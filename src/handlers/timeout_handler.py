# -*- coding: utf-8 -*-
"""触发2-5处理器: 客户咨询超时无响应"""
from ..models.message import Message
from ..models.response import ResponseItem
from ..core.response_generator import ResponseGenerator
from ..core.trigger_engine import TriggerEngine


class TimeoutHandler:
    """处理客户咨询超时无响应的触发"""

    def __init__(self, response_generator: ResponseGenerator):
        self.response_generator = response_generator

    def handle(self, trigger_type: str, message: Message) -> ResponseItem:
        """
        处理超时触发，生成@对应角色 + 安抚文案

        触发类型与@对象映射:
        - appointment_timeout  -> @师傅
        - contract_timeout     -> @销售
        - construction_timeout -> @销售
        - medication_timeout   -> @销售 + @工程部负责人
        """
        return self.response_generator.generate_timeout_response(trigger_type)
