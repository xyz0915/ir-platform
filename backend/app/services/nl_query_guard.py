"""NL 检索护栏 — 白名单字段映射 + 参数化 + 拒 DDL/写操作（§C / §8.2）。

职责：
1. compile(nl_text, user): 调用 AgentLLM 将自然语言转换为结构化查询意图 JSON。
2. validate(intent): 校验意图——拒绝非白名单字段 / DDL / 写操作 / 超限行数。
3. 绝不拼原始 SQL：字段名取自白名单常量，值经后续 NormalizedLog.search 参数化。
"""

import json
import logging
import re
from typing import Any, Optional

from app.config import settings
from app.services.agent_llm import AgentLLM

logger = logging.getLogger(__name__)


# normalized_logs 真实列名白名单（key=逻辑字段, value=DB 列名）
WHITELIST_FIELDS: dict[str, str] = {
    "host_id": "host_id",
    "hostname": "hostname",
    "log_source": "log_source",
    "event_id": "event_id",
    "event_type": "event_type",
    "event_label": "event_label",
    "mitre_attack": "mitre_attack",
    "severity": "severity",
    "timestamp": "timestamp",
    "source_ip": "source_ip",
    "source_hostname": "source_hostname",
    "target_ip": "target_ip",
    "target_hostname": "target_hostname",
    "user_name": "user_name",
    "user_domain": "user_domain",
    "logon_session": "logon_session",
    "process_name": "process_name",
    "parent_process_name": "parent_process_name",
    "command_line": "command_line",
    "object_name": "object_name",
    "tags": "tags",
    "description": "description",
}

# 允许的操作符
ALLOWED_OPS = {"=", "!=", "contains", "in", ">=", "<=", ">", "<", "between"}

# 危险关键字（用于拒绝 DDL / 写操作）
_DDL_WRITE_PATTERN = re.compile(
    r"\b(drop|delete|update|insert|alter|truncate|create|replace|exec|execute|grant|revoke)\b"
    r"|;|--|/\*|\*/|xp_",
    re.IGNORECASE,
)

# 单次查询最大行数（硬性安全上限）
MAX_PAGE_SIZE = 500

# 编译用 system prompt
_COMPILE_SYSTEM_PROMPT = """你是一名安全日志检索助手。请将用户的中文自然语言检索需求，
转换为严格的 JSON 查询意图，不要输出任何解释文字，仅输出 JSON。

JSON 结构：
{
  "filters": [
    {"field": "白名单字段", "op": "操作符", "value": "值"}
  ],
  "time_range": {"from": "ISO时间(可空)", "to": "ISO时间(可空)"},
  "sort": "timestamp DESC",
  "page_size": 50,
  "summary_requested": true
}

规则：
- field 只能从以下白名单选择：host_id, hostname, log_source, event_type, event_label,
  mitre_attack, severity, timestamp, source_ip, target_ip, source_hostname, target_hostname,
  user_name, user_domain, logon_session, process_name, parent_process_name, command_line,
  object_name, tags, description。
- op 只能是：=, !=, contains, in, >=, <=, >, <, between。
- page_size 不得超过 500。
- 若用户只是泛泛提问（如"最近有什么异常"），filters 可为空数组，summary_requested 为 true。
- 不要输出任何 SQL、不要包含写操作。"""


class NlQueryGuard:
    """NL 检索护栏：编译 + 校验。"""

    def __init__(self, llm: Optional[AgentLLM] = None) -> None:
        self._llm = llm or AgentLLM()

    async def compile(self, nl_text: str, user: Optional[dict] = None) -> dict:
        """将自然语言编译为结构化查询意图 JSON。

        调用 AgentLLM；若 LLM 不可用（降级），则回退为对 description 的安全关键字检索。

        Returns:
            意图 dict：{"filters":[...], "time_range":{...}, "sort":str,
                       "page_size":int, "summary_requested":bool, "_llm_failed":bool}
        """
        nl_text = (nl_text or "").strip()
        default_intent: dict[str, Any] = {
            "filters": [],
            "time_range": {},
            "sort": "timestamp DESC",
            "page_size": 50,
            "summary_requested": True,
            "_llm_failed": False,
        }
        if not nl_text:
            return default_intent

        user_prompt = f"用户检索需求：{nl_text}\n\n请输出 JSON 查询意图。"
        try:
            resp = await self._llm.call(user_prompt, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning("NlQueryGuard.compile: LLM 调用异常，回退关键字检索: %s", exc)
            return self._keyword_fallback(nl_text, default_intent)

        if resp.get("degraded"):
            logger.warning("NlQueryGuard.compile: LLM 降级，回退关键字检索")
            return self._keyword_fallback(nl_text, default_intent)

        content = (resp.get("content") or "").strip()
        parsed = self._extract_json(content)
        if not parsed:
            return self._keyword_fallback(nl_text, default_intent)

        return {
            "filters": parsed.get("filters", []) or [],
            "time_range": parsed.get("time_range", {}) or {},
            "sort": parsed.get("sort", "timestamp DESC") or "timestamp DESC",
            "page_size": int(parsed.get("page_size", 50) or 50),
            "summary_requested": bool(parsed.get("summary_requested", True)),
            "_llm_failed": False,
        }

    @staticmethod
    def _keyword_fallback(nl_text: str, base: dict) -> dict:
        """LLM 不可用时的安全回退：把原文当作 description 的 contains 过滤。"""
        base = dict(base)
        base["filters"] = [{"field": "description", "op": "contains", "value": nl_text}]
        base["_llm_failed"] = True
        return base

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """从 LLM 文本中稳健提取 JSON（尝试整体 / ```json 块 / 首个花括号）。"""
        if not text:
            return None
        # 1. 整体解析
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
        # 2. ```json 块
        if "```json" in text:
            s = text.find("```json") + 7
            e = text.find("```", s)
            if e > s:
                try:
                    obj = json.loads(text[s:e].strip())
                    if isinstance(obj, dict):
                        return obj
                except (json.JSONDecodeError, ValueError):
                    pass
        # 3. 首个花括号区间
        b = text.find("{")
        e = text.rfind("}")
        if b >= 0 and e > b:
            try:
                obj = json.loads(text[b:e + 1])
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    def validate(self, intent: dict, nl_text: str = "") -> tuple[bool, str]:
        """校验查询意图安全性。

        Returns:
            (ok, error_message)。ok=False 时 error_message 描述拒绝原因。
        """
        # 1. 拒绝 DDL / 写操作（直接检测原文危险关键字）
        if nl_text and _DDL_WRITE_PATTERN.search(nl_text):
            return False, "查询包含 DDL/写操作关键字，已被护栏拒绝"

        # 2. 校验字段白名单
        filters = intent.get("filters", []) or []
        if not isinstance(filters, list):
            return False, "filters 必须为数组"
        for f in filters:
            if not isinstance(f, dict):
                return False, "filter 元素必须为对象"
            field = f.get("field")
            if field not in WHITELIST_FIELDS:
                return False, f"字段 {field!r} 不在白名单，查询被拒绝"
            op = f.get("op")
            if op not in ALLOWED_OPS:
                return False, f"操作符 {op!r} 不被允许"
            if "value" not in f:
                return False, f"filter {field!r} 缺少 value"

        # 3. 校验行数上限
        page_size = int(intent.get("page_size", 50) or 50)
        if page_size > MAX_PAGE_SIZE:
            return False, f"page_size 超过上限 {MAX_PAGE_SIZE}"

        return True, ""
