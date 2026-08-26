# -*- coding: utf-8 -*-
"""文本工具函数"""
import re


def normalize_text(text: str) -> str:
    """标准化文本: 去除多余空白"""
    return re.sub(r'\s+', ' ', text).strip()


def extract_phone_numbers(text: str) -> list:
    """提取手机号"""
    pattern = r'1[3-9]\d{9}'
    return re.findall(pattern, text)


def extract_chinese_names(text: str) -> list:
    """提取中文姓名 (简化版: 2-4字中文连续)"""
    pattern = r'[\u4e00-\u9fa5]{2,4}'
    return re.findall(pattern, text)


def count_keyword_occurrences(text: str, keyword: str) -> int:
    """统计关键词出现次数"""
    return text.count(keyword)


def has_multiple_colon_pairs(text: str, min_pairs: int = 3) -> bool:
    """检查文本是否包含多个 key:value 对"""
    pattern = r'[\u4e00-\u9fa5A-Za-z]{2,8}[\uff1a:][^\s]+'
    matches = re.findall(pattern, text)
    return len(matches) >= min_pairs
