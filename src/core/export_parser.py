# -*- coding: utf-8 -*-
"""微信会话导出格式解析器

导出格式结构 (区别于传统 group_name/messages 格式):
[
  {
    "meta": {"sessionTitle": ..., "isGroup": ..., "exportedAt": ..., ...},
    "message": [
      {"createTime": ..., "senderDisplay": ..., "isSend": ..., "text": ..., "kind": ...},
      ...
    ]
  },
  ...
]
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List

from ..models.message import ChatSession, Message
from .role_manager import RoleManager

logger = logging.getLogger(__name__)


class ExportParser:
    """解析会话导出文件为 ChatSession 列表"""

    TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

    def __init__(self, role_manager: RoleManager = None, config_path: str = None):
        self.role_manager = role_manager or RoleManager()
        # 说明: 输入的会话快照本身已是 3-7 分钟窗口内的消息,
        # 解析与触发判定均不再对时间戳做窗口过滤,
        # 超时仅依据快照标记 (消息之后无他人回应 = 未响应/窗口内)。

    @staticmethod
    def is_export_format(data) -> bool:
        """判断数据是否为导出格式 (会话列表或单个 {meta, message} 对象)"""
        if isinstance(data, list):
            return bool(data) and isinstance(data[0], dict) and "meta" in data[0]
        if isinstance(data, dict):
            return "meta" in data and "message" in data
        return False

    def parse(self, data) -> List[ChatSession]:
        """解析导出数据 (列表或单会话对象)"""
        items = [data] if isinstance(data, dict) else data
        return [self._parse_session(item) for item in items if isinstance(item, dict)]

    def parse_file(self, file_path: str) -> List[ChatSession]:
        """解析导出文件"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"输入文件不存在: {file_path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not self.is_export_format(data):
            raise ValueError(f"文件不是导出格式(meta/message): {file_path}")
        return self.parse(data)

    def _parse_session(self, item: dict) -> ChatSession:
        meta = item.get("meta") or {}
        raw_messages = item.get("message") or []

        messages = []
        skipped_noise = 0
        for m in raw_messages:
            if not isinstance(m, dict):
                continue
            kind = str(m.get("kind") or "").strip().lower()
            # 系统消息(入群通知等)非对话内容, 对意图判定无价值
            if kind == "system":
                skipped_noise += 1
                continue
            text = (m.get("text") or "").strip()
            if not text:
                continue
            # 微信占位消息([图片]/[视频]/[语音]等)无文本判定价值
            if kind != "text" and text.startswith("[") and text.endswith("]"):
                skipped_noise += 1
                continue
            sender = m.get("senderDisplay") or m.get("senderUsername") or ""
            explicit_role = str(m.get("role") or "").strip()
            messages.append(Message(
                userid=sender,
                role=self._resolve_role(sender, bool(m.get("isSend")), explicit_role),
                content=text,
                timestamp=m.get("createTime", ""),
                msgid=str(m.get("serverId") or m.get("localId") or ""),
            ))

        # 导出消息可能按 seq 倒序, 统一按时间升序
        messages.sort(key=lambda msg: self._parse_time(msg.timestamp))
        self._annotate_response_flags(messages)

        # 解析结果日志 (排查角色推断与消息数量)
        role_stats = {}
        for m in messages:
            role_stats[m.role] = role_stats.get(m.role, 0) + 1
        unresponded = sum(1 for m in messages if not m.has_response_after)
        explicit_cnt = sum(1 for m in raw_messages
                           if isinstance(m, dict) and str(m.get("role") or "").strip())
        logger.info("解析会话[%s]: 有效文本消息%d条 过滤噪音消息%d条 显式role标注%d条 角色分布=%s 未获响应%d条",
                    meta.get("sessionTitle", ""), len(messages), skipped_noise,
                    explicit_cnt, role_stats, unresponded)

        return ChatSession(group_name=meta.get("sessionTitle", ""), messages=messages)

    def _resolve_role(self, sender: str, is_send: bool, explicit_role: str = "") -> str:
        """确定发送者角色

        优先级:
        1. 输入消息显式携带的 role 字段 (上游已明确标注谁说的, 最可靠)
        2. 本方账号发出 (isSend=true) 视为内部人员
        3. 命中 role_mapping 的使用映射结果
        4. 未命中映射的外部发送者使用 default_external_role (默认客户)
        """
        if explicit_role:
            normalized = self.role_manager.normalize_role(explicit_role)
            logger.debug("发送者[%s]使用输入显式role: %s -> %s",
                         sender, explicit_role, normalized)
            return normalized
        if is_send:
            return "internal"
        role = self.role_manager.get_role(sender)
        if role != self.role_manager.default_role:
            return role
        logger.debug("发送者[%s]未命中角色映射, 使用外部默认角色: %s",
                     sender, self.role_manager.default_external_role)
        return self.role_manager.default_external_role

    def _annotate_response_flags(self, messages: List[Message]):
        """标注 has_response_after / is_last_in_window

        快照语义: 仅当该消息之后有工作人员(角色非客户)的后续回复,
        才视为已被响应; 其他客户的后续发言不构成响应。
        规则引擎依据这两个标记判断超时触发。
        """
        for i, msg in enumerate(messages):
            responded = any(m.role != "customer" for m in messages[i + 1:])
            msg.has_response_after = responded
            msg.is_last_in_window = not responded

    def _parse_time(self, value: str) -> datetime:
        try:
            return datetime.strptime(value, self.TIME_FORMAT)
        except (ValueError, TypeError):
            return datetime.min
