# -*- coding: utf-8 -*-
"""角色管理器 - 用户角色映射"""
import json
from pathlib import Path


class RoleManager:
    """管理用户ID到角色的映射"""

    def __init__(self, role_mapping_path: str = None):
        if role_mapping_path is None:
            base_dir = Path(__file__).parent.parent.parent
            role_mapping_path = base_dir / "config" / "role_mapping.json"
        self.role_mapping_path = Path(role_mapping_path)
        self._load_mapping()

    def _load_mapping(self):
        with open(self.role_mapping_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.mapping = data.get("role_mapping", {})
        self.default_role = data.get("default_role", "internal")
        # 导出格式(无显式角色标注)中未命中映射的外部发送者默认角色
        self.default_external_role = data.get("default_external_role", "customer")

    def get_role(self, userid: str) -> str:
        """根据用户显示名称获取角色"""
        if userid in self.mapping:
            return self.mapping[userid]
        # 模糊匹配：检查userid是否包含某些关键词
        for keyword, role in self.mapping.items():
            if keyword in userid:
                return role
        return self.default_role

    def normalize_role(self, role: str) -> str:
        """
        标准化角色名称，支持中文和英文输入
        中文角色 -> 英文角色标识
        英文角色 -> 原样返回
        """
        role_map = {
            # 中文角色名
            "销售": "sales",
            "师傅": "master",
            "工程部负责人": "eng_head",
            "工程负责人": "eng_head",
            "内部其他人": "internal",
            "内部": "internal",
            "客户": "customer",
            # 英文角色名（原样返回）
            "sales": "sales",
            "master": "master",
            "eng_head": "eng_head",
            "internal": "internal",
            "customer": "customer",
        }
        return role_map.get(role, role)

    def is_sales(self, role: str) -> bool:
        return self.normalize_role(role) == "sales"

    def is_customer(self, role: str) -> bool:
        return self.normalize_role(role) == "customer"

    def is_master(self, role: str) -> bool:
        return self.normalize_role(role) == "master"

    def is_eng_head(self, role: str) -> bool:
        return self.normalize_role(role) == "eng_head"
