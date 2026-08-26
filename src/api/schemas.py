# -*- coding: utf-8 -*-
"""API 请求/响应数据模型"""
from typing import Any, Optional

from pydantic import BaseModel


class StartTaskRequest(BaseModel):
    """开始任务请求: input_file 与 data 二选一"""
    input_file: Optional[str] = None      # input/ 下的文件路径 (相对项目根或绝对路径)
    data: Optional[Any] = None            # 直接提交的会话数据


class TaskCreatedResponse(BaseModel):
    """任务创建响应"""
    task_id: str
    status: str
    input_file: Optional[str] = None
    created_at: str


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: str                            # pending/running/success/failed
    input_file: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    output_file: Optional[str] = None
    error: Optional[str] = None


class TaskResultResponse(BaseModel):
    """任务结果响应"""
    task_id: str
    status: str
    output_file: Optional[str] = None
    result: Optional[Any] = None
