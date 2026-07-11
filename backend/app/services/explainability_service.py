"""AI 分析可解释性与漏检风险辅助服务."""

from __future__ import annotations

import copy
from typing import Any


class ExplainabilityService:
    """生成证据链、覆盖缺口、推荐追问等结构化辅助信息。"""

    @staticmethod
    def build_coverage_gaps(
        tiered_data: dict[str, Any],
        evidence_items: list[dict[str, Any]],
        input_quality: dict[str, Any],
    ) -> dict[str, list[str]]:
        missing_data: list[str] = []
        weak_evidence: list[str] = []
        blind_spots: list[str] = []
        recommended_collection: list[str] = []

        timeline_events = (
            (tiered_data.get("timeline_high", []) or [])
            + (tiered_data.get("timeline_medium", []) or [])
            + (tiered_data.get("timeline_low", []) or [])
        )
        suspicious_connections = (
            (tiered_data.get("suspicious_connections_high", []) or [])
            + (tiered_data.get("suspicious_connections_medium", []) or [])
            + (tiered_data.get("suspicious_connections_low", []) or [])
        )
        abnormal_processes = (
            (tiered_data.get("abnormal_processes_high", []) or [])
            + (tiered_data.get("abnormal_processes_medium", []) or [])
            + (tiered_data.get("abnormal_processes_low", []) or [])
        )

        if input_quality.get("level") == "low":
            weak_evidence.append("输入质量较低，当前结论可能存在遗漏或置信度下降。")

        if len(evidence_items) < 2:
            weak_evidence.append("RAG/规则证据较少，分析结论更多依赖模型推断。")
            recommended_collection.append("补充更多 IOC、异常行为或历史案例证据后再分析。")

        if len(timeline_events) < 2:
            missing_data.append("关键时间线事件不足，攻击链可能不完整。")
            recommended_collection.append("补充系统日志、进程启动时间和网络连接时间。")

        if not suspicious_connections:
            blind_spots.append("缺少外联证据，无法充分判断 C2 或数据渗出风险。")
            recommended_collection.append("补采网络连接、DNS 访问、代理日志等数据。")

        if not abnormal_processes:
            blind_spots.append("缺少异常进程证据，执行链和父子进程关系不清晰。")
            recommended_collection.append("补采完整进程树和命令行参数。")

        if not missing_data and not weak_evidence and not blind_spots:
            weak_evidence.append("当前分析输入较完整，但仍建议结合人工研判复核高危结论。")

        return {
            "missing_data": missing_data,
            "weak_evidence": weak_evidence,
            "blind_spots": blind_spots,
            "recommended_collection": recommended_collection,
        }

    @staticmethod
    def build_key_conclusions(parsed: dict[str, Any], evidence_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        conclusions: list[dict[str, Any]] = []
        risk = parsed.get("risk_assessment", {}) or {}
        threat = parsed.get("threat_analysis", {}) or {}
        timeline = parsed.get("timeline_analysis", {}) or {}
        evidence_ids = [item.get("evidence_id") for item in evidence_items[:3] if item.get("evidence_id")]

        if risk.get("risk_summary"):
            conclusions.append({
                "conclusion_id": "risk-summary",
                "text": risk.get("risk_summary"),
                "confidence": risk.get("confidence_level") or "medium",
                "evidence_ids": evidence_ids,
                "tags": [risk.get("risk_level") or "unknown", "summary"],
            })

        if threat.get("attack_vector"):
            conclusions.append({
                "conclusion_id": "attack-vector",
                "text": threat.get("attack_vector"),
                "confidence": threat.get("confidence_level") or "medium",
                "evidence_ids": evidence_ids,
                "tags": ["attack_vector"],
            })

        if timeline.get("attack_chain"):
            conclusions.append({
                "conclusion_id": "attack-chain",
                "text": timeline.get("attack_chain"),
                "confidence": timeline.get("confidence_level") or "medium",
                "evidence_ids": evidence_ids,
                "tags": ["timeline"],
            })

        return conclusions

    @staticmethod
    def build_suggested_questions(
        parsed: dict[str, Any],
        coverage_gaps: dict[str, list[str]],
    ) -> list[dict[str, str]]:
        """生成推荐追问（供前端 DeepDiveQuestionPanel 渲染与追问触发）.

        返回对象列表，每个元素形如:
            {
                "title": <短标题（问题文本本身或前 18 字摘要）>,
                "question": <完整问题文本>,
                "focus_area": <对应焦点，用于前端追问路由>,
            }

        focus_area 取值与触发条件对应：
            - attack_vector    威胁分析含 attack_vector
            - attack_chain     时间线分析含 attack_chain
            - missing_data     coverage_gaps 含 missing_data
            - blind_spots      coverage_gaps 含 blind_spots
            - risk             risk_level 为高危/high

        Args:
            parsed: parse_json_response 返回的完整 dict（含 risk_assessment /
                threat_analysis / timeline_analysis）.
            coverage_gaps: build_coverage_gaps 返回的覆盖缺口 dict（可空 {}）.

        Returns:
            推荐追问对象列表（最多 5 条）；每个对象含 title / question /
            focus_area 且均非空。无匹配时返回空列表。
        """
        risk = parsed.get("risk_assessment", {}) or {}
        threat = parsed.get("threat_analysis", {}) or {}
        timeline = parsed.get("timeline_analysis", {}) or {}

        # (完整问题文本, focus_area)
        candidates: list[tuple[str, str]] = []
        if threat.get("attack_vector"):
            candidates.append(
                ("这个攻击入口最可能是怎么成立的？还需要补哪些证据确认？", "attack_vector")
            )
        if timeline.get("attack_chain"):
            candidates.append(
                ("请按时间顺序详细拆解这条攻击链，每一步的证据分别是什么？", "attack_chain")
            )
        if coverage_gaps.get("missing_data"):
            candidates.append(
                ("当前最关键的缺失数据是什么？补采优先级应该怎么排？", "missing_data")
            )
        if coverage_gaps.get("blind_spots"):
            candidates.append(
                ("现有分析盲区主要在哪里？是否可能存在未识别的横向移动或外传？", "blind_spots")
            )
        if risk.get("risk_level") in ("高危", "high"):
            candidates.append(
                ("如果现在立刻处置，最优先要做的三件事是什么？", "risk")
            )

        # 去重（基于完整问题文本），构造对象并保证 title/question/focus_area 均非空
        seen: set[str] = set()
        result: list[dict[str, str]] = []
        for question, focus_area in candidates:
            if question in seen:
                continue
            seen.add(question)
            title = question if len(question) <= 18 else question[:18] + "…"
            result.append({
                "title": title,
                "question": question,
                "focus_area": focus_area,
            })
        return result[:5]

    @staticmethod
    def normalize_key_events(ai_key_events: list, timeline_events: list) -> list:
        """将 AI key_events 与原始 timeline_events 进行模糊匹配，建立关联.

        对每个 AI key_event，按 timestamp + event_type + description 前 30 字符
        模糊匹配 timeline_events，匹配成功则追加 source_event_id。

        Args:
            ai_key_events: AI 分析产出的 key_events 列表.
            timeline_events: 原始时间线事件列表（来自 TimelineEvent.list_by_host）.

        Returns:
            增强后的 key_events 列表，匹配成功的条目含 source_event_id.
        """
        if not ai_key_events or not timeline_events:
            return list(ai_key_events) if ai_key_events else []

        result: list[dict] = []
        # 构建 timeline_events 索引：{event_type: {description_prefix: event}}
        tl_index: dict[str, list[dict]] = {}
        for te in timeline_events:
            if not isinstance(te, dict):
                continue
            et = (te.get("event_type") or "").lower()
            if et not in tl_index:
                tl_index[et] = []
            tl_index[et].append(te)

        for ke in ai_key_events:
            if not isinstance(ke, dict):
                result.append(ke)
                continue

            ke_copy = dict(ke)
            ke_ts: str = (ke_copy.get("timestamp") or ke_copy.get("time") or "").strip()
            ke_type: str = (ke_copy.get("type") or ke_copy.get("event_type") or "").lower()
            ke_desc: str = (ke_copy.get("desc") or ke_copy.get("description") or ke_copy.get("event") or "")
            ke_desc_prefix = ke_desc[:30].lower() if ke_desc else ""

            matched_id = None
            candidates = tl_index.get(ke_type, [])

            for te in candidates:
                te_ts = (te.get("timestamp") or "").strip()
                te_desc = (te.get("description") or "").lower()

                # 匹配条件：时间戳相同 或 描述前 30 字符匹配
                ts_match = ke_ts and te_ts and ke_ts == te_ts
                desc_match = ke_desc_prefix and te_desc and ke_desc_prefix in te_desc

                if ts_match or desc_match:
                    matched_id = te.get("id")
                    break

            if matched_id is not None:
                ke_copy["source_event_id"] = matched_id

            result.append(ke_copy)

        return result

    @staticmethod
    def normalize_section(section: Any) -> dict:
        """把任意 AI 返回的"分段"归一化为安全的可变 dict.

        调用方（ai_task_service / ai_service）会在返回结果上做
        ``.setdefault`` / 键赋值（如 risk_level、evidence_trace），
        因此这里必须返回**新的** dict，禁止就地修改原始 ``parsed``，
        否则会污染上游解析结果。

        Args:
            section: AI 返回的分段内容，可能是 None / 非 dict（畸形 JSON）。

        Returns:
            归一化后的新 dict；非 dict 入参返回空 dict。
        """
        if not isinstance(section, dict):
            return {}
        # 深拷贝：保证嵌套字段的后续修改也不会污染原始 parsed 对象
        return copy.deepcopy(section)

    @staticmethod
    def _normalize_timeline_event(raw: Any) -> dict:
        """把时间线原始条目归一化为前端 StructuredTimeline 期望的字段结构.

        Args:
            raw: 单条时间线事件（来自 AI 的 key_events/events，或 tiered_data 的
                timeline_high/medium/low）。

        Returns:
            含 ``timestamp`` / ``event`` / ``phase`` / ``significance`` 的 dict。
        """
        if not isinstance(raw, dict):
            fallback = str(raw) if raw is not None else "未知事件"
            return {"timestamp": "", "event": fallback, "phase": "待确认", "significance": ""}

        time_val = raw.get("timestamp") or raw.get("time") or ""
        type_val = raw.get("type") or raw.get("event_type") or ""
        desc_val = (
            raw.get("desc")
            or raw.get("description")
            or raw.get("event")
            or ""
        )
        severity_val = raw.get("severity") or raw.get("level") or "unknown"

        significance = f"严重度：{severity_val}" if severity_val and severity_val != "unknown" else ""
        return {
            "timestamp": time_val,
            "event": desc_val or type_val or "未知事件",
            "phase": type_val or "待确认",
            "significance": significance,
        }

    @staticmethod
    def ensure_structured_timeline(timeline_section: Any, tiered_data: Any) -> dict:
        """确保时间线分段具备供前端 StructuredTimelinePanel 渲染的结构。

        行为：
        - 深拷贝 ``timeline_section``，保留 attack_chain / confidence_level /
          timeline_summary 等原有字段；
        - 优先使用 AI 给出的 ``key_events`` / ``events``；
        - 若 AI 未给出，则从 ``tiered_data`` 的 timeline_high / timeline_medium /
          timeline_low 抽取 time / type / desc / severity 组成事件；
        - 最终把事件放到 ``key_events``（前端消费字段名）下。

        Args:
            timeline_section: AI 返回的时间线分段（可能 None / 非 dict / 缺 events）。
            tiered_data: PromptBuilder 组装的分层数据，含 timeline_* 列表。

        Returns:
            含 ``key_events`` 列表及原字段的时间线 dict；永不抛异常。
        """
        result: dict = (
            copy.deepcopy(timeline_section)
            if isinstance(timeline_section, dict)
            else {}
        )
        tiered = tiered_data if isinstance(tiered_data, dict) else {}

        # 1. AI 已给出事件
        ai_events = result.get("key_events") or result.get("events")
        if isinstance(ai_events, list) and len(ai_events) > 0:
            key_events = [
                ExplainabilityService._normalize_timeline_event(e) for e in ai_events
            ]
        else:
            # 2. 从 tiered_data 补齐时间线事件
            raw_entries: list[Any] = []
            for key in ("timeline_high", "timeline_medium", "timeline_low"):
                items = tiered.get(key)
                if isinstance(items, list):
                    raw_entries.extend(items)
            key_events = [
                ExplainabilityService._normalize_timeline_event(e) for e in raw_entries
            ]

        result["key_events"] = key_events
        # 兼容旧字段名（若上游曾用 events），保持单一事实来源
        result.pop("events", None)
        return result

    @staticmethod
    def build_evidence_trace(
        parsed_sections: Any,
        knowledge_items: Any,
        tiered_data: Any,
    ) -> dict:
        """构建证据链与推荐追问，供前端 EvidenceTracePanel / DeepDiveQuestionPanel 消费。

        返回 dict 必须同时包含 ``evidence_trace`` 与 ``recommended_questions`` 两键，
        否则下游（ai_task_service.py / ai_service.py）赋值时会 KeyError。

        ``evidence_trace`` 结构（与前端 EvidenceTracePanel 字段一致）：
        - ``knowledge_evidence``: RAG/规则检索命中的知识条目列表
        - ``local_evidence``: 基于 parsed 威胁/时间线分析提炼的本地证据列表
        - ``explainability_labels``: 证据来源标签列表

        Args:
            parsed_sections: parse_json_response 返回的完整 dict（含四分段）。
            knowledge_items: KnowledgeRetriever.retrieve 的结构化结果（list of dict）。
            tiered_data: PromptBuilder 组装的分层数据。

        Returns:
            含 ``evidence_trace``(object) 与 ``recommended_questions``(list) 的 dict；
            对所有入参做防御，永不抛异常。
        """
        parsed = parsed_sections if isinstance(parsed_sections, dict) else {}
        knowledge = knowledge_items if isinstance(knowledge_items, list) else []
        tiered = tiered_data if isinstance(tiered_data, dict) else {}

        # ---- 知识库证据：直接复用 RAG 检索结果（字段已与前端对齐）----
        knowledge_evidence: list[dict[str, Any]] = []
        for item in knowledge:
            if isinstance(item, dict):
                knowledge_evidence.append(dict(item))  # 浅拷贝，避免副作用

        # ---- 本地证据：从 parsed 的威胁/时间线分析提炼 ----
        local_evidence: list[dict[str, Any]] = []
        threat = parsed.get("threat_analysis") if isinstance(parsed.get("threat_analysis"), dict) else {}
        timeline = parsed.get("timeline_analysis") if isinstance(parsed.get("timeline_analysis"), dict) else {}

        if threat.get("attack_vector"):
            local_evidence.append({"summary": f"攻击入口：{threat.get('attack_vector')}"})
        if threat.get("attack_chain"):
            local_evidence.append({"summary": f"攻击链：{threat.get('attack_chain')}"})
        if timeline.get("attack_chain"):
            local_evidence.append({"summary": f"时间线攻击链：{timeline.get('attack_chain')}"})

        # 兜底：parsed 无内容时，从 tiered_data 的异常信号各取一条
        if not local_evidence:
            for key in ("abnormal_processes_high", "suspicious_connections_high", "persistence_suspicious"):
                items = tiered.get(key)
                if isinstance(items, list) and items:
                    first = items[0]
                    if isinstance(first, dict):
                        local_evidence.append({
                            "summary": f"{key}: {first.get('name') or first.get('process_name') or first.get('type') or '发现异常'}"
                        })
                        break

        # ---- 证据来源标签 ----
        sources: set[str] = set()
        for item in knowledge_evidence:
            src = item.get("source")
            if src:
                sources.add(src)
        explainability_labels = (
            [f"证据来源：{s}" for s in sorted(sources)]
            if sources
            else ["无知识库证据（结论基于模型推断）"]
        )

        evidence_trace: dict[str, Any] = {
            "knowledge_evidence": knowledge_evidence,
            "local_evidence": local_evidence,
            "explainability_labels": explainability_labels,
        }

        # ---- 推荐追问：复用类内 build_suggested_questions（此处无 coverage_gaps）----
        recommended_questions = ExplainabilityService.build_suggested_questions(parsed, {})

        return {
            "evidence_trace": evidence_trace,
            "recommended_questions": recommended_questions,
        }
