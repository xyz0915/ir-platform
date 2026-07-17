"""AI 降噪 · 优先推荐事件服务（v2）.

核心流程：
  收集已匹配事件 → 构建一行摘要 → 调用 LLM 研判 → 保存结果
    - attack:  生成新 security_events 行 (event_type='ai_recommended') + ai_analysis
    - suspicious: 原事件标记 ai_verdict
    - false_positive: 原事件标记 ai_verdict

方案文档: deliverables/software-audit-case8/AI-noise-reduction-v2.md
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Optional

from app.database import get_connection
from app.services.frontend_projection import infer_t_code

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Step 1: 数据库加列
# ═══════════════════════════════════════════════════════════════

def ensure_ai_columns() -> None:
    """确保 security_events 表有 AI 降噪所需列（幂等）。"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(security_events)").fetchall()}
        if "ai_verdict" not in columns:
            conn.execute("ALTER TABLE security_events ADD COLUMN ai_verdict TEXT")
            logger.info("Added column ai_verdict to security_events")
        if "ai_analysis" not in columns:
            conn.execute("ALTER TABLE security_events ADD COLUMN ai_analysis TEXT DEFAULT ''")
            logger.info("Added column ai_analysis to security_events")
        conn.commit()


# ═══════════════════════════════════════════════════════════════
# Step 2: AI 降噪服务（3 函数）
# ═══════════════════════════════════════════════════════════════


def build_events_summary(events: list[dict]) -> str:
    """将事件列表压缩为 LLM 友好的一行摘要格式.

    每行格式:  事件ID | T-code | 事件类型 | 关键概要 | 命中规则(置信度)
    """
    lines: list[str] = []
    for ev in events:
        eid = ev.get("id", "?")[:20]
        etype = ev.get("event_type", "?")
        mr = ev.get("matched_rules")
        if isinstance(mr, str):
            try:
                mr = json.loads(mr)
            except (json.JSONDecodeError, TypeError):
                mr = []
        mr_list = mr if isinstance(mr, list) else []

        # T-code
        tcode = infer_t_code(etype, mr_list)

        # 关键概要：从 evidence 或 summary 提取
        summary = ev.get("summary", "") or ""
        evidence = ev.get("evidence", {})
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except (json.JSONDecodeError, TypeError):
                evidence = {}
        proc = evidence.get("process_name") or evidence.get("file_name") or ""
        cmd = evidence.get("command_line") or ""
        proc = str(proc)[:20]
        cmd = str(cmd)[:30]
        brief = proc + (" " + cmd if cmd else "")

        # 规则摘要
        rule_hits = ";".join(
            f"{r.get('rule_name','?')}({r.get('confidence',0)})"
            for r in mr_list[:3]
        )

        line = f"{eid} | {tcode} | {etype} | {brief[:50]} | {rule_hits}"
        lines.append(line)
    return "\n".join(lines)


# ── Prompt 模板 ──

# System Prompt（AI 配置中设置，用于替换默认 system prompt）
AI_NOISE_REDUCE_SYSTEM = "你是一个网络安全应急响应专家。严格按用户指令对事件进行三分类研判（attack/suspicious/false_positive），始终以 JSON 数组格式输出。"

AI_NOISE_REDUCE_PROMPT = """你是一个网络安全应急响应专家。请对以下事件进行三分类研判。

【分类标准】
- attack：确认真实攻击，有明确恶意行为证据（非系统目录、已知攻击工具、可疑编码、持久化机制）
- suspicious：可疑但证据不足，需要人工复核（行为异常但可能为正常软件）
- false_positive：确认误报（系统行为、正常业务、已知白名单）

【已知误报模式】（请特别注意不要将这些标记为 attack）
- svchost.exe / conhost.exe / csrss.exe 等系统进程的正常子进程
- Windows Update 相关路径（C:\\Windows\\SoftwareDistribution）
- 常见办公软件安装路径（AppData\\Local\\Programs）
- 杀毒软件（MsMpEng.exe, Defender）

【事件列表】（每行格式：事件ID | T-code | 事件类型 | 关键概要 | 命中规则(置信度)）
{events_summary}

【输出要求】
返回 JSON 数组，每条格式：
{{
  "event_id": "原事件ID",
  "label": "attack/suspicious/false_positive",
  "confidence": 0-100,
  "reason": "研判理由（15字以内）",
  "action": "isolate/kill_process/block_ip/review",
  "attack_type": "持久化/横向移动/执行/提权/防御规避",
  "t_code": "T1059",
  "ai_summary": "[AI研判]攻击|置信92%|T1059|非系统目录脚本执行|建议:隔离"
}}

⚠️ ai_summary 必须严格遵循格式：`[AI研判]{{label}}|置信{{confidence}}%|{{t_code}}|{{reason}}|建议:{{action}}`
⚠️ reason 控制在 15 字以内，ai_summary 整行控制在 50 字以内"""


