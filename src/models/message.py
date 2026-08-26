# -*- coding: utf-8 -*-
"""消息数据模型"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Message:
    """单条群聊消息"""
    userid: str                                    # 用户显示名称
    role: str = "internal"                          # 角色: sales/master/eng_head/internal/customer
    content: str = ""                               # 消息内容
    timestamp: str = ""                             # ISO时间戳
    msgid: str = ""                                 # 唯一消息ID
    is_last_in_window: bool = False                 # 是否在3-7分钟超时窗口内
    has_response_after: bool = False                # 该消息后是否有人响应

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            userid=data.get("userid", ""),
            role=data.get("role", "internal"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", ""),
            msgid=data.get("msgid", ""),
            is_last_in_window=data.get("is_last_in_window", False),
            has_response_after=data.get("has_response_after", False),
        )


@dataclass
class ChatSession:
    """群聊会话窗口"""
    group_name: str                                # 群名
    messages: List[Message] = field(default_factory=list)  # 消息列表

    @classmethod
    def from_dict(cls, data: dict) -> "ChatSession":
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return cls(
            group_name=data.get("group_name", ""),
            messages=messages,
        )

    @property
    def last_message(self) -> Optional[Message]:
        return self.messages[-1] if self.messages else None
