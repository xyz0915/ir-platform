"""分层 Prompt 构建器 — Token 预算控制 + 脱敏支持.

按严重度分层组装数据，使用 tiktoken 做精确 token 计数，
在预算约束下按优先级填充数据，支持脱敏模式.
"""

import json
import logging
from typing import Any, Optional

from app.services.input_quality_service import InputQualityService

from app.config import settings
from app.models.analysis import (
    AbnormalProcess,
    AnalysisResult,
    HostProfile,
    IocHit,
    PersistenceItem,
    SuspiciousConnection,
    TimelineEvent,
)
from app.models.host import Host

logger = logging.getLogger(__name__)

# tiktoken 编码器（cl100k_base 兼容 gpt-4o / gpt-4 / gpt-3.5-turbo）
try:
    import tiktoken

    _ENCODER = tiktoken.get_encoding("cl100k_base")
except ImportError:
    _ENCODER = None
    logger.warning("tiktoken not available, falling back to character-based estimation")


# 数据优先级分层（按严重度 + 重要性排序）
TIER_1_KEYS: list[str] = ["host_basic"]
TIER_2_KEYS: list[str] = ["analysis_result"]
TIER_3_KEYS: list[str] = [
    "ioc_hits_high",
    "abnormal_processes_high",
    "suspicious_connections_high",
]
TIER_4_KEYS: list[str] = [
    "ioc_hits_medium",
    "abnormal_processes_medium",
    "suspicious_connections_medium",
]
TIER_5_KEYS: list[str] = [
    "timeline_high",
    "timeline_medium",
]
TIER_6_KEYS: list[str] = [
    "persistence_suspicious",
]
TIER_7_KEYS: list[str] = [
    "profile",
    "ioc_hits_low",
    "abnormal_processes_low",
    "timeline_low",
    "persistence_all",
]

# 输出 JSON Schema 要求
OUTPUT_JSON_SCHEMA: dict = {
    "type": "json_object",
    "description": "AI 分析结果 JSON",
}

SYSTEM_PROMPT_TEMPLATE: str = """你是一个专业的网络安全应急响应分析专家。基于提供的主机取证数据和分析结果，你需要进行全面深入的安全分析。

请严格按照以下 JSON 格式输出，不要添加任何额外的解释说明：

```json
{
  "risk_assessment": {
    "risk_level": "高危/中危/低危/安全之一",
    "risk_score": 0-100的整数,
    "risk_summary": "风险评估总结（100字以内）",
    "threat_type": "威胁类型：挖矿/勒索/后门/APT/僵尸网络/网页后门/正常",
    "input_quality": {
      "score": 0,
      "level": "high/medium/low",
      "summary": "输入质量总结",
      "evidence_counts": {}
    },
    "coverage_gaps": [
      {
        "category": "timeline_events",
        "title": "缺失时间线",
        "severity": "high/medium/low",
        "description": "覆盖缺口说明",
        "suggestion": "建议补充的信息"
      }
    ],
    "miss_risk": {
      "level": "high/medium/low",
      "summary": "漏检风险概述",
      "likely_blind_spots": ["可能漏掉的维度"]
    },
    "evidence_insufficiency": [
      {
        "field": "timeline_events",
        "label": "时间线",
        "reason": "证据不足原因"
      }
    ]
  },
  "threat_analysis": {
    "attack_vector": "可能的攻击入口和向量描述",
    "malicious_behaviors": ["恶意行为1", "恶意行为2"],
    "ioc_interpretation": "IOC命中解读",
    "lateral_movement_indicators": "横向移动迹象",
    "evidence_trace": {
      "knowledge_evidence": [],
      "local_evidence": [],
      "evidence_count": 0,
      "explainability_labels": []
    }
  },
  "timeline_analysis": {
    "attack_stage": "攻击阶段判断（初始访问/执行/持久化/提权/防御规避/横向移动/数据渗出）",
    "key_events": [{"timestamp": "ISO时间", "event": "事件描述", "significance": "重要性说明", "phase": "阶段"}],
    "attack_chain": "攻击链路串联描述",
    "phase_mapping": [{"timestamp": "ISO时间", "event": "事件描述", "phase": "阶段"}],
    "timeline_summary": "时间线整体总结"
  },
  "recommendations": {
    "immediate_actions": ["紧急处置措施1", "紧急处置措施2"],
    "eradication_steps": ["清除步骤1", "清除步骤2"],
    "hardening_suggestions": ["加固建议1", "加固建议2"],
    "remediation_priority": "高/中/低",
    "input_suggestions": [],
    "recommended_questions": []
  }
}
```

分析要求：
1. 结合 IOC 命中、异常进程、可疑外连、持久化痕迹、时间线等数据进行综合研判
2. 时间线分析需要串联事件形成攻击链，并补齐 key_events / phase_mapping / timeline_summary
3. 必须显式说明输入质量、覆盖缺口、漏检风险，不能仅给出结论
4. threat_analysis 中必须包含 evidence_trace，引用参考知识和本地证据
5. 处置建议要具体可执行，不能笼统，并生成适合二次追问的 recommended_questions
6. 用中文输出所有分析内容"""


