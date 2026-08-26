# -*- coding: utf-8 -*-
"""消息解析器 - 解析输入JSON"""
import json
from pathlib import Path
from ..models.message import ChatSession, Message


class MessageParser:
    """解析群聊会话窗口JSON"""

    @staticmethod
    def parse_file(file_path: str) -> ChatSession:
        """从文件解析JSON"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"输入文件不存在: {file_path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return MessageParser.parse_dict(data)

    @staticmethod
    def parse_dict(data: dict) -> ChatSession:
        """从字典解析"""
        return ChatSession.from_dict(data)

    @staticmethod
    def parse_json_str(json_str: str) -> ChatSession:
        """从JSON字符串解析"""
        data = json.loads(json_str)
        return MessageParser.parse_dict(data)

    @staticmethod
    def extract_booking_info(content: str) -> dict:
        """从订单消息中提取结构化信息"""
        import re
        info = {}
        # 匹配 "关键词：值" 或 "关键词:值" 模式
        # 支持中文冒号和英文冒号
        pattern = r'([\u4e00-\u9fa5A-Za-z]{2,8})[：:]\s*([^\n\r]+?)(?=[\u4e00-\u9fa5A-Za-z]{2,8}[：:]|$)'
        matches = re.findall(pattern, content)
        for key, value in matches:
            key = key.strip()
            value = value.strip()
            info[key] = value
        return info