async def analyze_with_llm(summary: str, case_context: str = "") -> list[dict]:
    """发送给 LLM 研判 → 解析返回的 JSON 数组.

    优先使用系统中已配置的真实 AI（AiService），
    未配置时回退到 mock（开发/测试环境）。
    """
    prompt = AI_NOISE_REDUCE_PROMPT.format(events_summary=summary)

    # 优先使用真实 AI（带超时保护）
    try:
        from app.models.ai_config import AiConfig
        import asyncio
        config = await asyncio.wait_for(
            asyncio.to_thread(AiConfig.get), timeout=3.0
        )
        if config and config.get("enabled"):
            from app.services.ai_service import AiService
            api_key = AiService.decrypt_api_key(config["api_key"])
            system_prompt = config.get("system_prompt") or AI_NOISE_REDUCE_SYSTEM
            raw_resp = await asyncio.wait_for(
                AiService.call_llm(
                    api_base_url=config["api_base_url"],
                    api_key=api_key,
                    model=config.get("model_name", "gpt-4o"),
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    max_tokens=config.get("max_tokens", 4096),
                    temperature=config.get("temperature", 0.3),
                ),
                timeout=180.0,
            )
            raw = raw_resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            if raw:
                logger.info("LLM noise-reduce response received (%d chars)", len(raw))
                return _parse_llm_response(raw)
    except asyncio.TimeoutError:
        logger.warning("Real AI call timed out, falling back to mock")
    except ImportError:
        logger.debug("AiService/AiConfig not available")
    except Exception as e:
        logger.warning("Real AI call failed, falling back to mock: %s", e)

    # fallback: 模拟返回（开发/测试环境无真实 LLM）
    logger.warning("Using mock response for noise-reduce")
    raw = _mock_llm_response(summary)
    return _parse_llm_response(raw)


def _parse_llm_response(raw: str) -> list[dict]:
    """从 LLM 返回文本中解析 JSON 数组。"""
    # 尝试提取 ```json ... ``` 块
    if "```json" in raw:
        start = raw.index("```json") + 7
        end = raw.index("```", start) if "```" in raw[start:] else len(raw)
        raw = raw[start:end].strip()
    elif "```" in raw:
        start = raw.index("```") + 3
        end = raw.index("```", start) if "```" in raw[start:] else len(raw)
        raw = raw[start:end].strip()

    # 尝试直接解析 JSON
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # 尝试逐行提取 JSON（模型可能每行输出一个 JSON 对象）
    lines = [l.strip() for l in raw.split("\n") if l.strip().startswith("{") and l.strip().endswith("}")]
    if lines:
        try:
            return [json.loads(l) for l in lines]
        except (json.JSONDecodeError, TypeError):
            pass

    logger.error("Failed to parse LLM response: %s", raw[:500])
    return []


def _mock_llm_response(summary: str) -> str:
    """开发/测试用的模拟 LLM 响应。"""
    lines = summary.strip().split("\n")
    results = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("|")
        event_id = parts[0].strip() if len(parts) > 0 else "?"
        t_code = parts[1].strip() if len(parts) > 1 else "?"
        etype = parts[2].strip() if len(parts) > 2 else "?"

        # 简单规则：system 进程路径的标记为 false_positive
        is_fp = any(kw in line.lower() for kw in ["svchost", "conhost", "csrss", "explorer.exe", "msmpeng"])
        label = "false_positive" if is_fp else "attack"
        confidence = 85 if label == "attack" else 95
        action = "review" if label == "false_positive" else "review"
        results.append({
            "event_id": event_id,
            "label": label,
            "confidence": confidence,
            "reason": "系统正常进程" if is_fp else "非系统目录执行",
            "action": action,
            "attack_type": "执行",
            "t_code": t_code,
            "ai_summary": f"[AI研判]{label}|置信{confidence}%|{t_code}|{'系统进程' if is_fp else '可疑执行'}|建议:{action}",
        })
    return json.dumps(results, ensure_ascii=False)