class PromptBuilder:
    """分层 Prompt 构建器.

    静态方法 build() 组装主机数据为结构化的 system/user prompt 对，
    使用 Token 预算控制确保不超出模型上下文窗口，支持数据脱敏.
    """

    @staticmethod
    def build(host_id: int, masked: bool = False, include_knowledge: bool = True) -> dict:
        """构建 AI 分析用的 system prompt 和 user prompt.

        数据组装流程：
        1. 从数据库拉取主机及各维度分析数据
        2. 按严重度分层分类
        3. 构建 system prompt（包含 JSON Schema 要求）
        4. 计算 system prompt tokens，得到剩余预算
        5. 按优先级逐层填充 user prompt 数据，超出预算则截断
        6. 如果 masked=True，对数据应用脱敏
        7. 如果 include_knowledge=True，注入知识库检索结果、规则命中、历史案例

        Args:
            host_id: 主机 ID.
            masked: 是否启用数据脱敏.
            include_knowledge: 是否注入知识库和历史案例上下文.

        Returns:
            {"system_prompt": str, "user_prompt": str}

        Raises:
            ValueError: 主机不存在.
        """
        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError(f"主机 {host_id} 不存在")

        # 1. 拉取所有数据
        tiered_data = PromptBuilder._fetch_tiered_data(host_id)

        # 2. 预先计算输入质量与覆盖缺口，作为模型外兜底
        quality_context = InputQualityService.evaluate(tiered_data)
        tiered_data["input_quality"] = quality_context["input_quality"]
        tiered_data["input_suggestions"] = quality_context["input_suggestions"]
        tiered_data["coverage_gaps"] = quality_context["coverage_gaps"]
        tiered_data["miss_risk"] = quality_context["miss_risk"]
        tiered_data["evidence_insufficiency"] = quality_context["evidence_insufficiency"]

        # 3. 构建 system prompt（固定）
        system_prompt = SYSTEM_PROMPT_TEMPLATE.strip()

        # 3. Token 预算
        system_tokens = PromptBuilder._count_tokens(system_prompt)
        budget = settings.AI_INPUT_BUDGET
        remaining = budget - system_tokens - 200  # 预留 200 tokens 缓冲

        if remaining < 0:
            raise ValueError(f"System prompt 超出 token 预算 ({system_tokens} > {budget})")

        logger.info(
            "Prompt building: system_tokens=%d, budget=%d, remaining=%d",
            system_tokens,
            budget,
            remaining,
        )

        # 4. 按优先级填充 user prompt
        user_prompt = PromptBuilder._build_user_prompt(
            host=host,
            tiered_data=tiered_data,
            remaining_budget=remaining,
            masked=masked,
        )

        # 5. 注入知识库、规则命中、历史案例（P2）
        if include_knowledge:
            knowledge_section = PromptBuilder._build_knowledge_section(
                host_id=host_id,
                host=host,
                tiered_data=tiered_data,
            )
            if knowledge_section:
                knowledge_tokens = PromptBuilder._count_tokens(knowledge_section)
                user_tokens = PromptBuilder._count_tokens(user_prompt)
                total_tokens = user_tokens + knowledge_tokens
                if total_tokens <= settings.AI_INPUT_BUDGET:
                    user_prompt = user_prompt + knowledge_section
                    logger.info(
                        "Knowledge section injected: +%d tokens (total=%d)",
                        knowledge_tokens, total_tokens,
                    )
                else:
                    logger.warning(
                        "Knowledge section skipped: would exceed budget (%d > %d)",
                        total_tokens, settings.AI_INPUT_BUDGET,
                    )

        return {"system_prompt": system_prompt, "user_prompt": user_prompt}

    @staticmethod
    def _fetch_tiered_data(host_id: int) -> dict:
        """从数据库拉取各层数据并按严重度分类.

        Returns:
            分层数据字典.
        """
        data: dict = {
            "host_basic": {},
            "analysis_result": {},
            "profile": {},
            "ioc_hits_high": [],
            "ioc_hits_medium": [],
            "ioc_hits_low": [],
            "abnormal_processes_high": [],
            "abnormal_processes_medium": [],
            "abnormal_processes_low": [],
            "suspicious_connections_high": [],
            "suspicious_connections_medium": [],
            "suspicious_connections_low": [],
            "timeline_high": [],
            "timeline_medium": [],
            "timeline_low": [],
            "persistence_suspicious": [],
            "persistence_all": [],
        }

        # 主机基础信息
        host = Host.get_by_id(host_id)
        if host:
            data["host_basic"] = {
                "hostname": host.get("hostname", ""),
                "ip_address": host.get("ip_address", ""),
                "os_type": host.get("os_type", ""),
                "os_version": host.get("os_version", ""),
                "status": host.get("status", ""),
                "collection_time": host.get("collection_time", ""),
            }

        # 分析结果
        analysis = AnalysisResult.get_by_host(host_id)
        if analysis:
            data["analysis_result"] = {
                "risk_level": analysis.get("risk_level", ""),
                "risk_score": analysis.get("risk_score", 0),
                "total_findings": analysis.get("total_findings", 0),
                "summary": analysis.get("summary", ""),
            }

        # 主机画像
        profile = HostProfile.get_by_host(host_id)
        if profile:
            data["profile"] = {
                "system_summary": profile.get("system_summary", ""),
                "cpu_info": profile.get("cpu_info", ""),
                "memory_info": profile.get("memory_info", ""),
                "security_products": profile.get("security_products", ""),
                "user_accounts": profile.get("user_accounts", ""),
                "installed_software": profile.get("installed_software", ""),
            }

        # IOC 命中（按严重度分）
        ioc_hits = IocHit.list_by_host(host_id)
        for item in ioc_hits:
            sev = (item.get("severity") or "medium").lower()
            entry = {
                "type": item.get("ioc_type", ""),
                "value": item.get("ioc_value", ""),
                "matched_in": item.get("matched_in", ""),
                "context": item.get("context", ""),
                "severity": item.get("severity", ""),
            }
            if sev in ("critical", "high"):
                data["ioc_hits_high"].append(entry)
            elif sev == "medium":
                data["ioc_hits_medium"].append(entry)
            else:
                data["ioc_hits_low"].append(entry)

        # 异常进程（按严重度分）
        processes = AbnormalProcess.list_by_host(host_id)
        for item in processes:
            sev = (item.get("severity") or "medium").lower()
            entry = {
                "name": item.get("process_name", ""),
                "pid": item.get("pid"),
                "path": item.get("process_path", ""),
                "cmd": item.get("command_line", ""),
                "parent_name": item.get("parent_name", ""),
                "reason": item.get("reason", ""),
                "severity": item.get("severity", ""),
                "risk_score": item.get("risk_score", 0),
            }
            if sev in ("critical", "high"):
                data["abnormal_processes_high"].append(entry)
            elif sev == "medium":
                data["abnormal_processes_medium"].append(entry)
            else:
                data["abnormal_processes_low"].append(entry)

        # 可疑外连（按严重度分）
        connections = SuspiciousConnection.list_by_host(host_id)
        for item in connections:
            sev = (item.get("severity") or "medium").lower()
            entry = {
                "remote": f"{item.get('remote_address', '')}:{item.get('remote_port', '')}",
                "protocol": item.get("protocol", ""),
                "process": item.get("process_name", ""),
                "reason": item.get("reason", ""),
                "severity": item.get("severity", ""),
            }
            if sev in ("critical", "high"):
                data["suspicious_connections_high"].append(entry)
            elif sev == "medium":
                data["suspicious_connections_medium"].append(entry)
            else:
                data["suspicious_connections_low"].append(entry)

        # 时间线（按严重度分）
        timeline = TimelineEvent.list_by_host(host_id)
        for item in timeline:
            sev = (item.get("severity") or "info").lower()
            entry = {
                "time": item.get("timestamp", ""),
                "type": item.get("event_type", ""),
                "desc": item.get("description", ""),
                "severity": item.get("severity", ""),
            }
            if sev in ("critical", "high"):
                data["timeline_high"].append(entry)
            elif sev == "medium":
                data["timeline_medium"].append(entry)
            else:
                data["timeline_low"].append(entry)

        # 持久化痕迹
        persistence = PersistenceItem.list_by_host(host_id)
        for item in persistence:
            entry = {
                "type": item.get("type", ""),
                "name": item.get("name", ""),
                "command": item.get("command", ""),
                "location": item.get("location", ""),
                "suspicious": bool(item.get("is_suspicious")),
                "reason": item.get("reason", ""),
            }
            data["persistence_all"].append(entry)
            if item.get("is_suspicious"):
                data["persistence_suspicious"].append(entry)

        return data

    @staticmethod
    def _build_user_prompt(
        host: dict,
        tiered_data: dict,
        remaining_budget: int,
        masked: bool,
    ) -> str:
        """按优先级逐层组装 user prompt，在预算内最大化数据量.

        策略：
        - 逐层追加 JSON 数据块
        - 每追加一层后检查 token 数
        - 超出预算则停止填充后续层
        - 在最后层做截断处理

        Args:
            host: 主机信息.
            tiered_data: 分层数据.
            remaining_budget: 剩余 token 预算.
            masked: 是否脱敏.

        Returns:
            组装好的 user prompt 字符串.
        """
        # 脱敏处理
        if masked:
            from app.services.data_masking import apply as mask_apply

            tiered_data = mask_apply(tiered_data)

        # 构建用户提示开头
        intro_lines = [
            "请基于以下主机取证数据和分析结果进行专业安全应急响应分析：\n",
            f"主机: {host.get('hostname', 'N/A')}",
            f"IP: {host.get('ip_address', 'N/A')}",
            f"OS: {host.get('os_type', 'N/A')} {host.get('os_version', 'N/A')}\n",
        ]

        intro_text = "\n".join(intro_lines)

        # 所有数据层定义（按优先级排序）
        all_tiers: list[tuple[str, str, Any]] = [
            ("host_basic", "## 主机基础信息", tiered_data.get("host_basic", {})),
            ("analysis_result", "## 本地分析结果", tiered_data.get("analysis_result", {})),
            ("ioc_hits_high", "## IOC 命中 (高危)", tiered_data.get("ioc_hits_high", [])),
            ("abnormal_processes_high", "## 异常进程 (高危)", tiered_data.get("abnormal_processes_high", [])),
            ("suspicious_connections_high", "## 可疑外连 (高危)", tiered_data.get("suspicious_connections_high", [])),
            ("ioc_hits_medium", "## IOC 命中 (中危)", tiered_data.get("ioc_hits_medium", [])),
            ("abnormal_processes_medium", "## 异常进程 (中危)", tiered_data.get("abnormal_processes_medium", [])),
            ("suspicious_connections_medium", "## 可疑外连 (中危)", tiered_data.get("suspicious_connections_medium", [])),
            ("timeline_high", "## 时间线 (高危)", tiered_data.get("timeline_high", [])),
            ("timeline_medium", "## 时间线 (中危)", tiered_data.get("timeline_medium", [])),
            ("persistence_suspicious", "## 可疑持久化痕迹", tiered_data.get("persistence_suspicious", [])),
            ("profile", "## 主机画像", tiered_data.get("profile", {})),
            ("ioc_hits_low", "## IOC 命中 (低危)", tiered_data.get("ioc_hits_low", [])),
            ("abnormal_processes_low", "## 异常进程 (低危)", tiered_data.get("abnormal_processes_low", [])),
            ("timeline_low", "## 时间线 (低危)", tiered_data.get("timeline_low", [])),
            ("persistence_all", "## 所有持久化痕迹", tiered_data.get("persistence_all", [])),
        ]

        # 组装数据
        parts: list[str] = [intro_text]
        current_text = intro_text
        budget_exceeded: bool = False

        for tier_key, section_title, section_data in all_tiers:
            if budget_exceeded:
                break

            # 跳过空数据
            if isinstance(section_data, (list, dict)) and not section_data:
                continue
            if isinstance(section_data, str) and not section_data:
                continue

            section_json = json.dumps(section_data, ensure_ascii=False, indent=2)
            section_text = f"\n{section_title}\n{section_json}"

            # 计算如果加上这层后的总 tokens
            candidate_text = current_text + section_text
            candidate_tokens = PromptBuilder._count_tokens(candidate_text)

            if candidate_tokens > remaining_budget:
                budget_exceeded = True
                logger.info(
                    "Token budget exceeded at tier '%s' (would be %d > %d), stopping",
                    tier_key,
                    candidate_tokens,
                    remaining_budget,
                )
                continue

            parts.append(section_text)
            current_text = candidate_text

        result = "".join(parts)
        total_tokens = PromptBuilder._count_tokens(result)
        logger.info(
            "User prompt built: tokens=%d/%d, tiers_included=%d",
            total_tokens,
            remaining_budget,
            len(parts) - 1,
        )
        return result

    @staticmethod
    def _build_knowledge_section(
        host_id: int,
        host: dict,
        tiered_data: dict,
    ) -> str:
        """构建知识库增强区域.

        包括：
        - 知识库 RAG 检索结果
        - 规则联动推理（actual_matches）
        - 历史案例匹配

        Args:
            host_id: 主机ID.
            host: 主机信息.
            tiered_data: 分层数据.

        Returns:
            知识库区域文本（以 ## 标注）.
        """
        sections: list[str] = []

        # --- P2-02: 知识库 RAG ---
        try:
            from app.services.knowledge_retriever import KnowledgeRetriever

            knowledge_items = KnowledgeRetriever.retrieve(tiered_data, limit=5, structured=True)
            if knowledge_items:
                sections.append("## 参考知识\n以下是根据当前主机数据匹配的安全规则知识，请参考这些规则进行分析：")
                for item in knowledge_items:
                    title = item.get("title", item.get("rule_name", "未命名规则"))
                    summary = item.get("summary", item.get("formatted_text", ""))
                    confidence = item.get("confidence", "medium")
                    sections.append(f"- [{confidence}] {title}: {summary}")
                sections.append("")
        except Exception as e:
            logger.warning("Knowledge retrieval failed: %s", e)

        # --- P2-03: 规则命中联动 ---
        try:
            actual_matches_section = PromptBuilder._build_actual_matches(tiered_data)
            if actual_matches_section:
                sections.append(actual_matches_section)
        except Exception as e:
            logger.warning("Actual matches building failed: %s", e)

        # --- P2-04: 历史案例匹配 ---
        try:
            case_section = PromptBuilder._build_case_context(host_id, tiered_data)
            if case_section:
                sections.append(case_section)
        except Exception as e:
            logger.warning("Case matching failed: %s", e)

        return "\n".join(sections) if sections else ""

    @staticmethod
    def _build_actual_matches(tiered_data: dict) -> str:
        """构建规则命中联动段.

        从 tiered_data 中提取 IOC 命中和异常进程的 rule_name，
        加载对应规则描述，注入到 prompt 中让 AI 解释命中原因和置信度.

        Args:
            tiered_data: 分层数据.

        Returns:
            规则命中文本.
        """
        import json
        from pathlib import Path

        # 收集所有相关 reason 字段
        matched_reasons: set[str] = set()

        for key in [
            "ioc_hits_high", "ioc_hits_medium", "ioc_hits_low",
            "abnormal_processes_high", "abnormal_processes_medium", "abnormal_processes_low",
            "suspicious_connections_high", "suspicious_connections_medium",
            "persistence_suspicious",
        ]:
            for item in tiered_data.get(key, []):
                if isinstance(item, dict):
                    reason = item.get("reason", "")
                    if reason:
                        matched_reasons.add(reason)

        if not matched_reasons:
            return ""

        # 尝试加载对应规则描述
        rules_path = Path(settings.BACKEND_DIR) / "app" / "rules" / "default_rules.json"
        rules_desc: dict[str, str] = {}
        if rules_path.exists():
            with open(rules_path, "r", encoding="utf-8") as f:
                all_rules = json.load(f)
            for reason in matched_reasons:
                for rule in all_rules:
                    name = rule.get("name", "")
                    desc = rule.get("description", "")
                    severity = rule.get("severity", "")
                    # 模糊匹配：reason 包含 rule name 或反之
                    if (name.lower() in reason.lower() or
                            any(word in name.lower() for word in reason.lower().split() if len(word) >= 3)):
                        rules_desc[name] = f"[{severity}] {desc}"

        lines = [
            "## 命中规则\n以下规则在本地分析中被触发。请在分析报告中：",
            "1. 解释每条规则命中的可能原因",
            "2. 给出对该命中结果的置信度评估（高/中/低）",
            "",
        ]

        if rules_desc:
            for i, (name, desc) in enumerate(rules_desc.items(), 1):
                lines.append(f"{i}. **{name}**: {desc}")
                lines.append(f"   置信度评估：___（请填写高/中/低），原因：___")
        else:
            lines.append("以下是本地引擎标记的原因：")
            for reason in list(matched_reasons)[:10]:
                lines.append(f"- {reason}")

        return "\n".join(lines)

    @staticmethod
    def _build_case_context(host_id: int, tiered_data: dict) -> str:
        """构建历史案例上下文.

        Args:
            host_id: 当前主机ID.
            tiered_data: 分层数据.

        Returns:
            案例上下文文本.
        """
        from app.models.host import Host
        from app.models.analysis import AnalysisResult
        from app.services.case_matcher import CaseMatcher

        host = Host.get_by_id(host_id)
        if not host:
            return ""

        case_id = host.get("case_id", 0)
        analysis = AnalysisResult.get_by_host(host_id)
        risk_level = (analysis.get("risk_level", "") if analysis else "") or ""

        sections: list[str] = []

        # 同案件上下文
        same_case = CaseMatcher.get_same_case_context(host_id, case_id, limit=2)
        if same_case:
            sections.append("## 同案件历史分析\n以下是同一案件中其他主机的AI分析摘要，供参考对比：")
            sections.append(same_case)

        # 相似案例
        if risk_level:
            similar = CaseMatcher.get_similar_cases(host_id, risk_level, limit=3)
            if similar:
                sections.append(f"## 相似风险案例\n以下是历史同风险等级（{risk_level}）的案例分析，供参考处置：")
                sections.append(similar)

        return "\n\n".join(sections) if sections else ""

    @staticmethod
    def _count_tokens(text: str) -> int:
        """使用 tiktoken 精确计算 token 数.

        Args:
            text: 要计数的文本.

        Returns:
            token 数量.
        """
        if _ENCODER is not None:
            try:
                tokens = _ENCODER.encode(text)
                return len(tokens)
            except Exception:
                pass
        # 回退：粗略估算（英文约 4 字符/token，中文约 1.5 字符/token）
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        ascii_chars = len(text) - chinese_chars
        return int(ascii_chars / 4 + chinese_chars / 1.5)
