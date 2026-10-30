"""本地 Chroma 知识库初始化与检索。

本文件职责：
- 把 data/knowledge/*.txt 与 data/knowledge/wiki.json 分块写入 Chroma；
- Wiki 条目按 content 切片，metadata 保留 entity / category / title / wiki_id；
- 通过 manifest 指纹检测知识文件增删改，自动重建索引，避免新增制度不生效；
- 使用请求级 DashScope Key 与 text-embedding-v1 生成向量；
- 提供 search(query, k=RAG_TOP_K, api_key=None) 与 rebuild_index(api_key)；
- 延迟初始化，未配置 API Key 时不阻塞应用启动。

依赖：dawndine.llm、dawndine.config、dawndine.knowledge.wiki、chromadb、
      langchain-chroma、langchain-community、langchain-text-splitters。
被调用：dawndine.agent.tools 各工具、dawndine.agent.graph、app.py、维护脚本。
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dawndine.config import (
    CHROMA_DIR,
    KNOWLEDGE_DIR,
    KNOWLEDGE_MANIFEST_FILE,
    MISSING_API_KEY_MESSAGE,
    QWEN_EMBEDDING_MODEL,
    RAG_CHUNK_OVERLAP,
    RAG_CHUNK_SIZE,
    RAG_COLLECTION_NAME,
    RAG_TOP_K,
)
from dawndine.knowledge.wiki import load_wiki
from dawndine.llm import resolve_api_key

if TYPE_CHECKING:
    from langchain_chroma import Chroma

logger = logging.getLogger(__name__)

_VECTORSTORE: Chroma | None = None
_ACTIVE_KEY_FINGERPRINT = ""
_LOCK = threading.RLock()
_MANIFEST_VERSION = 2  # v2：Wiki 分片正文带编号（[E001]），旧索引需重建


def _read_text(path: Path) -> str:
    """优先 UTF-8，其次 GB18030 读取知识文件。"""

    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"知识文件编码无法识别：{path.name}")


def _knowledge_files() -> list[Path]:
    """返回知识文件列表，按文件名稳定排序。"""

    return sorted(KNOWLEDGE_DIR.glob("*.txt"))


def _wiki_file() -> Path | None:
    """返回结构化 Wiki JSON；不存在时返回 None。"""

    path = KNOWLEDGE_DIR / "wiki.json"
    return path if path.is_file() else None


def _wiki_documents() -> list[Any]:
    """把 Wiki 条目转换为待切分的 Document，metadata 携带 entity/category。"""

    from langchain_core.documents import Document

    wiki = _wiki_file()
    if wiki is None:
        return []
    documents: list[Any] = []
    for entry in load_wiki(wiki):
        metadata = {
            "source": wiki.name,
            "path": str(wiki),
            "wiki_id": entry["id"],
            "entity": entry["entity"],
            "category": entry["category"],
            "title": entry["title"],
        }
        # 编号随正文一起入库，回答引用知识时可带上 E001 这类编号。
        text = (
            f"[{entry['id']}]【{entry['category']}】{entry['title']}（{entry['entity']}）\n"
            f"{entry['content']}"
        )
        documents.append(Document(page_content=text, metadata=metadata))
    return documents


def knowledge_fingerprint(files: list[Path] | None = None) -> str:
    """计算知识文件指纹；文件增删改都会改变结果。

    指纹包含文件名、文件内容和切片参数，用于判断 Chroma 索引是否过期。
    读取失败的文件用文件名占位，避免启动时因单个坏文件直接崩溃。
    Wiki JSON 一并计入指纹，改条目后会自动重建索引。
    """

    digest = hashlib.sha256()
    digest.update(f"v{_MANIFEST_VERSION}:{RAG_CHUNK_SIZE}:{RAG_CHUNK_OVERLAP}".encode())
    for path in files if files is not None else _knowledge_files():
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        try:
            content = _read_text(path)
        except (OSError, UnicodeError) as exc:
            logger.warning("读取知识文件失败，按文件名计入指纹：%s（%s）", path.name, exc)
            content = ""
        digest.update(content.encode("utf-8"))
        digest.update(b"\0")
    wiki = _wiki_file()
    if wiki is not None:
        digest.update(wiki.name.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(_read_text(wiki).encode("utf-8"))
        except (OSError, UnicodeError) as exc:
            logger.warning("读取 Wiki 指纹失败：%s（%s）", wiki.name, exc)
        digest.update(b"\0")
    return digest.hexdigest()


def _read_manifest() -> dict[str, Any]:
    """读取索引 manifest；不存在或损坏时返回空字典。"""

    try:
        raw = KNOWLEDGE_MANIFEST_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_manifest(fingerprint: str, count: int, files: list[Path]) -> None:
    """写入索引 manifest；失败不阻塞检索，只记录日志。"""

    wiki = _wiki_file()
    payload = {
        "version": _MANIFEST_VERSION,
        "fingerprint": fingerprint,
        "count": count,
        "chunk_size": RAG_CHUNK_SIZE,
        "chunk_overlap": RAG_CHUNK_OVERLAP,
        "files": [path.name for path in files] + ([wiki.name] if wiki is not None else []),
    }
    try:
        KNOWLEDGE_MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        KNOWLEDGE_MANIFEST_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("写入知识库 manifest 失败：%s", exc)


def _index_needs_rebuild(count: int, fingerprint: str) -> bool:
    """判断现有 Chroma 集合是否与当前知识文件一致。"""

    if count == 0:
        return True
    manifest = _read_manifest()
    if manifest.get("fingerprint") != fingerprint:
        logger.info(
            "知识文件已变化或缺少 manifest（旧指纹=%s），将自动重建索引。",
            str(manifest.get("fingerprint") or "无")[:12],
        )
        return True
    recorded_count = manifest.get("count")
    if not isinstance(recorded_count, int) or recorded_count != count:
        logger.info("知识库片段数与 manifest 不一致，将自动重建索引。")
        return True
    return False


def _document(text: str, metadata: dict[str, Any]) -> Any:
    """构造 LangChain Document；把依赖导入延迟到调用时。"""

    from langchain_core.documents import Document

    return Document(page_content=text, metadata=metadata)


def _load_documents(files: list[Path] | None = None) -> list[Any]:
    """读取并切分全部知识来源：制度 txt + 结构化 Wiki JSON。"""

    from langchain_text_splitters import RecursiveCharacterTextSplitter

    selected_files = files if files is not None else _knowledge_files()
    wiki_documents = _wiki_documents()
    if not selected_files and not wiki_documents:
        raise FileNotFoundError(
            f"知识库为空：{KNOWLEDGE_DIR} 下没有 .txt 或 wiki.json，请放入制度文本后重建索引。"
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=RAG_CHUNK_SIZE,
        chunk_overlap=RAG_CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    documents: list[Any] = []
    for path in selected_files:
        text = _read_text(path).strip()
        if not text:
            logger.warning("忽略空知识文件：%s", path.name)
            continue
        metadata = {"source": path.name, "path": str(path)}
        documents.append(_document(text, metadata))
    documents.extend(wiki_documents)

    if not documents:
        raise ValueError("知识文件均为空，无法建立索引。")

    chunks = splitter.split_documents(documents)
    logger.info(
        "知识库切分完成：%s 个 txt + %s 条 Wiki，共 %s 个片段",
        len(selected_files),
        len(wiki_documents),
        len(chunks),
    )
    return chunks


def _build_embedding(api_key: str) -> Any:
    """用请求 Key 构造 DashScope 向量模型；Key 缺失时给出明确错误。"""

    from langchain_community.embeddings import DashScopeEmbeddings

    resolved = resolve_api_key(api_key)
    if not resolved:
        raise RuntimeError(MISSING_API_KEY_MESSAGE)
    # 必须显式指定 DashScopeEmbeddings，否则默认 OpenAI Embeddings 会 401。
    return DashScopeEmbeddings(
        model=QWEN_EMBEDDING_MODEL,
        dashscope_api_key=resolved,
    )


def _create_vectorstore(api_key: str, force_rebuild: bool = False) -> Chroma:
    """创建 Chroma 客户端；集合为空或知识文件变化时自动入库/重建。"""

    import chromadb
    from chromadb.config import Settings
    from langchain_chroma import Chroma

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    embedding = _build_embedding(api_key)
    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    store = Chroma(
        client=client,
        collection_name=RAG_COLLECTION_NAME,
        embedding_function=embedding,
        collection_metadata={"hnsw:space": "cosine"},
    )

    files = _knowledge_files()
    fingerprint = knowledge_fingerprint(files)
    count = store._collection.count()
    needs_rebuild = force_rebuild or _index_needs_rebuild(count, fingerprint)

    if needs_rebuild and count > 0:
        try:
            store.delete_collection()
        except Exception:  # 集合可能尚不存在
            logger.debug("删除旧集合时未找到集合，继续新建。")
        store = Chroma(
            client=client,
            collection_name=RAG_COLLECTION_NAME,
            embedding_function=embedding,
            collection_metadata={"hnsw:space": "cosine"},
        )
        count = store._collection.count()

    if count == 0:
        chunks = _load_documents(files)
        ids = [
            f"{chunk.metadata.get('source', 'unknown')}::"
            f"{index}::{hashlib.sha1(chunk.page_content.encode('utf-8')).hexdigest()[:12]}"
            for index, chunk in enumerate(chunks)
        ]
        store.add_documents(chunks, ids=ids)
        count = store._collection.count()
        logger.info("Chroma 入库完成：%s 个片段", count)

    if count == 0:
        raise RuntimeError("Chroma 索引仍为空，请检查知识文件与嵌入模型配置。")

    if needs_rebuild or force_rebuild:
        _write_manifest(fingerprint, count, files)
    return store


def _fingerprint(api_key: str) -> str:
    """返回 Key 的不可逆指纹，仅用于日志/切换判断。"""

    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def get_vectorstore(api_key: str = "", force_rebuild: bool = False) -> Chroma:
    """获取全局 Chroma 实例，并把嵌入函数切换到当前请求 Key。

    Chroma 集合是共享的持久化索引；不同用户 Key 只影响查询/入库时
    使用的嵌入客户端。所有设置与检索都在同一把锁内串行，避免并发串 Key。
    """

    global _VECTORSTORE, _ACTIVE_KEY_FINGERPRINT

    resolved = resolve_api_key(api_key)
    if not resolved:
        raise RuntimeError(MISSING_API_KEY_MESSAGE)

    with _LOCK:
        fingerprint = _fingerprint(resolved)
        if _VECTORSTORE is None or force_rebuild:
            _VECTORSTORE = _create_vectorstore(resolved, force_rebuild=force_rebuild)
            _ACTIVE_KEY_FINGERPRINT = fingerprint
        elif _read_manifest().get("fingerprint") != knowledge_fingerprint():
            # 运行期间知识文件被增删改：自动重建，避免新制度检索不到。
            logger.info("检测到知识文件变化，自动重建索引。")
            _VECTORSTORE = _create_vectorstore(resolved, force_rebuild=True)
            _ACTIVE_KEY_FINGERPRINT = fingerprint
        elif fingerprint != _ACTIVE_KEY_FINGERPRINT:
            # 不重建索引，只替换 query embedding，避免不同用户 Key 串线。
            _VECTORSTORE._embedding_function = _build_embedding(resolved)
            _ACTIVE_KEY_FINGERPRINT = fingerprint
        return _VECTORSTORE


def search(query: str, k: int = RAG_TOP_K, api_key: str = "") -> list[dict[str, Any]]:
    """检索本地知识库，返回内容、来源与距离分数。"""

    clean_query = (query or "").strip()
    if not clean_query:
        raise ValueError("检索问题不能为空。")

    safe_k = max(1, min(int(k), 10))
    with _LOCK:
        store = get_vectorstore(api_key=api_key)
        results = store.similarity_search_with_score(clean_query, k=safe_k)
        payload: list[dict[str, Any]] = []
        for document, score in results:
            item: dict[str, Any] = {
                "content": document.page_content.strip(),
                "source": str(document.metadata.get("source", "未知来源")),
                "score": float(score),
            }
            for key in ("entity", "category", "title", "wiki_id"):
                value = document.metadata.get(key)
                if value:
                    item[key] = str(value)
            payload.append(item)
    logger.info("知识库检索完成：query=%s，命中=%s", clean_query[:60], len(payload))
    return payload


def rebuild_index(api_key: str = "") -> int:
    """删除现有集合并从 data/knowledge 重新入库，返回片段数。"""

    global _VECTORSTORE, _ACTIVE_KEY_FINGERPRINT
    resolved = resolve_api_key(api_key)
    if not resolved:
        raise RuntimeError(MISSING_API_KEY_MESSAGE)
    with _LOCK:
        _VECTORSTORE = None
        _ACTIVE_KEY_FINGERPRINT = ""
        store = _create_vectorstore(resolved, force_rebuild=True)
        _VECTORSTORE = store
        _ACTIVE_KEY_FINGERPRINT = _fingerprint(resolved)
        count = int(store._collection.count())
    logger.info("知识库重建完成：%s 个片段", count)
    return count


def knowledge_status() -> dict[str, Any]:
    """返回知识文件与索引的一致性状态，供设置区展示和测试使用。"""

    files = _knowledge_files()
    wiki = _wiki_file()
    wiki_entries = len(load_wiki(wiki)) if wiki is not None else 0
    fingerprint = knowledge_fingerprint(files)
    manifest = _read_manifest()
    names = [path.name for path in files] + ([wiki.name] if wiki is not None else [])
    return {
        "file_count": len(names),
        "files": names,
        "wiki_entries": wiki_entries,
        "fingerprint": fingerprint,
        "manifest_fingerprint": str(manifest.get("fingerprint") or ""),
        "indexed_count": int(manifest.get("count") or 0),
        "up_to_date": bool(manifest.get("fingerprint") == fingerprint),
    }
