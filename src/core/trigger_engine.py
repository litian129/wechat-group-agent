# -*- coding: utf-8 -*-
"""触发引擎 - 评估5个触发条件"""
from typing import Optional
from ..models.message import Message
from .intent_classifier import IntentClassifier
from .role_manager import RoleManager


class TriggerEngine:
    """触发条件评估引擎"""

    # 触发类型枚举
    TRIGGER_BOOKING = "booking"
    TRIGGER_APPOINTMENT_TIMEOUT = "appointment_timeout"
    TRIGGER_CONTRACT_TIMEOUT = "contract_timeout"
    TRIGGER_CONSTRUCTION_TIMEOUT = "construction_timeout"
    TRIGGER_MEDICATION_TIMEOUT = "medication_timeout"
    TRIGGER_NONE = "none"

    # 意图到触发类型的映射 (超时场景)
    TIMEOUT_TRIGGER_MAP = {
        IntentClassifier.INTENT_APPOINTMENT: TRIGGER_APPOINTMENT_TIMEOUT,
        IntentClassifier.INTENT_CONTRACT: TRIGGER_CONTRACT_TIMEOUT,
        IntentClassifier.INTENT_CONSTRUCTION: TRIGGER_CONSTRUCTION_TIMEOUT,
        IntentClassifier.INTENT_MEDICATION: TRIGGER_MEDICATION_TIMEOUT,
    }

    def __init__(self, intent_classifier: IntentClassifier, role_manager: RoleManager):
        self.intent_classifier = intent_classifier
        self.role_manager = role_manager

    def evaluate(self, message: Message) -> tuple:
        """
        评估单条消息的触发条件
        返回: (trigger_type, intent_type, score)
        """
        content = message.content
        role = message.role

        # 触发1: 销售发送订单信息
        if self.role_manager.is_sales(role):
            intent, score = self.intent_classifier.classify(content)
            if intent == IntentClassifier.INTENT_BOOKING:
                return (self.TRIGGER_BOOKING, intent, score)

        # 触发2-5: 客户发送咨询 + 超时无响应
        if self.role_manager.is_customer(role):
            # 检查超时条件: 输入快照本身已是 3-7 分钟窗口内的消息,
            # 无需再做时间过滤, 仅依据快照标记判断是否无人响应
            if self._is_timeout(message):
                intent, score = self.intent_classifier.classify(content)
                trigger = self.TIMEOUT_TRIGGER_MAP.get(intent)
                if trigger:
                    return (trigger, intent, score)

        return (self.TRIGGER_NONE, IntentClassifier.INTENT_NONE, 0.0)

    def _is_timeout(self, message: Message) -> bool:
        """判断是否满足超时条件 (基于快照标记, 不做时间计算)

        输入的会话快照已是 3-7 分钟窗口内的消息, 因此超时判定
        仅依据标注: is_last_in_window=True 且 has_response_after=False。
        """
        # JSON 输入已标注: is_last_in_window=True 且 has_response_after=False
        return message.is_last_in_window and not message.has_response_after

    def evaluate_session(self, messages: list) -> tuple:
        """
        评估整个会话窗口，返回第一个触发的结果
        返回: (trigger_type, message, intent_type, score)
        """
        for msg in messages:
            trigger_type, intent, score = self.evaluate(msg)
            if trigger_type != self.TRIGGER_NONE:
                return (trigger_type, msg, intent, score)
        return (self.TRIGGER_NONE, None, IntentClassifier.INTENT_NONE, 0.0)
