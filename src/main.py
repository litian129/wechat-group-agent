# -*- coding: utf-8 -*-
"""
企业微信群聊智能体 - 主入口

使用方式:
  1. 文件输入:  python src/main.py --input input/1787379786.json --output output.json
  2. 标准输入:  cat input.json | python src/main.py --stdin
  3. 编程调用:  from src.main import WeComGroupAgent
  4. API服务:   python src/server.py  (FastAPI 异步任务接口, 见 src/api)

支持的输入格式:
  - 传统格式: {"group_name": ..., "messages": [...]}
  - 导出格式: [{"meta": {...}, "message": [...]}, ...]  (时间戳命名的会话导出文件)
"""
import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# 添加项目根目录到路径 (main.py 在 src/ 下，项目根是上一级)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.message_parser import MessageParser
from src.core.export_parser import ExportParser
from src.core.role_manager import RoleManager
from src.core.intent_classifier import IntentClassifier
from src.core.trigger_engine import TriggerEngine
from src.core.response_generator import ResponseGenerator
from src.handlers.booking_handler import BookingHandler
from src.handlers.timeout_handler import TimeoutHandler
from src.llm.llm_client import LLMClient
from src.models.message import ChatSession, Message
from src.models.response import AgentResponse, ResponseItem
from src.utils.logging_config import setup_logging, truncate

logger = logging.getLogger(__name__)


