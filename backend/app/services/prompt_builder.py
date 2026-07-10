"""分层 Prompt 构建器 — Token 预算控制 + 脱敏支持.

按严重度分层组装数据，使用 tiktoken 做精确 token 计数，
在预算约束下按优先级填充数据，支持脱敏模式.
"""

import json
import logging
import re
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

# ── 模块化 AI 分析常量 ──────────────────────────────────────────────

# 模块名 → 在 _fetch_module_data() 中需要拉取的数据键
MODULE_DATA_MAP: dict[str, list[str]] = {
    "profile":            ["host_basic", "analysis_result", "profile"],
    "process_list":       ["process_list"],
    "abnormal_processes": ["abnormal_processes_all"],
    "connections":        ["suspicious_connections_all"],
    "persistence":        ["persistence_all"],
    "startup":            ["startup_items"],
    "ioc":                ["ioc_hits_all"],
    "timeline":           ["timeline_all"],
    "users":              ["users"],
    "services":           ["services"],
    "usb":                ["usb_devices"],
    "remote_control":     ["remote_tools"],
}

# Token 预算分档（模块化分析专用）
TOKEN_BUDGET_MAP: dict[str, int] = {
    # 重型（4000 tokens）— 数据量大、需要深层次分析
    "process_list":       4000,
    "abnormal_processes": 4000,
    "timeline":           4000,
    # 中型（2000 tokens）— 数据量中等
    "connections":  2000,
    "persistence":  2000,
    "ioc":          2000,
    "startup":      2000,
    "profile":      2000,
    # 轻型（1500 tokens）— 数据量小
    "users":         1500,
    "services":      1500,
    "usb":           1500,
    "remote_control":1500,
}

