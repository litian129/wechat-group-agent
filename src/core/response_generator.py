# -*- coding: utf-8 -*-
"""响应生成器 - 生成最终回复内容"""
import json
from pathlib import Path
from typing import List
from ..models.response import ResponseItem
from .message_parser import MessageParser


class ResponseGenerator:
    """根据触发类型生成响应"""

    def __init__(self, config_path: str = None, master_info_path: str = None):
        if config_path is None:
            base_dir = Path(__file__).parent.parent.parent
            config_path = base_dir / "config" / "agent_config.json"
        if master_info_path is None:
            base_dir = Path(__file__).parent.parent.parent
            master_info_path = base_dir / "config" / "master_info.json"

        self.config_path = Path(config_path)
        self.master_info_path = Path(master_info_path)
        self._load_config()

    def _load_config(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        with open(self.master_info_path, "r", encoding="utf-8") as f:
            self.master_info = json.load(f)

        self.templates = self.config.get("response_templates", {})

    def generate_booking_response(self, message_content: str, master_name: str = None) -> List[ResponseItem]:
        """生成触发1(订单)的响应"""
        # 1. 提取订单信息
        booking_info = MessageParser.extract_booking_info(message_content)

        # 2. 获取师傅信息
        master = self._find_master(master_name)
        if master is None:
            master = self.master_info.get("masters", [{}])[0] if self.master_info.get("masters") else {}

        customer_service = self.master_info.get("customer_service", {})

        # 3. 构建模板变量
        variables = {
            "master_display_name": master.get("display_name", "师傅"),
            "master_name": master.get("display_name", "师傅"),
            "master_phone": master.get("phone", ""),
            "customer_service_name": customer_service.get("name", "除醛顾问"),
            "customer_service_phone": customer_service.get("phone", ""),
        }

        # 4. 生成前摇文案1
        preamble_1 = self.templates.get("booking_preamble_1", "")

        # 5. 生成前摇文案2 (含师傅信息)
        preamble_2_template = self.templates.get("booking_preamble_2", "")
        preamble_2 = self._fill_template(preamble_2_template, variables)

        # 6. 生成@师傅行动
        action_template = self.templates.get("booking_action", "")
        action = self._fill_template(action_template, variables)

        # 7. 组装响应
        responses = [
            ResponseItem(at_target=[], content=preamble_1),
            ResponseItem(at_target=[], content=preamble_2),
            ResponseItem(
                at_target=[f"@{master.get('display_name', '师傅')}"],
                content=action,
            ),
        ]

        return responses

    def generate_timeout_response(self, trigger_type: str) -> ResponseItem:
        """生成触发2-5(超时)的响应"""
        timeout_templates = {
            "appointment_timeout": {
                "at_targets": ["@师傅"],
                "template_key": "appointment_timeout",
            },
            "contract_timeout": {
                "at_targets": ["@销售"],
                "template_key": "contract_timeout_general",
            },
            "construction_timeout": {
                "at_targets": ["@销售"],
                "template_key": "construction_timeout",
            },
            "medication_timeout": {
                "at_targets": ["@销售", "@工程部负责人"],
                "template_key": "medication_timeout",
            },
        }

        config = timeout_templates.get(trigger_type)
        if not config:
            return ResponseItem(at_target=[], content="")

        template = self.templates.get(config["template_key"], "")
        return ResponseItem(
            at_target=config["at_targets"],
            content=template,
        )

    def _find_master(self, master_name: str = None) -> dict:
        """查找师傅信息"""
        masters = self.master_info.get("masters", [])
        if not masters:
            return {}

        if master_name:
            for m in masters:
                if master_name in m.get("display_name", "") or master_name in m.get("wechat_name", ""):
                    return m

        # 默认返回第一个师傅
        return masters[0]

    @staticmethod
    def _fill_template(template: str, variables: dict) -> str:
        """模板变量填充"""
        result = template
        for key, value in variables.items():
            result = result.replace("{" + key + "}", str(value))
        return result
