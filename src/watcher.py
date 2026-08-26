# -*- coding: utf-8 -*-
"""
输入文件夹监听器

轮询 input 目录, 发现新增/更新的 .json 文件 (时间戳命名) 且文件大小稳定后,
调用 POST {api_url}/api/tasks 接口开始智能体任务。

已处理记录持久化到 state 文件, 服务重启后不会重复提交; 文件内容更新
(大小变化) 后会重新提交。
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class InputWatcher:
    """监听 input 文件夹变化并触发开始任务接口"""

    def __init__(self, input_dir, api_url: str, poll_interval: float = 2.0,
                 state_path=None):
        self.input_dir = Path(input_dir)
        self.api_url = str(api_url).rstrip("/")
        self.poll_interval = max(0.5, float(poll_interval))
        self.state_path = Path(state_path) if state_path else None
        self._pending: Dict[str, int] = {}          # 文件名 -> 上次扫描的大小
        self._processed: Dict[str, int] = self._load_state()

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------
    def _load_state(self) -> Dict[str, int]:
        if self.state_path and self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                logger.warning("监听状态文件损坏, 将重新处理: %s", self.state_path)
        return {}

    def _save_state(self):
        if not self.state_path:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(self._processed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("保存监听状态失败: %s", e)

    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------
    def scan(self) -> List[Tuple[Path, int]]:
        """返回本轮可提交的文件 [(路径, 大小)]

        文件需在连续两次扫描中大小一致才视为写入完成, 避免读到半截文件。
        """
        if not self.input_dir.exists():
            return []

        ready: List[Tuple[Path, int]] = []
        current: Dict[str, int] = {}
        for path in sorted(self.input_dir.glob("*.json")):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            name = path.name
            if self._processed.get(name) == size:
                continue  # 已处理且内容未变化
            current[name] = size
            if self._pending.get(name) == size:
                ready.append((path, size))   # 与上次扫描大小一致 -> 写入完成
                logger.debug("文件写入稳定, 准备提交: %s (%d字节)", name, size)
            else:
                self._pending[name] = size   # 新发现或仍在变化, 下一轮再确认
                logger.debug("发现新增/变化文件, 等待写入稳定: %s (%d字节)", name, size)

        # 清理已不存在的文件的 pending 记录
        self._pending = {k: v for k, v in self._pending.items() if k in current}
        return ready

    # ------------------------------------------------------------------
    # 提交任务
    # ------------------------------------------------------------------
    async def submit(self, path: Path) -> bool:
        """调用开始任务接口, 成功返回 True"""
        import httpx

        url = f"{self.api_url}/api/tasks"
        payload = {"input_file": str(path)}
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(url, json=payload)
                if resp.status_code in (200, 201, 202):
                    body = resp.json()
                    logger.info("发现新文件 %s -> 已开始任务 task_id=%s",
                                path.name, body.get("task_id"))
                    return True
                logger.warning("开始任务接口返回异常 (%s): %s",
                               resp.status_code, resp.text[:200])
            except Exception as e:  # noqa: BLE001
                logger.warning("调用开始任务接口失败 (第%d次): %s", attempt + 1, e)
            await asyncio.sleep(1)
        return False

    async def run_once(self) -> List[str]:
        """执行一轮扫描与提交, 返回已提交的文件名列表"""
        submitted = []
        ready = self.scan()
        if ready:
            logger.info("本轮扫描发现%d个待处理文件: %s",
                        len(ready), [p.name for p, _ in ready])
        for path, size in ready:
            if await self.submit(path):
                self._processed[path.name] = size
                self._pending.pop(path.name, None)
                self._save_state()
                submitted.append(path.name)
                logger.info("文件已提交并记录状态: %s (%d字节)", path.name, size)
            else:
                # 提交失败: 清除 pending 记录, 下一轮重新检测并重试
                self._pending.pop(path.name, None)
                logger.warning("文件提交失败, 下一轮重试: %s", path.name)
        return submitted

    async def run_forever(self):
        """持续监听, 直到被取消"""
        logger.info("开始监听输入文件夹: %s (间隔 %.1fs)",
                    self.input_dir, self.poll_interval)
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning("监听循环异常: %s", e)
            await asyncio.sleep(self.poll_interval)