# 模块分析 risk_assessment 附加的质量相关字段（追加到 threat_type 之后）
_MODULE_RISK_QUALITY_FIELDS = """,
    "input_quality": {
      "score": 0,
      "level": "high/medium/low",
      "summary": "基于本模块数据量/覆盖度的质量评估说明",
      "evidence_counts": {}
    },
    "coverage_gaps": [
      {
        "category": "数据维度名（如 startup_items）",
        "title": "缺失/不足的数据类型",
        "severity": "high/medium/low",
        "description": "该缺失对分析的具体影响",
        "suggestion": "补充该数据的建议"
      }
    ],
    "miss_risk": {
      "level": "high/medium/low",
      "summary": "基于当前有限数据的漏检风险概述",
      "likely_blind_spots": ["可能遗漏的威胁视角"]
    },
    "evidence_insufficiency": [
      {
        "field": "字段名",
        "label": "中文标签",
        "reason": "证据不足以支撑结论的原因"
      }
    ],
"""
MODULE_SYSTEM_PROMPTS: dict[str, str] = {
    "profile": """你是一个专业的网络安全应急响应分析专家。
请针对【主机画像】数据进行专项分析。

## 分析要求
1. 评估主机的系统环境是否正常，识别异常配置
2. 检查安装软件中是否存在高风险/恶意软件
3. 分析用户账户是否有异常（权限、新增账户）
4. 检查安全产品部署情况
5. 评估整体系统基线风险

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "正常/异常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "process_list": """你是一个专业的网络安全应急响应分析专家。
请针对【进程树】数据进行专项分析。

## 分析要求
1. 检查是否存在可疑进程（异常路径、隐藏进程、注入行为）
2. 分析进程父子关系是否异常
3. 识别潜在的恶意软件进程
4. 检查进程命令行参数是否包含可疑特征
5. 评估整体进程环境的威胁程度

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "正常/异常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "abnormal_processes": """你是一个专业的网络安全应急响应分析专家。
请针对【异常进程】数据进行专项分析。

## 分析要求
1. 分析每个异常进程的可疑程度和风险
2. 识别进程间的关联关系
3. 判断是否为已知恶意软件家族
4. 评估异常进程对系统的影响
5. 给出进程处置优先级建议

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "挖矿/勒索/后门/APT/僵尸网络/正常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "ioc_interpretation": "", "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "connections": """你是一个专业的网络安全应急响应分析专家。
请针对【可疑外连】数据进行专项分析。

## 分析要求
1. 分析每个外连的目标地址是否可疑（C2、矿池、恶意域名）
2. 检查外连协议和端口是否异常
3. 分析关联进程与外连的关系
4. 识别潜在的 C2 通信和数据渗出行为
5. 评估外连的整体威胁程度

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "挖矿/勒索/后门/APT/僵尸网络/正常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "ioc_interpretation": "", "lateral_movement_indicators": "", "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "persistence": """你是一个专业的网络安全应急响应分析专家。
请针对【持久化痕迹】数据进行专项分析。

## 分析要求
1. 检查注册表 Run 键、启动文件夹、计划任务等持久化项
2. 识别可疑的持久化机制
3. 判断持久化项是否与恶意软件相关
4. 分析持久化项之间的关联
5. 给出清理建议

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "挖矿/勒索/后门/APT/正常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "startup": """你是一个专业的网络安全应急响应分析专家。
请针对【可疑启动项】数据进行专项分析。

## 分析要求
1. 分析每个启动项的可疑程度
2. 检查启动项路径和命令行是否异常
3. 识别伪装系统进程的启动项
4. 判断启动项是否为恶意软件
5. 给出启动项处置建议

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "正常/异常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "ioc": """你是一个专业的网络安全应急响应分析专家。
请针对【IOC 命中】数据进行专项分析。

## 分析要求
1. 分析每个 IOC 命中的含义和威胁级别
2. 判断 IOC 命中的可信度
3. 关联多个 IOC 命中看是否指向同一威胁
4. 评估 IOC 命中对主机的实际影响
5. 给出基于 IOC 的处置建议

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "挖矿/勒索/后门/APT/僵尸网络/正常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "ioc_interpretation": "", "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "timeline": """你是一个专业的网络安全应急响应分析专家。
请针对【时间线】数据进行专项分析。

## 分析要求
1. 按时间顺序串联安全事件
2. 识别攻击阶段的关键时间节点
3. 判断攻击者活动的时间窗口
4. 分析事件之间的因果关系
5. 构建攻击链时间线

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "挖矿/勒索/后门/APT/正常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "lateral_movement_indicators": "", "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "timeline_analysis": {"attack_stage": "初始访问/执行/持久化/提权/防御规避/横向移动/数据渗出", "key_events": [], "attack_chain": "", "phase_mapping": [], "timeline_summary": ""},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "users": """你是一个专业的网络安全应急响应分析专家。
请针对【用户账户】数据进行专项分析。

## 分析要求
1. 检查是否存在可疑的新增用户
2. 分析用户权限是否异常（管理员权限授予）
3. 识别隐藏用户或克隆账户
4. 检查用户组成员是否异常
5. 评估账户安全风险

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "正常/异常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "services": """你是一个专业的网络安全应急响应分析专家。
请针对【系统服务】数据进行专项分析。

## 分析要求
1. 检查是否存在可疑的系统服务
2. 分析服务二进制路径是否异常
3. 识别伪装成系统服务的恶意程序
4. 检查服务启动类型和权限
5. 评估服务的整体安全风险

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "正常/异常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "usb": """你是一个专业的网络安全应急响应分析专家。
请针对【USB 记录】数据进行专项分析。

## 分析要求
1. 检查是否存在可疑的 USB 设备接入
2. 分析 USB 设备接入时间是否异常
3. 识别可能用于数据窃取的 USB 设备
4. 检查 USB 设备序列号是否在威胁情报中
5. 评估 USB 相关安全风险

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "正常/异常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",

    "remote_control": """你是一个专业的网络安全应急响应分析专家。
请针对【远程工具】数据进行专项分析。

## 分析要求
1. 检查是否存在可疑的远程控制工具
2. 分析远程工具的合法性和必要性
3. 识别攻击者使用的远程管理工具
4. 检查远程工具的执行时间和频率
5. 评估远程访问的安全风险

## 输出格式
严格按以下 JSON 格式输出：
```json
{
  "risk_assessment": {"risk_level": "高危/中危/低危/安全", "risk_score": 0-100, "risk_summary": "汇总", "threat_type": "正常/异常"},
  "threat_analysis": {"attack_vector": "", "malicious_behaviors": [], "evidence_trace": {"knowledge_evidence": [], "local_evidence": [], "evidence_count": 0, "explainability_labels": []}},
  "recommendations": {"immediate_actions": [], "eradication_steps": [], "hardening_suggestions": [], "remediation_priority": "高/中/低", "input_suggestions": [], "recommended_questions": []}
}
```
用中文输出所有分析内容。""",
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


# ── 全貌分析（overview）系统提示 ──────────────────────────────────────────
OVERVIEW_SYSTEM_PROMPT: str = """你是一个专业的网络安全应急响应分析专家。基于提供的主机取证数据，你需要还原本次安全事件的「全貌故事线」。

请严格按照以下 JSON 格式输出，不要添加任何额外的解释说明：

```json
{
  "story_line": "以叙事方式还原的完整攻击故事线（时间顺序，300-800字，中文），串联初始访问→执行→持久化→横向移动→渗出等关键阶段",
  "key_events": [
    {"time": "2026-07-11 10:05", "dimension": "process", "summary": "powershell -enc 内存加载可疑载荷"},
    {"time": "2026-07-11 10:12", "dimension": "connection", "summary": "外连 C2 域名 evil.example.com"}
  ]
}
```

输出要求：
1. story_line 必须基于真实证据，按时间顺序串联各维度线索，形成可读的攻击叙事。
2. key_events 提炼 3-10 个最关键事件，标注 time / dimension（process/connection/registry/persistence/timeline/ioc）/ summary。
3. 缺失证据处明确说明「证据不足，无法还原」，不得编造。
4. 用中文输出所有内容。"""


# ── 处置建议（remediation）系统提示 ──────────────────────────────────────
REMEDIATION_SYSTEM_PROMPT: str = """你是一个专业的网络安全应急响应处置专家。基于提供的主机取证数据，你需要生成「可审核的处置脚本」。

重要约束：
- 你生成的脚本仅供安全人员人工审核后执行，系统绝不自动执行任何脚本。
- 每条脚本必须标注 risk（high/medium/low）、reversible（布尔，是否可逆）、requires_approval（布尔，是否需审批）。

请严格按照以下 JSON 格式输出，不要添加任何额外的解释说明：

```json
{
  "remediation_scripts": [
    {
      "id": "step-1-kill-process",
      "description": "终止可疑 powershell 进程",
      "language": "powershell",
      "script": "Stop-Process -Name powershell -IncludeUserName attacker",
      "risk": "medium",
      "reversible": true,
      "requires_approval": true
    }
  ]
}
```

输出要求：
1. remediation_scripts 为 1-8 条处置脚本，覆盖「止血-隔离-清除-恢复」闭环。
2. 每条必须含 id / description / language / script / risk / reversible / requires_approval。
3. 高风险操作（如删除文件、断开网络、隔离主机）risk 必须为 high 且 requires_approval 为 true。
4. script 必须是可直接复制执行的合法命令，避免含糊描述。
5. 用中文填写 description，script 保持原语言。"""


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
    def build_module(host_id: int, module_type: str, masked: bool = False) -> dict:
        """构建模块专属 AI 分析 prompt.

        与 build() 的区别：
        - 只拉取 MODULE_DATA_MAP[module_type] 对应的数据子集
        - 使用模块专属精简 system_prompt 模板
        - 按 TOKEN_BUDGET_MAP[module_type] 预算组装 user_prompt
        - 不注入知识库（include_knowledge=False）

        Args:
            host_id: 主机 ID.
            module_type: 模块名（如 'connections'、'process_list'）.
            masked: 是否启用脱敏.

        Returns:
            {"system_prompt": str, "user_prompt": str}

        Raises:
            ValueError: 主机不存在或 module_type 无效.
        """
        if module_type not in MODULE_DATA_MAP:
            valid_types = ", ".join(sorted(MODULE_DATA_MAP.keys()))
            raise ValueError(
                f"无效的模块类型 '{module_type}'，有效值：{valid_types}"
            )

        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError(f"主机 {host_id} 不存在")

        # 1. 只拉取该模块需要的专属数据
        module_data = PromptBuilder._fetch_module_data(host_id, module_type)

        # 2. 构建模块专属 system_prompt
        system_prompt = PromptBuilder._build_module_system_prompt(module_type)

        # 3. Token 预算
        system_tokens = PromptBuilder._count_tokens(system_prompt)
        module_budget = TOKEN_BUDGET_MAP.get(module_type, 2000)
        remaining = module_budget - system_tokens - 100  # 预留 100 tokens 缓冲

        if remaining < 0:
            logger.warning(
                "Module system_prompt exceeds token budget (%d > %d), using full budget",
                system_tokens, module_budget,
            )
            remaining = module_budget - system_tokens

        logger.info(
            "Module prompt building: module=%s, system_tokens=%d, budget=%d, remaining=%d",
            module_type, system_tokens, module_budget, remaining,
        )

        # 4. 组装 user_prompt
        user_prompt = PromptBuilder._build_module_user_prompt(
            host=host,
            module_data=module_data,
            budget=remaining,
            masked=masked,
        )

        return {"system_prompt": system_prompt, "user_prompt": user_prompt}

    @staticmethod
    def _fetch_module_data(host_id: int, module_type: str) -> dict:
        """按 MODULE_DATA_MAP 只拉取指定模块需要的数据.

        对 6 个需新增数据源的模块（process_list, startup, users, services,
        usb, remote_control），尽力从现有 DB 表或模型拉取；无法确认数据源
        则返回空数据 + logger.warning，不阻塞流程。

        Args:
            host_id: 主机 ID.
            module_type: 模块名.

        Returns:
            模块数据字典.
        """
        data: dict = {}

        if module_type not in MODULE_DATA_MAP:
            return data

        data_keys = MODULE_DATA_MAP[module_type]

        # ── 主机基础信息 ──
        if "host_basic" in data_keys:
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

        # ── 分析结果 ──
        if "analysis_result" in data_keys:
            analysis = AnalysisResult.get_by_host(host_id)
            if analysis:
                data["analysis_result"] = {
                    "risk_level": analysis.get("risk_level", ""),
                    "risk_score": analysis.get("risk_score", 0),
                    "total_findings": analysis.get("total_findings", 0),
                    "summary": analysis.get("summary", ""),
                }

        # ── 主机画像 ──
        if "profile" in data_keys:
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

        # ── 异常进程（全量） ──
        if "abnormal_processes_all" in data_keys:
            processes = AbnormalProcess.list_by_host(host_id)
            data["abnormal_processes_all"] = [
                {
                    "name": p.get("process_name", ""),
                    "pid": p.get("pid"),
                    "path": p.get("process_path", ""),
                    "cmd": p.get("command_line", ""),
                    "parent_name": p.get("parent_name", ""),
                    "reason": p.get("reason", ""),
                    "severity": p.get("severity", ""),
                    "risk_score": p.get("risk_score", 0),
                }
                for p in processes
            ]

        # ── 可疑外连（全量） ──
        if "suspicious_connections_all" in data_keys:
            connections = SuspiciousConnection.list_by_host(host_id)
            data["suspicious_connections_all"] = [
                {
                    "remote": f"{c.get('remote_address', '')}:{c.get('remote_port', '')}",
                    "protocol": c.get("protocol", ""),
                    "process": c.get("process_name", ""),
                    "reason": c.get("reason", ""),
                    "severity": c.get("severity", ""),
                }
                for c in connections
            ]

        # ── 持久化痕迹（全量） ──
        if "persistence_all" in data_keys:
            persistence = PersistenceItem.list_by_host(host_id)
            data["persistence_all"] = [
                {
                    "type": p.get("type", ""),
                    "name": p.get("name", ""),
                    "command": p.get("command", ""),
                    "location": p.get("location", ""),
                    "suspicious": bool(p.get("is_suspicious")),
                    "reason": p.get("reason", ""),
                }
                for p in persistence
            ]

        # ── IOC 命中（全量） ──
        if "ioc_hits_all" in data_keys:
            ioc_hits = IocHit.list_by_host(host_id)
            data["ioc_hits_all"] = [
                {
                    "type": i.get("ioc_type", ""),
                    "value": i.get("ioc_value", ""),
                    "matched_in": i.get("matched_in", ""),
                    "context": i.get("context", ""),
                    "severity": i.get("severity", ""),
                }
                for i in ioc_hits
            ]

        # ── 时间线（全量） ──
        if "timeline_all" in data_keys:
            timeline = TimelineEvent.list_by_host(host_id)
            data["timeline_all"] = [
                {
                    "time": t.get("timestamp", ""),
                    "type": t.get("event_type", ""),
                    "desc": t.get("description", ""),
                    "severity": t.get("severity", ""),
                }
                for t in timeline
            ]

        # ── 进程树（process_list 模块） ──
        if "process_list" in data_keys:
            try:
                # 尝试通过 Host 模型拉取进程树（raw_json_path 中包含进程信息）
                processes = AbnormalProcess.list_by_host(host_id)
                # 同时拉取主机 raw json 中的完整进程列表
                data["process_list"] = [
                    {
                        "name": p.get("process_name", ""),
                        "pid": p.get("pid"),
                        "path": p.get("process_path", ""),
                        "cmd": p.get("command_line", ""),
                        "parent_pid": p.get("parent_pid"),
                        "parent_name": p.get("parent_name", ""),
                        "reason": p.get("reason", ""),
                        "severity": p.get("severity", ""),
                    }
                    for p in processes
                ]
                if not data["process_list"]:
                    logger.warning(
                        "No process data available for host %d (process_list module)",
                        host_id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to fetch process_list data for host %d: %s", host_id, e,
                )
                data["process_list"] = []

        # ── 启动项（startup 模块） ──
        if "startup_items" in data_keys:
            try:
                from app.models.analysis import SuspiciousStartupItem

                startup_items = SuspiciousStartupItem.list_by_host(host_id)
                data["startup_items"] = [
                    {
                        "name": s.get("name", ""),
                        "command": s.get("command", ""),
                        "location": s.get("location", ""),
                        "type": s.get("type", ""),
                        "user": s.get("user", ""),
                        "reason": s.get("reason", ""),
                        "severity": s.get("severity", ""),
                    }
                    for s in startup_items
                ]
            except Exception as e:
                logger.warning(
                    "Failed to fetch startup_items data for host %d: %s", host_id, e,
                )
                data["startup_items"] = []

        # ── 用户账户（users 模块） ──
        if "users" in data_keys:
            try:
                profile = HostProfile.get_by_host(host_id)
                if profile and profile.get("user_accounts"):
                    data["users"] = {"user_accounts": profile["user_accounts"]}
                else:
                    data["users"] = {}
                    logger.warning(
                        "No user account data available for host %d (users module)",
                        host_id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to fetch users data for host %d: %s", host_id, e,
                )
                data["users"] = {}

        # ── 系统服务（services 模块） ──
        if "services" in data_keys:
            # 当前数据库没有独立的 services 表；返回空数据
            logger.warning(
                "Services data not available for host %d — no dedicated table exists",
                host_id,
            )
            data["services"] = {}

        # ── USB 记录（usb 模块） ──
        if "usb_devices" in data_keys:
            # 当前数据库没有独立的 usb 表；返回空数据
            logger.warning(
                "USB device data not available for host %d — no dedicated table exists",
                host_id,
            )
            data["usb_devices"] = {}

        # ── 远程工具（remote_control 模块） ──
        if "remote_tools" in data_keys:
            # 当前数据库没有独立的 remote_tools 表；返回空数据
            logger.warning(
                "Remote control tool data not available for host %d — no dedicated table exists",
                host_id,
            )
            data["remote_tools"] = {}

        return data

    @staticmethod
    def build_overview(host_id: int, masked: bool = False) -> dict:
        """构建「全貌分析」模式的 system/user prompt（任务② overview）.

        复用 _fetch_tiered_data 聚合主机证据，system prompt 要求模型以 JSON 返回
        story_line（攻击故事线）+ key_events（关键事件）。masked=True 时对证据脱敏。

        Args:
            host_id: 主机 ID.
            masked: 是否对证据脱敏.

        Returns:
            {"system_prompt": str, "user_prompt": str}
        """
        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError(f"主机 {host_id} 不存在")
        tiered_data = PromptBuilder._fetch_tiered_data(host_id)
        if masked:
            try:
                from app.services.data_masking import apply as mask_apply
                tiered_data = mask_apply(tiered_data)
            except Exception as exc:  # noqa: BLE001
                logger.debug("overview 脱敏失败，跳过: %s", exc)
        user_prompt = PromptBuilder._build_overview_user_prompt(tiered_data)
        return {
            "system_prompt": OVERVIEW_SYSTEM_PROMPT.strip(),
            "user_prompt": user_prompt,
        }

    @staticmethod
    def build_remediation(host_id: int, masked: bool = False) -> dict:
        """构建「处置建议」模式的 system/user prompt（任务② remediation）.

        复用 _fetch_tiered_data 聚合主机证据，system prompt 要求模型以 JSON 返回
        remediation_scripts（带 risk/reversible/requires_approval 的可审核脚本）。
        生成的脚本仅供人工审核，系统绝不自动执行。

        Args:
            host_id: 主机 ID.
            masked: 是否对证据脱敏.

        Returns:
            {"system_prompt": str, "user_prompt": str}
        """
        host = Host.get_by_id(host_id)
        if not host:
            raise ValueError(f"主机 {host_id} 不存在")
        tiered_data = PromptBuilder._fetch_tiered_data(host_id)
        if masked:
            try:
                from app.services.data_masking import apply as mask_apply
                tiered_data = mask_apply(tiered_data)
            except Exception as exc:  # noqa: BLE001
                logger.debug("remediation 脱敏失败，跳过: %s", exc)
        user_prompt = PromptBuilder._build_remediation_user_prompt(tiered_data)
        return {
            "system_prompt": REMEDIATION_SYSTEM_PROMPT.strip(),
            "user_prompt": user_prompt,
        }

    @staticmethod
    def _build_overview_user_prompt(tiered_data: dict) -> str:
        """将分层证据拼装为 overview 用户提示文本."""
        import json

        lines: list[str] = []
        hb = tiered_data.get("host_basic", {}) or {}
        lines.append(
            "## 主机信息\n"
            f"主机名: {hb.get('hostname', '')}  IP: {hb.get('ip_address', '')}  "
            f"OS: {hb.get('os_type', '')} {hb.get('os_version', '')}  "
            f"采集时间: {hb.get('collection_time', '')}"
        )
        ar = tiered_data.get("analysis_result", {}) or {}
        lines.append(
            "## 已有分析结论\n"
            f"风险等级: {ar.get('risk_level', '')}  分数: {ar.get('risk_score', 0)}  "
            f"发现数: {ar.get('total_findings', 0)}\n摘要: {ar.get('summary', '')}"
        )
        high_keys = [
            "abnormal_processes_high", "suspicious_connections_high",
            "ioc_hits_high", "timeline_high", "persistence_suspicious",
        ]
        for key in high_keys:
            items = tiered_data.get(key, []) or []
            if items:
                lines.append(f"## {key}\n{json.dumps(items, ensure_ascii=False)}")
        lines.append(
            "\n请基于以上证据还原攻击全貌故事线（story_line）并提炼关键事件（key_events）。"
        )
        return "\n".join(lines)

    @staticmethod
    def _build_remediation_user_prompt(tiered_data: dict) -> str:
        """将分层证据拼装为 remediation 用户提示文本."""
        import json

        lines: list[str] = []
        hb = tiered_data.get("host_basic", {}) or {}
        lines.append(
            "## 主机信息\n"
            f"主机名: {hb.get('hostname', '')}  IP: {hb.get('ip_address', '')}  "
            f"OS: {hb.get('os_type', '')} {hb.get('os_version', '')}"
        )
        ar = tiered_data.get("analysis_result", {}) or {}
        lines.append(
            "## 已有分析结论\n"
            f"风险等级: {ar.get('risk_level', '')}  分数: {ar.get('risk_score', 0)}"
        )
        high_keys = [
            "abnormal_processes_high", "suspicious_connections_high",
            "ioc_hits_high", "persistence_suspicious",
        ]
        for key in high_keys:
            items = tiered_data.get(key, []) or []
            if items:
                lines.append(f"## {key}\n{json.dumps(items, ensure_ascii=False)}")
        lines.append(
            "\n请基于以上证据生成可审核的处置脚本（remediation_scripts），"
            "严禁编造，高风险操作必须标注 requires_approval=true。"
        )
        return "\n".join(lines)

    @staticmethod
    def _build_module_system_prompt(module_type: str) -> str:
        """获取模块专属 system_prompt 模板（自动注入质量字段）.

        Args:
            module_type: 模块名.

        Returns:
            system_prompt 字符串.
        """
        prompt = MODULE_SYSTEM_PROMPTS.get(module_type, "")
        if not prompt:
            logger.warning(
                "No system prompt defined for module '%s', using default",
                module_type,
            )
            prompt = SYSTEM_PROMPT_TEMPLATE.strip()

        # 在 risk_assessment 对象的 threat_type 之后注入质量字段
        # 匹配： "threat_type": "xxx"}   → 插入 quality 字段后再加 }
        prompt = re.sub(
            r'("threat_type"\s*:\s*"[^"]*")(\s*\})',
            r'\g<1>' + _MODULE_RISK_QUALITY_FIELDS + r'    \g<2>',
            prompt,
            count=1,
        )
        return prompt.strip()

    @staticmethod
    def _build_module_user_prompt(
        host: dict,
        module_data: dict,
        budget: int,
        masked: bool,
    ) -> str:
        """按 Token 预算组装模块专属 user prompt.

        与 _build_user_prompt() 的区别：
        - 使用模块专属 budget（而非全局 AI_INPUT_BUDGET）
        - 数据量小，直接全部序列化，超出则截断

        Args:
            host: 主机信息.
            module_data: 模块数据字典.
            budget: Token 预算.
            masked: 是否脱敏.

        Returns:
            组装好的 user_prompt 字符串.
        """
        if masked:
            from app.services.data_masking import apply as mask_apply

            module_data = mask_apply(dict(module_data))

        hostname = host.get("hostname", "N/A")
        ip = host.get("ip_address", "N/A")
        os_type = host.get("os_type", "N/A")
        os_version = host.get("os_version", "N/A")

        intro = (
            f"请基于以下主机数据进行专业分析：\n\n"
            f"主机: {hostname}\n"
            f"IP: {ip}\n"
            f"OS: {os_type} {os_version}\n"
        )

        # 将模块数据序列化为 JSON
        data_json = json.dumps(module_data, ensure_ascii=False, indent=2)

        # 先在预算内组装，超了做截断
        candidate = intro + "\n## 模块数据\n" + data_json
        candidate_tokens = PromptBuilder._count_tokens(candidate)

        if candidate_tokens <= budget:
            final = candidate
        else:
            # 截断策略：保留 intro + 截断数据 JSON
            intro_tokens = PromptBuilder._count_tokens(intro)
            header = "\n## 模块数据\n"
            header_tokens = PromptBuilder._count_tokens(header)
            available = budget - intro_tokens - header_tokens
            if available <= 0:
                final = intro
            else:
                # 逐字符缩短 data_json 直到符合预算
                truncated = data_json
                while PromptBuilder._count_tokens(truncated) > available and len(truncated) > 0:
                    truncated = truncated[:int(len(truncated) * 0.9)]
                truncated += "\n... [数据因 token 预算限制已截断]"
                final = intro + header + truncated

        total_tokens = PromptBuilder._count_tokens(final)
        logger.info(
            "Module user prompt built: tokens=%d/%d",
            total_tokens, budget,
        )
        return final

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
