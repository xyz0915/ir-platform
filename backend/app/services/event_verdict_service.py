"""AI 事件研判打标服务（生产者）— T-V1.

职责：批量对 ``security_events`` 调用大模型研判，将结果写回 ``ai_verdict``
JSON 列，使下游语义归并器（``IncidentCorrelator._fetch_suspicious_events``）
有可读的 ``label='suspicious'`` 数据源。

关键契约（成败点）：写回 JSON 键名 ``label / confidence / reason / attack_type``
与 ``incident_correlator.py`` 读取键**逐字符一致**；``label`` 取值范围
``{suspicious, false_positive, benign, unknown}``。

设计要点：
- LLM 不可用 / 熔断 / 解析失败 → 写 ``{label:"unknown", ...}``，整批仍 2xx，绝不 500。
- 阈值：``confidence < confidence_threshold`` 时即便 LLM 给 ``suspicious`` 也降级为 ``benign``。
- 幂等：``force=False`` 跳过已研判（ai_verdict 非 ``{}``）事件；``force=True`` 覆盖。
- 可选写 ``ai_analysis`` 列：用 try/except 包裹，列缺失不阻断 ai_verdict 写回。
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.database import get_connection
from app.services.agent_llm import AgentLLM
from app.services.data_masking import apply as mask_apply

logger = logging.getLogger(__name__)


def _safe_json_loads(value: Any) -> Any:
    """安全 JSON 解析：None / 已为 dict|list 直接返回；字符串尝试解析，失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


