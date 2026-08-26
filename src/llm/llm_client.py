# -*- coding: utf-8 -*-
"""
大模型客户端 - OpenAI 兼容接口封装

配置位于 config/llm_config.json:
- enabled: 是否启用大模型兜底 (默认关闭, 关闭时完全走规则引擎)
- api_key 支持 ${ENV_VAR} 形式从环境变量注入

提供同步 chat() 与异步 achat() 两种调用方式。
"""
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from ..utils.logging_config import truncate

logger = logging.getLogger(__name__)

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value):
    """展开配置值中的 ${ENV_VAR} 占位符"""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    return value


class LLMJudgeResult(BaseModel):
    """大模型全量会话判定输出的 Pydantic 约束

    模型输出不符合该结构时统一视为格式违规, 由上层降级规则引擎,
    避免脏数据静默流入业务逻辑。
    """
    trigger: Literal[
        "booking",
        "appointment_timeout",
        "contract_timeout",
        "construction_timeout",
        "medication_timeout",
        "none",
    ]
    reason: str = Field(default="", max_length=200)


class LLMClient:
    """OpenAI 兼容协议的大模型客户端"""

    # 规则引擎意图 -> 触发类型 (与 TriggerEngine 保持一致)
    INTENT_TO_TRIGGER = {
        "appointment": "appointment_timeout",
        "contract": "contract_timeout",
        "construction": "construction_timeout",
        "medication": "medication_timeout",
    }

    def __init__(self, config_path: str = None):
        if config_path is None:
            base_dir = Path(__file__).parent.parent.parent
            config_path = base_dir / "config" / "llm_config.json"
        self.config_path = Path(config_path)
        self._load_config()

    def _load_config(self):
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {}

        self.enabled = bool(config.get("enabled", False))
        self.provider = config.get("provider", "openai_compatible")
        self.base_url = str(config.get("base_url", "")).rstrip("/")
        self.api_key = _expand_env(config.get("api_key", ""))
        self.model = config.get("model", "gpt-4o-mini")
        self.temperature = config.get("temperature", 0.3)
        self.max_tokens = config.get("max_tokens", 512)
        self.timeout_seconds = config.get("timeout_seconds", 30)
        self.max_retries = max(0, int(config.get("max_retries", 2)))
        self.fallback_to_template = bool(config.get("fallback_to_template", True))

        logger.info(
            "LLM配置加载完成: enabled=%s provider=%s model=%s base_url=%s api_key=%s "
            "temperature=%s max_tokens=%s timeout=%ss retries=%s",
            self.enabled, self.provider, self.model, self.base_url,
            "已配置" if self.api_key else "(空)",
            self.temperature, self.max_tokens, self.timeout_seconds, self.max_retries,
        )

    @property
    def available(self) -> bool:
        """配置完整且启用才视为可用"""
        return self.enabled and bool(self.base_url) and bool(self.api_key)

    # ------------------------------------------------------------------
    # 基础对话调用
    # ------------------------------------------------------------------
    def _build_payload(self, messages: List[dict], **overrides) -> dict:
        return {
            "model": overrides.get("model", self.model),
            "messages": messages,
            "temperature": overrides.get("temperature", self.temperature),
            "max_tokens": overrides.get("max_tokens", self.max_tokens),
        }

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_content(resp_json: dict) -> str:
        try:
            return resp_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ValueError(f"LLM 响应格式异常: {resp_json}")

    @staticmethod
    def _format_error(e: Exception) -> str:
        """格式化异常用于日志输出

        httpx 超时类异常的 str() 可能为空, 直接打印会丢失原因;
        统一输出异常类型+消息, HTTP错误额外附状态码与响应体, 保证日志可读。
        """
        import httpx

        msg = str(e)
        detail = f"{type(e).__name__}: {msg}" if msg else type(e).__name__
        if isinstance(e, httpx.HTTPStatusError):
            try:
                body = truncate(e.response.text, 300)
            except Exception:  # noqa: BLE001
                body = "<响应体不可读>"
            detail += f" [状态码={e.response.status_code} 响应体={body}]"
        elif isinstance(e, httpx.TimeoutException):
            detail = f"{type(e).__name__}: 请求超时 {msg}".rstrip() if msg \
                else f"{type(e).__name__}: 请求超时(超过配置的timeout秒数)"
        return detail

    def chat(self, messages: List[dict], **overrides) -> str:
        """同步对话调用"""
        import httpx

        if not self.available:
            raise RuntimeError("LLM 未启用或配置不完整 (enabled/base_url/api_key)")

        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, **overrides)
        logger.info(
            "LLM请求开始(同步): model=%s messages=%d条 首条内容=%s",
            payload["model"], len(messages),
            truncate(messages[-1].get("content", ""), 120),
        )
        logger.debug(
            "LLM请求payload详情(同步): model=%s temperature=%s max_tokens=%s messages=%s",
            payload["model"], payload["temperature"], payload["max_tokens"],
            truncate(json.dumps(payload["messages"], ensure_ascii=False), 3000),
        )
        started = time.perf_counter()
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    resp = client.post(url, headers=self._headers(), json=payload)
                    resp.raise_for_status()
                    content = self._extract_content(resp.json())
                    logger.info(
                        "LLM响应成功(同步): 耗时=%.0fms 响应长度=%d字符",
                        (time.perf_counter() - started) * 1000, len(content),
                    )
                    logger.debug("LLM响应原始内容(同步): %s", truncate(content, 2000))
                    return content
            except Exception as e:  # noqa: BLE001
                last_error = e
                logger.warning("LLM调用失败(同步, 第%d/%d次): %s",
                               attempt + 1, self.max_retries + 1,
                               self._format_error(e))
        logger.error("LLM调用最终失败(同步): 共%d次尝试, 最后错误=%s",
                     self.max_retries + 1, self._format_error(last_error))
        raise RuntimeError(f"LLM 调用最终失败: {self._format_error(last_error)}")

    async def achat(self, messages: List[dict], **overrides) -> str:
        """异步对话调用"""
        import httpx

        if not self.available:
            raise RuntimeError("LLM 未启用或配置不完整 (enabled/base_url/api_key)")

        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, **overrides)
        logger.info(
            "LLM请求开始(异步): model=%s messages=%d条 首条内容=%s",
            payload["model"], len(messages),
            truncate(messages[-1].get("content", ""), 120),
        )
        logger.debug(
            "LLM请求payload详情(异步): model=%s temperature=%s max_tokens=%s messages=%s",
            payload["model"], payload["temperature"], payload["max_tokens"],
            truncate(json.dumps(payload["messages"], ensure_ascii=False), 3000),
        )
        started = time.perf_counter()
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.post(url, headers=self._headers(), json=payload)
                    resp.raise_for_status()
                    content = self._extract_content(resp.json())
                    logger.info(
                        "LLM响应成功(异步): 耗时=%.0fms 响应长度=%d字符",
                        (time.perf_counter() - started) * 1000, len(content),
                    )
                    logger.debug("LLM响应原始内容(异步): %s", truncate(content, 2000))
                    return content
            except Exception as e:  # noqa: BLE001
                last_error = e
                logger.warning("LLM调用失败(异步, 第%d/%d次): %s",
                               attempt + 1, self.max_retries + 1,
                               self._format_error(e))
        logger.error("LLM调用最终失败(异步): 共%d次尝试, 最后错误=%s",
                     self.max_retries + 1, self._format_error(last_error))
        raise RuntimeError(f"LLM 调用最终失败: {self._format_error(last_error)}")

    # ------------------------------------------------------------------
    # 智能体意图判断: 全量会话交由大模型识别五类触发条件
    # ------------------------------------------------------------------
    _JUDGE_PROMPT = (
        "你是企业微信售后服务群的智能客服助手。以下是某客户服务群的完整聊天记录"
        "(消息已处于最近3-7分钟窗口内)。请判断智能体是否应该回复，"
        "属于哪一类触发。\n\n"
        "触发类别 (只能是以下之一或 none):\n"
        "1. booking: 销售发送了包含多个\"字段：值\"的订单信息"
        "(带冒号的一长串, 如上门时间/姓名/电话/地址等字段)\n"
        "2. appointment_timeout: 客户发送预约上门/改期/确认上门时间相关内容, "
        "且该消息之后无人回应\n"
        "3. contract_timeout: 客户发送合同/签约/个人信息填写相关内容, "
        "且该消息之后无人回应\n"
        "4. construction_timeout: 客户发送现场施工/上门作业/入住准备相关内容, "
        "且该消息之后无人回应\n"
        "5. medication_timeout: 客户发送药剂/甲醛/气味/安全担忧相关内容, "
        "且该消息之后无人回应\n\n"
        "判断要求:\n"
        "- \"之后\"一律以每条消息开头方括号内的时间戳为准判断: "
        "时间戳晚于某条消息的消息才是它的后续消息, 与消息在记录中的出现顺序无关\n"
        "- \"无人回应\"指: 时间戳晚于该客户消息的聊天记录中, 没有工作人员的后续消息; "
        "其他客户的后续发言不算回应\n"
        "- 只要工作人员已对该客户的问题做过回应(安排、解答、确认等), "
        "即使客户之后又有追问或补充, 也视为诉求已被响应, 判为 none; "
        "客户自己确认结束(如回复\"好\"\"可以\"\"知道了\"等)同样判为 none\n"
        "- 闲聊/致谢/无关内容, 判为 none\n"
        "- 每条消息发送者括号内为角色标注, 角色标注是判断说话人身份的唯一依据: "
        "标注为客户的说话人就是客户, 标注为师傅/销售/工程部负责人等工作人员的"
        "就是工作人员; 禁止根据消息内容、语气或@关系推测或更改说话人身份\n"
        "- 所有涉及\"客户发送\"的触发条件严格按角色标注判断: "
        "发言者角色标注为客户, 就按客户诉求评估; "
        "最后一条消息由工作人员(角色标注非客户)发出, 判为 none\n\n"
        '只输出JSON，格式: {"trigger": "...", "reason": "简短判断依据"}\n'
        "聊天记录:\n__TRANSCRIPT__"
    )

    async def judge_session(self, transcript: str) -> Optional[dict]:
        """
        全量会话意图判断: 由大模型识别五类触发条件。

        回复文案与@目标仍由规则引擎固定模板生成, 大模型只负责判定。

        Returns:
            命中触发: {"trigger", "reason"}
            判定无需回复: None
        Raises:
            RuntimeError/ValueError: 调用失败或输出无法解析 (由上层决定降级)
        """
        if not self.available:
            raise RuntimeError("LLM 未启用或配置不完整 (enabled/base_url/api_key)")
        msg_count = len(transcript.splitlines())
        logger.info("LLM全量会话判定开始: 消息%d条 对话记录长度=%d字符",
                    msg_count, len(transcript))
        # 模板含 JSON 示例花括号, 不能用 str.format, 改用占位符替换
        prompt = self._JUDGE_PROMPT.replace("__TRANSCRIPT__", transcript)
        logger.debug("LLM判定完整prompt(共%d字符): %s", len(prompt), truncate(prompt, 3000))
        messages = [
            {"role": "user", "content": prompt}
        ]
        started = time.perf_counter()
        content = await self.achat(messages)
        logger.debug("LLM判定模型原始输出: %s", truncate(content, 2000))
        parsed = self._parse_json(content)
        if not parsed:
            logger.warning("LLM全量判定: 输出无法解析为JSON. 原始输出=%s",
                           truncate(content, 200))
            raise ValueError(f"LLM 判定输出无法解析: {truncate(content, 100)}")
        logger.debug("LLM判定JSON解析结果: %s", parsed)
        # Pydantic 约束: 字段类型/取值范围不合规时显式失败, 交由上层降级
        try:
            judgment = LLMJudgeResult.model_validate(parsed)
        except ValidationError as e:
            logger.warning("LLM全量判定: 输出不符合结构约束. 原始输出=%s 校验错误=%s",
                           truncate(content, 200), e.errors(include_url=False))
            raise ValueError(f"LLM 判定输出格式违规: {truncate(content, 100)}")
        elapsed_ms = (time.perf_counter() - started) * 1000
        if judgment.trigger == "none":
            logger.info("LLM全量判定: 无需回复 (trigger=none, 判定耗时=%.0fms) 依据=%s",
                        elapsed_ms, judgment.reason)
            return None
        logger.info("LLM全量判定命中: trigger=%s 判定耗时=%.0fms 依据=%s",
                    judgment.trigger, elapsed_ms, judgment.reason)
        return judgment.model_dump()

    @staticmethod
    def _parse_json(content: str) -> Optional[dict]:
        """尽力从模型输出中解析 JSON (容忍 markdown 代码块)"""
        content = content.strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # 兜底: reason 文本内出现未转义双引号(如 回复"好的")时严格JSON解析必失败,
        # 改用正则逐字段提取; 提取结果仍会经过 Pydantic 校验拦截非法值
        trigger_match = re.search(r'"trigger"\s*:\s*"([^"]*)"', content)
        reason_match = re.search(r'"reason"\s*:\s*"(.*)"\s*\}\s*$',
                                 content, re.DOTALL)
        if trigger_match:
            logger.warning("JSON严格解析失败, 使用正则提取兜底: trigger=%s",
                           trigger_match.group(1))
            return {"trigger": trigger_match.group(1),
                    "reason": reason_match.group(1) if reason_match else ""}
        return None
