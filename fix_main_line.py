# -*- coding: utf-8 -*-
"""修复 main.py：让 booking 触发不受 LLM 降级覆盖（逐行方式）"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

with open("src/main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if '        if not judgment:' in line and i+1 < len(lines):
        # 下一行应该是注释行
        if '# 大模型判定无需回复' in lines[i+1]:
            print(f"找到目标位置：行{i+1}")
            # 插入三行新代码
            new_lines = [
                '            # booking(销售订单) 直接回复，不做 LLM 降级；仅超时场景支持 LLM 否决\n',
                '            if rule_result.get("trigger_type") == TriggerEngine.TRIGGER_BOOKING:\n',
                '                return result\n',
                '\n',
                # 保留原注释行
            ] + lines[i+1:]
            lines = new_lines[i:i+5] + lines[5:]  # 替换从该位置开始的 5 行
            
            with open("src/main.py", "w", encoding="utf-8") as f:
                f.writelines(lines)
            print("OK - 已添加 booking 保护逻辑")
            sys.exit(0)

print("ERROR - 未找到目标位置")
sys.exit(1)
