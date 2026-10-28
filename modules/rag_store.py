"""本地 Chroma 知识库初始化与检索。

本文件职责：
- 首次使用时把 data/knowledge/*.txt 分块写入 Chroma；
- 使用请求级 DashScope Key 与 text-embedding-v1 生成向量；
- 提供 search(query, k=3, api_key=None) 与 rebuild_index(api_key)；
- 延迟初始化，未配置 API Key 时不阻塞应用启动。

依赖：config/llm.py、constants.py、chromadb、langchain-chroma、
      langchain-community、langchain-text-splitters。
被调用：tools/compliance.py、维护脚本。
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config.llm import resolve_api_key
from constants import (
    CHROMA_DIR,
    KNOWLEDGE_DIR,
    MISSING_API_KEY_MESSAGE,
    QWEN_EMBEDDING_MODEL,
    RAG_CHUNK_OVERLAP,
    RAG_CHUNK_SIZE,
    RAG_COLLECTION_NAME,
    RAG_TOP_K,
)

if TYPE_CHECKING:
    from langchain_chroma import Chroma

logger = logging.getLogger(__name__)

_VECTORSTORE: Chroma | None = None
_ACTIVE_KEY_FINGERPRINT = ""
_LOCK = threading.RLock()


def _read_text(path: Path) -> str:
    """优先 UTF-8，其次 GB18030 读取知识文件。"""

    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"知识文件编码无法识别：{path.name}")


def _load_documents() -> list[Any]:
    """读取并切分全部知识文件。"""

    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    files = sorted(KNOWLEDGE_DIR.glob("*.txt"))
    if not files:
        raise FileNotFoundError(
            f"知识库为空：{KNOWLEDGE_DIR} 下没有 .txt 文件，请放入制度文本后重建索引。"
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=RAG_CHUNK_SIZE,
        chunk_overlap=RAG_CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    documents: list[Any] = []
    for path in files:
        text = _read_text(path).strip()
        if not text:
            logger.warning("忽略空知识文件：%s", path.name)
            continue
        metadata = {"source": path.name, "path": str(path)}
        documents.append(Document(page_content=text, metadata=metadata))

    if not documents:
        raise ValueError("知识文件均为空，无法建立索引。")

    chunks = splitter.split_documents(documents)
    logger.info("知识库切分完成：%s 个文件，%s 个片段", len(documents), len(chunks))
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
    """创建 Chroma 客户端；集合为空时自动入库。"""

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

    if force_rebuild:
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
        chunks = _load_documents()
        ids = [
            f"{chunk.metadata.get('source', 'unknown')}::"
            f"{index}::{hashlib.sha1(chunk.page_content.encode('utf-8')).hexdigest()[:12]}"
            for index, chunk in enumerate(chunks)
        ]
        store.add_documents(chunks, ids=ids)
        count = store._collection.count()
        logger.info("Chroma 首次入库完成：%s 个片段", count)

    if count == 0:
        raise RuntimeError("Chroma 索引仍为空，请检查知识文件与嵌入模型配置。")
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
            payload.append(
                {
                    "content": document.page_content.strip(),
                    "source": str(document.metadata.get("source", "未知来源")),
                    "score": float(score),
                }
            )
    logger.info("知识库检索完成：query=%s，命中=%s", clean_query[:60], len(payload))
    return payload


def rebuild_index(api_key: str = "") -> int:
    """删除现有集合并从 data/knowledge 重新入库，返回片段数。"""

    global _VECTORSTORE, _ACTIVE_KEY_FINGERPRINT
    resolved = resolve_api_key(api_key)
    if not resolved:
        raise RuntimeError(MISSING_API_KEY_MESSAGE)
    with _LOCK:
        if _VECTORSTORE is not None:
            try:
                _VECTORSTORE.delete_collection()
            except Exception:
                logger.debug("删除旧集合失败或集合不存在。")
            _VECTORSTORE = None
            _ACTIVE_KEY_FINGERPRINT = ""
        store = _create_vectorstore(resolved, force_rebuild=False)
        _VECTORSTORE = store
        _ACTIVE_KEY_FINGERPRINT = _fingerprint(resolved)
        count = int(store._collection.count())
    logger.info("知识库重建完成：%s 个片段", count)
    return count
