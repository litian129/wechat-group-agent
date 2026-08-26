# -*- coding: utf-8 -*-
"""
API 服务启动入口

使用方式:
    python src/server.py [--host 127.0.0.1] [--port 8000] [--config config/api_config.json]

等价于:
    uvicorn src.api.app:app --host 127.0.0.1 --port 8000
"""
import argparse
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(description="企业微信群聊智能体 API 服务")
    parser.add_argument("--host", type=str, default=None, help="监听地址 (默认读配置)")
    parser.add_argument("--port", type=int, default=None, help="监听端口 (默认读配置)")
    parser.add_argument("--config", type=str, default=None,
                        help="API配置文件路径 (默认 config/api_config.json)")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument("--log-level", type=str, default=None,
                        help="日志级别 (DEBUG/INFO/WARNING, 默认环境变量或配置)")
    args = parser.parse_args()

    import uvicorn
    from src.api.app import load_api_config
    from src.utils.logging_config import setup_logging

    config = load_api_config(args.config)

    # 初始化日志: 命令行 > 环境变量 AGENT_LOG_LEVEL > 配置文件 > INFO
    log_level = (args.log_level or os.environ.get("AGENT_LOG_LEVEL")
                 or config.get("log_level", "INFO"))
    setup_logging(level=log_level)

    # 优先级: 命令行参数 > 环境变量 (Docker部署用) > 配置文件
    host = args.host or os.environ.get("AGENT_API_HOST") or config.get("host", "127.0.0.1")
    port = int(args.port or os.environ.get("AGENT_API_PORT") or config.get("port", 8000))

    # 注入实际端口, 供应用内监听器拼接开始任务接口地址
    os.environ["AGENT_API_PORT"] = str(port)

    print(f"启动智能体 API 服务: http://{host}:{port}  (API文档: /docs)")
    uvicorn.run("src.api.app:app", host=host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
