"""DawnDine 启动入口：默认启动 Gradio 网页，也可进入命令行对话。

- 解析 --web（默认）/ --cli / --host / --port / --share / --no-browser；
- 统一配置一次 logging；
- 初始化运行目录与 SQLite 日程库，分发到 dawndine.ui.app.launch 或 dawndine.cli.run_cli。
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from dawndine.config import (
    APP_TITLE,
    DASHSCOPE_API_KEY_ENV,
    LOG_DATE_FORMAT,
    LOG_FORMAT,
    ensure_runtime_dirs,
    get_server_host,
    get_server_port,
)
from dawndine.db import init_db
from dawndine.llm import get_env_api_key

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """配置全局日志，只允许在这里调用 basicConfig。"""

    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=[logging.StreamHandler(stream=sys.stdout)],
        force=True,
    )
    # 降低第三方 HTTP / 向量库的噪声，保留业务模块日志。
    for noisy_logger in ("httpx", "httpcore", "urllib3", "chromadb"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""

    parser = argparse.ArgumentParser(
        prog="dawndine",
        description=f"{APP_TITLE}：默认启动 Gradio 网页，也可进入命令行对话。",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--web", action="store_true", help="启动 Gradio 网页（默认）。")
    mode.add_argument("--cli", action="store_true", help="启动命令行对话。")
    parser.add_argument(
        "--host",
        default=None,
        help="网页监听地址；默认 127.0.0.1，局域网共享可用 0.0.0.0。",
    )
    parser.add_argument("--port", type=int, default=None, help="网页端口；默认 7860。")
    parser.add_argument(
        "--share",
        action="store_true",
        help="生成 Gradio 临时公网链接（需要互联网）。",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="启动后不自动打开浏览器。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """程序主入口，返回进程退出码。"""

    configure_logging()
    ensure_runtime_dirs()
    init_db()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    has_key = bool(get_env_api_key())
    if not has_key:
        logger.warning(
            "未配置 %s；网页仍可启动，聊天与知识库检索会提示配置 Key。",
            DASHSCOPE_API_KEY_ENV,
        )

    try:
        if args.cli:
            logger.info("启动命令行模式。")
            from dawndine.cli import run_cli

            run_cli()
        else:
            host = (args.host or get_server_host()).strip() or "127.0.0.1"
            port = args.port or get_server_port()
            display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
            logger.info("启动 Web 模式：http://%s:%s", display_host, port)
            if args.share:
                logger.info("已开启 --share，启动后会输出临时公网链接。")
            from dawndine.ui.app import launch

            launch(
                inbrowser=False if args.no_browser else None,
                share=True if args.share else None,
                server_name=host,
                server_port=port,
            )
            logger.info("Web 服务已停止。")
    except KeyboardInterrupt:
        logger.info("收到中断信号，DawnDine 已退出。")
        return 130
    except Exception:
        logger.exception("DawnDine 启动或运行失败")
        print(
            "\n启动失败。请检查：\n"
            "1. 是否已执行 uv sync；\n"
            "2. .env 中是否配置 DASHSCOPE_API_KEY；\n"
            "3. 7860 端口是否被占用；\n"
            "4. 详细错误见上方日志。\n",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
