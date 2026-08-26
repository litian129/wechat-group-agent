# -*- coding: utf-8 -*-
"""响应数据模型"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional
import json


@dataclass
class ResponseItem:
    """单条响应"""
    at_target: List[str] = field(default_factory=list)  # @对象列表
    content: str = ""                                    # 回复内容

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentResponse:
    """智能体完整响应"""
    group_name: str = ""
    triggered: bool = False
    trigger_type: Optional[str] = None       # booking/appointment_timeout/contract_timeout/construction_timeout/medication_timeout
    responses: List[ResponseItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "group_name": self.group_name,
            "triggered": self.triggered,
            "trigger_type": self.trigger_type,
            "responses": [r.to_dict() for r in self.responses],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
