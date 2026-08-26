# -*- coding: utf-8 -*-
"""
统一日志配置

- 控制台输出到 stderr (不干扰 CLI 的 stdout JSON 输出)
- 文件输出: logs/agent.log, 滚动分割 (单文件 10MB, 保留 5 个备份)
- 级别优先级: 显式参数 > 环境变量 AGENT_LOG_LEVEL > 配置文件 > INFO
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_LOG_FILE = "agent.log"

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def setup_logging(level=None, log_dir=None, to_console=True, to_file=True):
    """初始化全局日志配置 (幂等, 重复调用只调整级别)"""
    global _initialized
    root = logging.getLogger()

    if level is None:
        level = os.environ.get("AGENT_LOG_LEVEL", "INFO")
    root.setLevel(str(level).upper())
    # DEBUG 模式下压制第三方 HTTP 库的底层连接日志, 避免刷屏
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.INFO)

    if _initialized:
        return root

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    if to_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    if to_file:
        directory = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        try:
            # exist_ok 兼容 Windows 卷挂载目录 (不支持 mkdir -p 语义)
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                directory / DEFAULT_LOG_FILE,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as e:
            root.warning("日志文件目录不可写, 仅控制台输出: %s", e)

    _initialized = True
    return root


def truncate(text, limit: int = 100) -> str:
    """截断过长内容用于日志展示"""
    text = str(text).replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(共{len(text)}字符)"
