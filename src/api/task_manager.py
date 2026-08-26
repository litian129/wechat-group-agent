# -*- coding: utf-8 -*-
"""异步任务管理器 - 创建/执行/跟踪智能体处理任务"""
import asyncio
import json
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class TaskInfo:
    """单个任务的状态与结果"""
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    input_file: Optional[str] = None
    data: Optional[Any] = None
    created_at: str = field(default_factory=_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    output_file: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None

    def to_status_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "input_file": self.input_file,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output_file": self.output_file,
            "error": self.error,
        }


class TaskManager:
    """管理异步任务的创建、后台执行与状态查询"""

    def __init__(self, agent, output_dir: Path = None, max_history: int = 200):
        self.agent = agent
        self.output_dir = Path(output_dir) if output_dir else None
        self.max_history = max_history
        self._tasks: "OrderedDict[str, TaskInfo]" = OrderedDict()
        self._background_tasks: set = set()

    # ------------------------------------------------------------------
    # 任务创建与提交
    # ------------------------------------------------------------------
    def create_task(self, input_file: str = None, data: Any = None) -> TaskInfo:
        task_id = uuid.uuid4().hex[:12]
        task = TaskInfo(task_id=task_id, input_file=input_file, data=data)
        self._tasks[task_id] = task
        self._trim_history()
        logger.info("任务已创建: task_id=%s 来源=%s", task_id,
                    input_file if input_file else "(内联data)")
        return task

    def submit(self, task: TaskInfo):
        """提交任务到后台异步执行"""
        bg = asyncio.create_task(self._execute(task))
        self._background_tasks.add(bg)
        bg.add_done_callback(self._background_tasks.discard)

    async def _execute(self, task: TaskInfo):
        task.status = TaskStatus.RUNNING
        task.started_at = _now()
        started = time.perf_counter()
        logger.info("任务开始执行: task_id=%s 来源=%s", task.task_id,
                    task.input_file if task.input_file else "(内联data)")
        try:
            if task.input_file:
                result = await self.agent.aprocess_auto(task.input_file)
            else:
                result = await self.agent.aprocess_data(task.data)
            if task.input_file and self.output_dir is not None:
                task.output_file = self._write_output(task, result)
            task.result = result
            task.status = TaskStatus.SUCCESS
            summary = result.get("summary") if isinstance(result, dict) else None
            logger.info("任务执行成功: task_id=%s 耗时=%.0fms summary=%s output=%s",
                        task.task_id, (time.perf_counter() - started) * 1000,
                        summary if summary else "(传统格式单会话)", task.output_file)
        except Exception as e:  # noqa: BLE001
            logger.exception("任务执行失败: task_id=%s 耗时=%.0fms",
                             task.task_id, (time.perf_counter() - started) * 1000)
            task.status = TaskStatus.FAILED
            task.error = str(e)
        finally:
            task.finished_at = _now()

    def _write_output(self, task: TaskInfo, result: dict) -> str:
        """将结果写入 output 目录: {输入文件名}_result.json"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(task.input_file).stem
        out_path = self.output_dir / f"{stem}_result.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info("任务结果已落盘: task_id=%s -> %s", task.task_id, out_path)
        return str(out_path)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get(self, task_id: str) -> Optional[TaskInfo]:
        return self._tasks.get(task_id)

    def list_tasks(self):
        return list(self._tasks.values())

    def _trim_history(self):
        while len(self._tasks) > self.max_history:
            self._tasks.popitem(last=False)
