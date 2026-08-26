# -*- coding: utf-8 -*-
"""触发1处理器: 销售发送订单信息"""
from typing import List
from ..models.message import Message
from ..models.response import ResponseItem
from ..core.response_generator import ResponseGenerator


class BookingHandler:
    """处理销售发送订单信息的触发"""

    def __init__(self, response_generator: ResponseGenerator):
        self.response_generator = response_generator

    def handle(self, message: Message) -> List[ResponseItem]:
        """
        处理订单消息，生成前摇+@师傅响应

        流程:
        1. 解析订单信息 (姓名/电话/地址/上门时间等)
        2. 查找对应师傅信息
        3. 生成两大段前摇文案
        4. @师傅 + "请主动联系客户确认上门时间~"
        """
        return self.response_generator.generate_booking_response(
            message_content=message.content,
            master_name=None,  # 可从订单信息或群成员中获取
        )