def save_results(verdicts: list[dict], original_events: dict[str, dict]) -> dict:
    """将 AI 研判结果写入数据库.

    Args:
        verdicts: AI 返回的研判结果列表.
        original_events: {event_id: event_dict} 用于复制原事件字段.

    Returns:
        {"attack": N, "suspicious": N, "false_positive": N, "ai_events": N}
    """
    stats: dict[str, int] = {"attack": 0, "suspicious": 0, "false_positive": 0, "ai_events": 0}

    with get_connection() as conn:
        for v in verdicts:
            event_id = v.get("event_id", "")

            # 查找原始事件：LLM 可能返回截断的 ID，需要前缀匹配
            original = original_events.get(event_id)
            if original is None:
                # 尝试前缀匹配
                for full_id, evt in original_events.items():
                    if full_id.startswith(event_id):
                        original = evt
                        break
            label = v.get("label", "suspicious")
            confidence = v.get("confidence", 0)
            reason = v.get("reason", "")
            action = v.get("action", "review")
            attack_type = v.get("attack_type", "")
            t_code = v.get("t_code", "")
            ai_summary = v.get("ai_summary", "")

            # 构建 ai_verdict JSON
            verdict_json = json.dumps({
                "label": label,
                "confidence": confidence,
                "reason": reason,
                "action": action,
                "attack_type": attack_type,
                "t_code": t_code,
            }, ensure_ascii=False)

            # 更新原事件的 ai_verdict
            conn.execute(
                "UPDATE security_events SET ai_verdict = ? WHERE id = ?",
                (verdict_json, event_id),
            )
            stats[label] = stats.get(label, 0) + 1

            # attack → 生成 AI 推荐事件
            if label == "attack":
                if original is None:
                    logger.warning("Cannot find original event for %s, skipping", event_id)
                    continue
                ai_event_id = f"ai:{event_id}"
                # 避免重复生成
                existing = conn.execute(
                    "SELECT id FROM security_events WHERE id = ?", (ai_event_id,)
                ).fetchone()
                if existing:
                    continue

                # 构建证据
                evidence = original.get("evidence", {})
                if isinstance(evidence, str):
                    try:
                        evidence = json.loads(evidence)
                    except (json.JSONDecodeError, TypeError):
                        evidence = {}
                if not isinstance(evidence, dict):
                    evidence = {}
                evidence["_ai_verdict"] = verdict_json
                evidence["_ai_analysis"] = ai_summary

                # summary 沿用原始事件的摘要（AI 分析文本存 ai_analysis 列）
                # 先计算原始事件的摘要
                from app.services.event_enrichment import build_event_summary
                orig_evi = original.get("evidence", {})
                if isinstance(orig_evi, str):
                    try: orig_evi = json.loads(orig_evi)
                    except: orig_evi = {}
                if not isinstance(orig_evi, dict):
                    orig_evi = {}
                orig_summary = build_event_summary({
                    "event_type": original.get("event_type", ""),
                    "severity": original.get("severity", "info"),
                    "host_id": original.get("host_id"),
                    "hostname": original.get("hostname", ""),
                    "evidence": orig_evi,
                })

                # 构建证据（注入 AI 研判和原始摘要）
                evidence = original.get("evidence", {})
                if isinstance(evidence, str):
                    try:
                        evidence = json.loads(evidence)
                    except (json.JSONDecodeError, TypeError):
                        evidence = {}
                if not isinstance(evidence, dict):
                    evidence = {}
                evidence["_ai_verdict"] = verdict_json
                evidence["_ai_analysis"] = ai_summary
                evidence["_original_summary"] = orig_summary

                conn.execute(
                    """INSERT OR IGNORE INTO security_events
                       (id, event_type, severity, status, host_id, timestamp,
                        attack_stage, attack_chain_id, matched_rules, ioc_matches,
                        evidence, assignee, related_events, source_collector,
                        event_key, created_at, updated_at, ai_analysis)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        ai_event_id,
                        "ai_recommended",
                        original.get("severity", "medium"),
                        "pending",
                        original.get("host_id", 0),
                        original.get("timestamp", datetime.now().isoformat()),
                        original.get("attack_stage"),
                        None,
                        original.get("matched_rules", "[]"),
                        "[]",
                        json.dumps(evidence, ensure_ascii=False),
                        None,
                        "[]",
                        "ai_noise_reduce",
                        f"ai:{event_id}",
                        datetime.now().isoformat(),
                        datetime.now().isoformat(),
                        ai_summary,
                    ),
                )
                stats["ai_events"] = stats.get("ai_events", 0) + 1

        conn.commit()

    logger.info("AI noise-reduce done: attack=%d suspicious=%d fp=%d ai_events=%d",
                 stats["attack"], stats["suspicious"], stats["false_positive"], stats["ai_events"])
    return stats


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════


async def noise_reduce(case_id: int, host_id: Optional[int] = None) -> dict:
    """AI 降噪研判完整流程（供 API 调用）。

    Args:
        case_id: 案件 ID.
        host_id: 可选的主机 ID，不传则全案件.

    Returns:
        {"total", "attack", "suspicious", "false_positive", "ai_events"}
    """
    ensure_ai_columns()

    # 1. 获取已匹配事件（提前计算摘要）
    with get_connection() as conn:
        where = "se.host_id IN (SELECT id FROM hosts WHERE case_id=?)"
        params: list = [case_id]
        if host_id:
            where = "se.host_id = ?"
            params = [host_id]

        rows = conn.execute(
            f"SELECT se.*, h.hostname, h.ip_address, "
            f"c.name as case_name, c.case_number "
            f"FROM security_events se "
            f"LEFT JOIN hosts h ON h.id = se.host_id "
            f"LEFT JOIN cases c ON c.id = h.case_id "
            f"WHERE {where} AND se.matched_rules IS NOT NULL "
            f"AND se.matched_rules != '[]' AND se.matched_rules != 'null'",
            params,
        ).fetchall()

    events: list[dict] = []
    events_by_id: dict[str, dict] = {}
    for r in rows:
        d = dict(r)
        events.append(d)
        events_by_id[d["id"]] = d

    if not events:
        return {"total": 0, "attack": 0, "suspicious": 0, "false_positive": 0, "ai_events": 0}

    # 2. 构建摘要 → LLM 研判
    summary = build_events_summary(events)
    verdicts = await analyze_with_llm(summary)

    # 3. 保存结果
    stats = save_results(verdicts, events_by_id)
    stats["total"] = len(events)
    return stats
