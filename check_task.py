# -*- coding: utf-8 -*-
"""临时脚本: 查询指定任务结果"""
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
task_id = sys.argv[1]
try:
    with urllib.request.urlopen(
            f"http://127.0.0.1:8000/api/tasks/{task_id}/result",
            timeout=10) as resp:
        data = json.loads(resp.read())["result"]
except urllib.error.HTTPError as e:
    print("尚未完成 HTTP", e.code)
    sys.exit(0)

print("summary:", data["summary"])
for s in data["sessions"]:
    lj = s.get("llm_judge") or {}
    reason = str(lj.get("reason", ""))[:90]
    print(f"[{s['group_name']}] triggered={s['triggered']} "
          f"trigger={lj.get('trigger')} 依据={reason}")
