# -*- coding: utf-8 -*-
"""
FastAPI 服务 - 智能体异步任务接口

接口:
  GET  /health                       健康检查
  POST /api/tasks                    开始任务 (input_file 或 data)
  GET  /api/tasks                    任务列表
  GET  /api/tasks/{task_id}/status   获取任务状态
  GET  /api/tasks/{task_id}/result   获取任务结果
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from ..main import WeComGroupAgent
from ..utils.logging_config import setup_logging
from ..watcher import InputWatcher
from .schemas import (
    StartTaskRequest,
    TaskCreatedResponse,
    TaskResultResponse,
    TaskStatusResponse,
)
from .task_manager import TaskManager, TaskStatus

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "api_config.json"


def load_api_config(config_path: str = None) -> dict:
    """加载 API 服务配置"""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def create_app(config: dict = None) -> FastAPI:
    """创建 FastAPI 应用"""
    if config is None:
        config = load_api_config()

    input_dir = PROJECT_ROOT / config.get("input_dir", "input")
    output_dir = PROJECT_ROOT / config.get("output_dir", "output")
    watcher_cfg = config.get("watcher", {}) or {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动: 初始化日志、智能体、任务管理器与输入文件夹监听器
        setup_logging(level=config.get("log_level"))
        logger.info("服务启动: input_dir=%s output_dir=%s watcher.enabled=%s",
                    input_dir, output_dir, watcher_cfg.get("enabled", True))
        agent = WeComGroupAgent()
        app.state.task_manager = TaskManager(agent, output_dir=output_dir)

        watcher_task = None
        if watcher_cfg.get("enabled", True):
            # 优先使用启动入口注入的实际端口 (支持 --port 覆盖配置)
            port = int(os.environ.get("AGENT_API_PORT") or config.get("port", 8000))
            api_url = watcher_cfg.get("api_base_url") or f"http://127.0.0.1:{port}"
            watcher = InputWatcher(
                input_dir=input_dir,
                api_url=api_url,
                poll_interval=float(watcher_cfg.get("poll_interval_seconds", 2)),
                state_path=PROJECT_ROOT / "state" / "watcher_state.json",
            )
            watcher_task = asyncio.create_task(watcher.run_forever())
            logger.info("输入文件夹监听已启动: %s -> %s", input_dir, api_url)
        try:
            yield
        finally:
            if watcher_task:
                watcher_task.cancel()

    app = FastAPI(
        title="企业微信群聊智能体服务",
        description="异步任务接口: 开始任务 / 获取任务状态 / 获取任务结果",
        version="1.1.0",
        lifespan=lifespan,
    )

    def _get_task_manager(request: Request) -> TaskManager:
        return request.app.state.task_manager

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "wechat-group-agent"}

    @app.post("/api/tasks", response_model=TaskCreatedResponse, status_code=202)
    async def start_task(payload: StartTaskRequest, request: Request):
        """开始任务: 传入 input_file (推荐) 或 data, 立即返回 task_id"""
        if not payload.input_file and payload.data is None:
            logger.warning("开始任务请求被拒绝: input_file 与 data 同时为空")
            raise HTTPException(status_code=400, detail="input_file 与 data 不能同时为空")
        logger.info("收到开始任务请求: input_file=%s",
                    payload.input_file if payload.input_file else "(内联data)")
        tm = _get_task_manager(request)
        task = tm.create_task(input_file=payload.input_file, data=payload.data)
        tm.submit(task)
        return TaskCreatedResponse(
            task_id=task.task_id,
            status=task.status.value,
            input_file=task.input_file,
            created_at=task.created_at,
        )

    @app.get("/api/tasks")
    async def list_tasks(request: Request):
        """任务列表 (含状态)"""
        tm = _get_task_manager(request)
        tasks = [t.to_status_dict() for t in tm.list_tasks()]
        return {"total": len(tasks), "tasks": tasks}

    @app.get("/api/tasks/{task_id}/status", response_model=TaskStatusResponse)
    async def task_status(task_id: str, request: Request):
        """获取任务状态"""
        task = _get_task_manager(request).get(task_id)
        if task is None:
            logger.warning("状态查询失败: 任务不存在 task_id=%s", task_id)
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
        logger.debug("状态查询: task_id=%s status=%s", task_id, task.status.value)
        return TaskStatusResponse(**task.to_status_dict())

    @app.get("/api/tasks/{task_id}/result", response_model=TaskResultResponse)
    async def task_result(task_id: str, request: Request):
        """获取任务结果 (任务未完成时返回 409)"""
        task = _get_task_manager(request).get(task_id)
        if task is None:
            logger.warning("结果查询失败: 任务不存在 task_id=%s", task_id)
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
        if task.status == TaskStatus.FAILED:
            logger.warning("结果查询失败: 任务已失败 task_id=%s error=%s", task_id, task.error)
            raise HTTPException(status_code=500, detail=f"任务执行失败: {task.error}")
        if task.status != TaskStatus.SUCCESS:
            logger.warning("结果查询拒绝: 任务未完成 task_id=%s status=%s",
                           task_id, task.status.value)
            raise HTTPException(
                status_code=409, detail=f"任务尚未完成, 当前状态: {task.status.value}"
            )
        logger.debug("结果查询成功: task_id=%s", task_id)
        return TaskResultResponse(
            task_id=task.task_id,
            status=task.status.value,
            output_file=task.output_file,
            result=task.result,
        )

    return app


app = create_app()