class EventVerdictService:
    """security_events 研判生产者服务."""

    MAX_BATCH = 200
    DEFAULT_THRESHOLD = 0.6
    ALLOWED_LABELS = {"suspicious", "false_positive", "benign", "unknown"}

    def __init__(self, llm: Optional[AgentLLM] = None) -> None:
        """初始化（可注入 llm，默认运行时实例化 AgentLLM）."""
        self._llm = llm or AgentLLM()

    # ─────────────────────────────────────────────
    # 统一入口
    # ─────────────────────────────────────────────
    async def analyze_events(
        self,
        event_ids: list,
        user: Optional[dict] = None,
        force: bool = False,
        confidence_threshold: float = DEFAULT_THRESHOLD,
    ) -> dict:
        """批量研判事件并写回 ai_verdict.

        Args:
            event_ids: 事件 ID 列表（security_events.id，TEXT 主键）。
            user: 当前用户字典（来自 get_current_user），用于 LLM 审计。
            force: 是否覆盖已研判事件（默认 False 跳过）。
            confidence_threshold: 置信度阈值，低于此值的 suspicious 降级为 benign。

        Returns:
            ``{processed, skipped, degraded, failed, limit, details}``，
            details 为逐条状态列表 ``{event_id, status, label?, reason?, error?}``。
            整批保证 2xx（单条异常计入 failed，不影响其它条）。
        """
        threshold = float(confidence_threshold)
        details: list[dict] = []
        counts = {"processed": 0, "skipped": 0, "degraded": 0, "failed": 0}

        for event_id in event_ids:
            try:
                detail = await self._process_one(event_id, user, force, threshold)
            except Exception as exc:  # noqa: BLE001  — 兜底，绝不让单条异常逃逸
                logger.exception("EventVerdictService 未捕获异常 event=%s: %s", event_id, exc)
                detail = {"event_id": str(event_id), "status": "failed", "error": str(exc)}
            status = detail.get("status")
            if status in counts:
                counts[status] += 1
            details.append(detail)

        return {
            "processed": counts["processed"],
            "skipped": counts["skipped"],
            "degraded": counts["degraded"],
            "failed": counts["failed"],
            "limit": self.MAX_BATCH,
            "details": details,
        }

    # ─────────────────────────────────────────────
    # 逐条处理
    # ─────────────────────────────────────────────
    async def _process_one(
        self,
        event_id: Any,
        user: Optional[dict],
        force: bool,
        threshold: float,
    ) -> dict:
        eid = str(event_id)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id, event_type, severity, host_id, evidence, ai_verdict "
                "FROM security_events WHERE id = ?",
                (eid,),
            ).fetchone()

        if row is None:
            return {"event_id": eid, "status": "failed", "error": "event_not_found"}

        # sqlite3.Row 无 .get() 方法，转为 dict 以便下游安全访问字段
        row = dict(row)
        current = _safe_json_loads(row["ai_verdict"]) or {}
        # 幂等保护：已研判（ai_verdict 非 {}）且非 force → 跳过
        if not force and current:
            return {"event_id": eid, "status": "skipped"}

        evidence = _safe_json_loads(row["evidence"]) or {}
        try:
            masked = mask_apply(evidence)
            prompt = self._build_prompt(row, masked)
            resp = await self._llm.call(prompt, user=user)

            if not isinstance(resp, dict):
                resp = {}
            content = resp.get("content") or ""

            if resp.get("degraded") or not content:
                # LLM 降级 / 无内容 → 写 unknown，整批不 500
                verdict = {
                    "label": "unknown",
                    "confidence": 0.0,
                    "reason": f"AI降级：{resp.get('error') or '模型无返回'}",
                    "attack_type": "",
                }
                status = "degraded"
                ai_analysis = ""
            else:
                parsed = self._parse_llm(content)
                if parsed is None:
                    # 解析失败 → 同样兜底为 unknown
                    verdict = {
                        "label": "unknown",
                        "confidence": 0.0,
                        "reason": "AI降级：模型返回无法解析",
                        "attack_type": "",
                    }
                    status = "degraded"
                    ai_analysis = content
                else:
                    verdict = self._normalize(parsed, threshold)
                    status = "processed"
                    ai_analysis = content

            self._write_back(eid, verdict, ai_analysis)
            detail: dict = {"event_id": eid, "status": status, "label": verdict["label"]}
            if verdict.get("reason"):
                detail["reason"] = verdict["reason"]
            return detail
        except Exception as exc:  # noqa: BLE001
            logger.warning("EventVerdictService 处理事件 %s 失败: %s", eid, exc)
            return {"event_id": eid, "status": "failed", "error": str(exc)}

    # ─────────────────────────────────────────────
    # 私有：prompt 构造
    # ─────────────────────────────────────────────
    @staticmethod
    def _build_prompt(row: dict, masked_evidence: dict) -> str:
        """构造脱敏后的研判 prompt。"""
        ev_json = json.dumps(masked_evidence, ensure_ascii=False, default=str)
        return (
            "你是一名资深的网络安全事件研判分析师。请分析以下安全事件，"
            "判断其性质并给出研判结论。\n\n"
            "事件信息：\n"
            f"- 事件ID: {row.get('id')}\n"
            f"- 事件类型: {row.get('event_type')}\n"
            f"- 严重度: {row.get('severity')}\n"
            f"- 主机ID: {row.get('host_id')}\n"
            f"- 证据(已脱敏): {ev_json}\n\n"
            "请仅返回一个 JSON 对象，不要包含 markdown 代码块或任何解释性文字，格式如下：\n"
            "{\n"
            '  "label": "suspicious | false_positive | benign | unknown",\n'
            '  "confidence": 0.0,        // 0.0~1.0 之间的浮点数\n'
            '  "reason": "研判理由（中文，简明扼要）",\n'
            '  "attack_type": "攻击类型（如 横向移动/凭据窃取/C2外连 等，无则空字符串）"\n'
            "}\n"
            "label 取值说明：\n"
            "  suspicious = 疑似真实攻击，需人工复核；\n"
            "  false_positive = 误报或正常业务行为；\n"
            "  benign = 良性/低风险事件；\n"
            "  unknown = 信息不足无法确定。\n"
        )

    # ─────────────────────────────────────────────
    # 私有：LLM 输出解析（容忍 ```json 包裹 / 噪声）
    # ─────────────────────────────────────────────
    @staticmethod
    def _parse_llm(content: str) -> Optional[dict]:
        """从 LLM 文本中稳健提取 JSON 对象。

        容忍 ```json ... ``` 包裹与前后噪声；返回 dict 或 None。
        """
        if not content:
            return None
        s = content.strip()
        # 去掉 ```json ... ``` 代码块包裹
        if s.startswith("```"):
            s = s.strip("`")
            s = s[s.find("{") :] if "{" in s else s
        start = s.find("{")
        end = s.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            obj = json.loads(s[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    # ─────────────────────────────────────────────
    # 私有：归一化校验（4 键强制 + label 枚举 + confidence 钳制 + 阈值降级）
    # ─────────────────────────────────────────────
    def _normalize(self, parsed: Any, threshold: float) -> dict:
        """强制校验研判结果。

        - label 不在允许集合 → 落入 unknown
        - confidence 非浮点/越界 → 钳制到 [0, 1]
        - confidence < threshold 且 label=='suspicious' → 降级为 benign
        """
        if not isinstance(parsed, dict):
            parsed = {}

        label = parsed.get("label")
        if label not in self.ALLOWED_LABELS:
            label = "unknown"

        conf = parsed.get("confidence", 0.0)
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0.0:
            conf = 0.0
        elif conf > 1.0:
            conf = 1.0

        # 阈值降级：低置信度的 suspicious 视为 benign，避免污染 suspicious 统计
        if label == "suspicious" and conf < threshold:
            label = "benign"

        return {
            "label": label,
            "confidence": round(conf, 4),
            "reason": str(parsed.get("reason") or ""),
            "attack_type": str(parsed.get("attack_type") or ""),
        }

    # ─────────────────────────────────────────────
    # 私有：参数化写回（ai_verdict 必须成功；ai_analysis 可选）
    # ─────────────────────────────────────────────
    def _write_back(self, event_id: str, verdict: dict, ai_analysis: str) -> None:
        """参数化 UPDATE 写回 ai_verdict；ai_analysis 缺失不阻断。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ai_verdict_json = json.dumps(verdict, ensure_ascii=False)
        with get_connection() as conn:
            # ai_verdict 为核心列，必须成功写回
            conn.execute(
                "UPDATE security_events SET ai_verdict = ?, updated_at = ? WHERE id = ?",
                (ai_verdict_json, now, event_id),
            )
            # ai_analysis 为可选列（P1 详情展示），列缺失则跳过，不影响主流程
            if ai_analysis:
                try:
                    conn.execute(
                        "UPDATE security_events SET ai_analysis = ?, updated_at = ? WHERE id = ?",
                        (ai_analysis, now, event_id),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("ai_analysis 列写入失败（跳过，不阻断）: %s", exc)
