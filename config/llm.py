"""DashScope / Qwen 模型工厂与动态 API Key 解析。

本文件职责：
- 从 .env 读取 DASHSCOPE_API_KEY，作为未填写界面 Key 时的回退；
- 通过 get_llm(api_key) 按请求动态创建 Qwen ChatOpenAI；
- 通过 get_vision_llm(api_key) 创建 Qwen-VL 视觉模型；
- 从 LangGraph RunnableConfig 中读取当前请求的 Key；
- 关闭 Qwen thinking，且绝不在日志中输出 Key 内容。

依赖：constants.py、python-dotenv、langchain-openai。
被调用：graph.py、tools/compliance.py、modules/vision.py、app.py、cli.py。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from constants import (
    DASHSCOPE_API_KEY_ENV,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_VL_MODEL_ENV,
    ENV_FILE,
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS,
    LLM_PLACEHOLDER_API_KEY,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
    QWEN_MODEL,
    QWEN_VL_MODEL,
)

logger = logging.getLogger(__name__)

# override=False：不覆盖用户已注入的环境变量，便于 CI / PyCharm 配置。
load_dotenv(dotenv_path=ENV_FILE, override=False)
_warned_missing = False


def get_env_api_key() -> str:
    """读取 .env / 进程环境中的百炼 Key；没有则返回空字符串。"""

    load_dotenv(dotenv_path=ENV_FILE, override=False)
    return (os.getenv(DASHSCOPE_API_KEY_ENV) or "").strip()


def resolve_api_key(api_key: str | None = None) -> str:
    """优先使用界面传入 Key，其次回退到 .env。"""

    return (api_key or "").strip() or get_env_api_key()


def api_key_configured(api_key: str | None = None) -> bool:
    """当前请求是否具备可用 Key。"""

    return bool(resolve_api_key(api_key))


def key_source(api_key: str | None = None) -> str:
    """返回 ui / env / missing，仅用于界面提示，不暴露 Key。"""

    if (api_key or "").strip():
        return "ui"
    if get_env_api_key():
        return "env"
    return "missing"


def api_key_from_config(config: Mapping[str, Any] | None = None) -> str:
    """从 LangGraph RunnableConfig 中读取当前请求的 API Key。"""

    if not config:
        return ""
    configurable = config.get("configurable") or {}
    if not isinstance(configurable, Mapping):
        return ""
    return str(configurable.get("api_key") or "").strip()


def _warn_missing_key_once() -> None:
    """只提示一次缺少 Key，避免每次请求刷屏。"""

    global _warned_missing
    if not _warned_missing:
        logger.warning("当前请求未配置 %s，模型调用将失败。", DASHSCOPE_API_KEY_ENV)
        _warned_missing = True


def _build_chat_model(model: str, api_key: str | None, max_tokens: int) -> ChatOpenAI:
    """构造 ChatOpenAI；这里统一关闭 thinking 并设置超时。"""

    resolved = resolve_api_key(api_key)
    if not resolved:
        _warn_missing_key_once()
    return ChatOpenAI(
        model=model,
        base_url=DASHSCOPE_BASE_URL,
        api_key=resolved or LLM_PLACEHOLDER_API_KEY,
        temperature=LLM_TEMPERATURE,
        max_tokens=max_tokens,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
        # 新版 langchain-openai 已显式支持 extra_body；避免旧写法告警。
        extra_body={"enable_thinking": False},
    )


def get_llm(api_key: str) -> ChatOpenAI:
    """按请求 Key 创建 qwen-plus 客户端。

    参数 Key 为空时回退到 .env；两者都没有时使用占位 Key 保证应用可启动，
    真正调用模型时会返回可读的鉴权错误。
    """

    source = key_source(api_key)
    logger.debug("创建文本模型客户端，model=%s，key_source=%s", QWEN_MODEL, source)
    return _build_chat_model(QWEN_MODEL, api_key, LLM_MAX_TOKENS)


def get_vision_model_name() -> str:
    """返回当前视觉模型 ID；允许用 DASHSCOPE_VL_MODEL 覆盖默认值。"""

    load_dotenv(dotenv_path=ENV_FILE, override=False)
    return (os.getenv(DASHSCOPE_VL_MODEL_ENV) or QWEN_VL_MODEL).strip()


def get_vision_llm(api_key: str) -> ChatOpenAI:
    """按请求 Key 创建视觉客户端，默认 qwen3-vl-plus。"""

    model = get_vision_model_name()
    source = key_source(api_key)
    logger.debug("创建视觉模型客户端，model=%s，key_source=%s", model, source)
    return _build_chat_model(model, api_key, max_tokens=1600)