class WeComGroupAgent:
    """企业微信群聊智能体主控"""

    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = PROJECT_ROOT / "config"

        config_dir = Path(config_dir)
        self.agent_config_path = config_dir / "agent_config.json"
        self.master_info_path = config_dir / "master_info.json"
        self.role_mapping_path = config_dir / "role_mapping.json"
        self.llm_config_path = config_dir / "llm_config.json"

        # 初始化核心组件
        self.role_manager = RoleManager(str(self.role_mapping_path))
        self.intent_classifier = IntentClassifier(str(self.agent_config_path))
        self.trigger_engine = TriggerEngine(self.intent_classifier, self.role_manager)
        self.response_generator = ResponseGenerator(
            str(self.agent_config_path), str(self.master_info_path)
        )
        self.export_parser = ExportParser(self.role_manager, str(self.agent_config_path))

        # 大模型客户端 (配置未启用时所有调用自动跳过)
        self.llm_client = LLMClient(str(self.llm_config_path))

        # 初始化处理器
        self.booking_handler = BookingHandler(self.response_generator)
        self.timeout_handler = TimeoutHandler(self.response_generator)

    # ------------------------------------------------------------------
    # 同步入口
    # ------------------------------------------------------------------
    def process(self, input_data: dict) -> dict:
        """
        处理群聊会话窗口 (传统格式)，返回响应

        Args:
            input_data: 包含 group_name 和 messages 的字典

        Returns:
            包含 group_name, triggered, trigger_type, responses 的字典
        """
        session = MessageParser.parse_dict(input_data)
        return self._process_session(session)

    def process_file(self, input_path: str) -> dict:
        """处理JSON文件 (传统格式)"""
        session = MessageParser.parse_file(input_path)
        return self._process_session(session)

    def process_data(self, input_data, source_file: str = None) -> dict:
        """自动识别格式并处理 (传统格式 / 导出格式)"""
        if ExportParser.is_export_format(input_data):
            sessions = self.export_parser.parse(input_data)
            logger.info("输入识别为导出格式: 共%d个会话 source=%s", len(sessions), source_file)
            return self._process_export_sessions(sessions, source_file)
        logger.info("输入识别为传统格式 source=%s", source_file)
        return self.process(input_data)

    def process_auto(self, input_path: str) -> dict:
        """处理JSON文件, 自动识别格式"""
        path = self._resolve_input_path(input_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return self.process_data(data, source_file=str(path))

    # ------------------------------------------------------------------
    # 异步入口 (供 FastAPI 服务调用)
    # ------------------------------------------------------------------
    async def aprocess_data(self, input_data, source_file: str = None) -> dict:
        """异步处理, 自动识别格式; 导出格式由大模型全量判定意图"""
        if ExportParser.is_export_format(input_data):
            sessions = await asyncio.to_thread(self.export_parser.parse, input_data)
            results = []
            for session in sessions:
                rule_result = await asyncio.to_thread(self._process_session, session)
                result = await self._llm_judge(session, rule_result)
                results.append(result)
            triggered = sum(1 for r in results if r.get("triggered"))
            return {
                "source_file": source_file,
                "summary": {"total": len(results), "triggered": triggered},
                "sessions": results,
            }
        return await asyncio.to_thread(self.process, input_data)

    async def aprocess_auto(self, input_path: str) -> dict:
        """异步处理JSON文件, 自动识别格式"""
        path = self._resolve_input_path(input_path)
        started = time.perf_counter()
        logger.info("开始异步处理文件: %s", path)
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        data = json.loads(text)
        result = await self.aprocess_data(data, source_file=str(path))
        logger.info("文件处理完成: %s 耗时=%.0fms", path, (time.perf_counter() - started) * 1000)
        return result

    # ------------------------------------------------------------------
    # 内部处理逻辑
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_input_path(input_path: str) -> Path:
        path = Path(input_path)
        if path.exists():
            return path
        # 不存在时依次尝试: 项目根相对路径 -> input 目录下的同名文件
        # (监听器提交的路径可能来自其他环境, 取文件名可跨环境/Docker定位)
        candidates = [PROJECT_ROOT / input_path, PROJECT_ROOT / "input" / path.name]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return path

    def _process_export_sessions(self, sessions: list, source_file: str = None) -> dict:
        """处理导出格式的多个会话"""
        results = [self._process_session(session) for session in sessions]
        triggered = sum(1 for r in results if r.get("triggered"))
        logger.info("导出格式处理完成: 共%d个会话, 触发%d个 source=%s",
                    len(results), triggered, source_file)
        return {
            "source_file": source_file,
            "summary": {"total": len(results), "triggered": triggered},
            "sessions": results,
        }

    def _process_session(self, session: ChatSession) -> dict:
        """处理会话"""
        # 遍历消息，评估触发条件
        trigger_type, message, intent, score = self.trigger_engine.evaluate_session(
            session.messages
        )

        # 触发评估日志 (排查规则引擎决策依据)
        if trigger_type == TriggerEngine.TRIGGER_NONE:
            logger.debug("会话[%s] 未触发: 共%d条消息",
                         session.group_name, len(session.messages))
        else:
            logger.info("会话[%s] 触发: type=%s intent=%s score=%.1f 触发消息=%s",
                        session.group_name, trigger_type, intent, score,
                        truncate(message.content, 80) if message else "")

        # 构建响应
        response = AgentResponse(group_name=session.group_name)

        if trigger_type == TriggerEngine.TRIGGER_NONE:
            response.triggered = False
            response.trigger_type = None
            response.responses = []
        elif trigger_type == TriggerEngine.TRIGGER_BOOKING:
            response.triggered = True
            response.trigger_type = "booking"
            response.responses = self.booking_handler.handle(message)
        else:
            # 超时触发 (触发2-5)
            response.triggered = True
            response.trigger_type = trigger_type
            timeout_response = self.timeout_handler.handle(trigger_type, message)
            response.responses = [timeout_response]

        logger.debug("会话[%s] 生成响应: triggered=%s responses=%d条",
                     session.group_name, response.triggered, len(response.responses))
        return response.to_dict()

    async def _llm_judge(self, session: ChatSession, rule_result: dict) -> dict:
        """大模型全量会话意图判定 (主导)

        会话全部消息交给大模型识别五类触发条件, 回复文案仍由
        固定模板生成 (booking=两段前摇+@师傅, 超时=安抚模板);
        大模型未启用/调用失败时降级为规则引擎判定结果。
        """
        if not self.llm_client.available:
            logger.debug("会话[%s] LLM未启用, 使用规则引擎判定", session.group_name)
            return rule_result
        transcript = self._build_transcript(session)
        if not transcript:
            logger.debug("会话[%s] 无消息记录, 不回复", session.group_name)
            return rule_result
        logger.info("会话[%s] 进入LLM判定路径: 规则引擎预判=%s 消息%d条",
                    session.group_name,
                    rule_result.get("trigger_type") or "未触发",
                    len(session.messages))
        logger.debug("会话[%s] 提交LLM的全量对话记录: %s",
                     session.group_name, truncate(transcript, 2000))
        try:
            judgment = await self.llm_client.judge_session(transcript)
        except Exception as e:  # noqa: BLE001
            logger.warning("会话[%s] LLM判定失败, 降级规则引擎结果: %s",
                           session.group_name, e)
            return rule_result

        result = dict(rule_result)
        if not judgment:
            # 大模型判定无需回复 (覆盖规则引擎结果, 以LLM为准)
            if rule_result.get("triggered"):
                logger.info("会话[%s] 规则引擎曾触发(%s), 但LLM判定无需回复, 不回复",
                            session.group_name, rule_result.get("trigger_type"))
            else:
                logger.info("会话[%s] 规则引擎与LLM判定一致: 无需回复",
                            session.group_name)
            result["triggered"] = False
            result["trigger_type"] = None
            result["responses"] = []
            result["llm_judge"] = {"trigger": "none"}
            return result

        trigger = judgment["trigger"]
        if rule_result.get("trigger_type") != trigger:
            logger.info("会话[%s] LLM判定(%s)与规则引擎预判(%s)不一致, 以LLM为准",
                        session.group_name, trigger,
                        rule_result.get("trigger_type") or "未触发")
        if trigger == TriggerEngine.TRIGGER_BOOKING:
            responses = [item.to_dict() for item in
                         self.response_generator.generate_booking_response("")]
        else:
            responses = [self.response_generator.generate_timeout_response(trigger).to_dict()]
        for item in responses:
            item["generated_by"] = "llm"
        logger.info("会话[%s] 应用LLM判定响应: trigger=%s 响应%d条 at=%s reply=%s",
                    session.group_name, trigger, len(responses),
                    responses[0].get("at_target"),
                    truncate(responses[0].get("content", ""), 80))
        logger.debug("会话[%s] LLM判定完整结果: %s 完整响应: %s",
                     session.group_name, judgment, responses)
        result["triggered"] = True
        result["trigger_type"] = trigger
        result["responses"] = responses
        result["llm_judge"] = judgment
        return result

    @staticmethod
    def _build_transcript(session: ChatSession) -> str:
        """构建供大模型分析的对话记录 (全量消息)"""
        lines = []
        for msg in session.messages:
            lines.append(f"[{msg.timestamp}] {msg.userid}({msg.role}): {msg.content}")
        return "\n".join(lines)

    def debug_classify(self, content: str) -> dict:
        """调试: 查看意图分类详情"""
        intent, score = self.intent_classifier.classify(content)
        all_scores = self.intent_classifier.get_all_scores(content)
        return {
            "content": content,
            "predicted_intent": intent,
            "score": score,
            "all_scores": all_scores,
        }


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="企业微信群聊智能体")
    parser.add_argument("--input", "-i", type=str, help="输入JSON文件路径")
    parser.add_argument("--output", "-o", type=str, help="输出JSON文件路径")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取JSON")
    parser.add_argument("--debug", action="store_true", help="输出调试信息")
    parser.add_argument("--log-level", type=str, default=None,
                        help="日志级别 (DEBUG/INFO/WARNING, 默认环境变量或INFO)")
    args = parser.parse_args()

    setup_logging(level=args.log_level)

    agent = WeComGroupAgent()

    # 读取输入并处理 (自动识别传统格式/导出格式)
    if args.stdin:
        input_str = sys.stdin.read()
        input_data = json.loads(input_str)
        result = agent.process_data(input_data)
    elif args.input:
        result = agent.process_auto(args.input)
    else:
        parser.print_help()
        sys.exit(1)

    # 输出
    output_str = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output_str, encoding="utf-8")
        print(f"结果已写入: {args.output}")
    else:
        print(output_str)

    if args.debug and result.get("triggered"):
        print("\n--- 调试信息 ---")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
