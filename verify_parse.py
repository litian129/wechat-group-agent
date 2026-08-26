# -*- coding: utf-8 -*-
"""临时脚本: 验证 _parse_json 对未转义双引号输出的兜底解析"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
from src.llm.llm_client import LLMClient, LLMJudgeResult

# 用例1: 真实失败样本 reason 内含未转义双引号(复现 18:35:38 日志)
bad = ("```json\n"
       '{"trigger": "none", "reason": "最后一条消息是客户伊辰回复"好的"，'
       '属于客户确认结束的回复。整个预约上门流程已完成。"}\n'
       "```")
r = LLMClient._parse_json(bad)
print("用例1 解析结果:", r)
assert r is not None and r["trigger"] == "none", r
LLMJudgeResult.model_validate(r)

# 用例2: 正常 JSON 不受影响
good = '{"trigger": "booking", "reason": "销售发送订单信息"}'
r2 = LLMClient._parse_json(good)
assert r2 == {"trigger": "booking", "reason": "销售发送订单信息"}, r2
print("用例2 正常JSON:", r2)

# 用例3: 完全非 JSON 仍返回 None
r3 = LLMClient._parse_json("我无法判断")
assert r3 is None, r3
print("用例3 非JSON返回None: OK")

print("全部通过")
