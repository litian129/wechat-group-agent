# -*- coding: utf-8 -*-
"""意图分类器 - 关键词规则引擎 + 加权评分"""
import json
import re
from pathlib import Path
from typing import Tuple, Optional


class IntentClassifier:
    """基于关键词加权评分的意图分类器"""

    # 意图类型枚举
    INTENT_BOOKING = "booking"
    INTENT_APPOINTMENT = "appointment"
    INTENT_CONTRACT = "contract"
    INTENT_CONSTRUCTION = "construction"
    INTENT_MEDICATION = "medication"
    INTENT_NONE = "none"

    def __init__(self, config_path: str = None):
        if config_path is None:
            base_dir = Path(__file__).parent.parent.parent
            config_path = base_dir / "config" / "agent_config.json"
        self.config_path = Path(config_path)
        self._load_config()

    def _load_config(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        self.intent_keywords = self.config.get("intent_keywords", {})
        self.booking_pattern = self.config.get("booking_pattern", {})
        self.intent_threshold = self.config.get("intent_threshold", 3)

    def classify(self, content: str) -> Tuple[str, float]:
        """
        分类消息意图
        返回: (intent_type, score)
        """
        if not content or not content.strip():
            return (self.INTENT_NONE, 0.0)

        # 1. 检查是否为订单信息 (触发1)
        if self._is_booking_message(content):
            return (self.INTENT_BOOKING, 10.0)

        # 2. 客户消息意图分类 (触发2-5)
        scores = {}
        for intent_type, keywords in self.intent_keywords.items():
            score = self._calculate_score(content, keywords)
            scores[intent_type] = score

        # 取最高分
        best_intent = max(scores, key=scores.get) if scores else self.INTENT_NONE
        best_score = scores.get(best_intent, 0.0)

        if best_score >= self.intent_threshold:
            return (best_intent, best_score)
        return (self.INTENT_NONE, best_score)

    def _is_booking_message(self, content: str) -> bool:
        """检查是否为订单信息 (包含多个 key:value 对)"""
        min_pairs = self.booking_pattern.get("min_colon_pairs", 3)
        key_pattern_str = self.booking_pattern.get("key_pattern", r"[\u4e00-\u9fa5]{2,8}[\uff1a:]")

        # 查找所有 key：value 模式
        full_pattern = key_pattern_str + r"[^\s]+"
        matches = re.findall(full_pattern, content)

        # 检查已知字段匹配
        known_fields = self.booking_pattern.get("known_fields", [])
        known_matches = sum(1 for field in known_fields if field in content)

        return len(matches) >= min_pairs or known_matches >= 3

    def _calculate_score(self, content: str, keywords: dict) -> float:
        """计算某意图类别的得分"""
        score = 0.0
        for keyword, weight in keywords.items():
            count = content.count(keyword)
            score += count * weight
        return score

    def get_all_scores(self, content: str) -> dict:
        """获取所有意图类别的得分（用于调试）"""
        scores = {}
        for intent_type, keywords in self.intent_keywords.items():
            scores[intent_type] = self._calculate_score(content, keywords)
        return scores
