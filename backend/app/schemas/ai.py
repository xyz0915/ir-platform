"""AI分析相关的 Pydantic Schema — 完整重写.

涵盖多Profile配置、异步任务、审计日志、报告版本管理等全部数据模型.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# AI 配置 Profile 相关
# ============================================================


class AiConfigProfileCreate(BaseModel):
    """AI配置Profile创建请求."""
    profile_name: str = Field(default="默认配置", description="配置名称")
    provider: str = Field(default="openai", description="供应商（openai/azure/anthropic等）")
    api_base_url: str = Field(default="", description="API基础URL")
    api_key: Optional[str] = Field(default=None, description="API Key（前端传入明文，后端加密存储）")
    model_name: str = Field(default="gpt-4o", description="模型名称")
    max_tokens: int = Field(default=4096, description="最大生成token数")
    temperature: float = Field(default=0.3, ge=0.0, le=2.0, description="生成温度")
    system_prompt: str = Field(default="", description="自定义系统提示词")


class AiConfigProfileUpdate(BaseModel):
    """AI配置Profile更新请求."""
    profile_name: Optional[str] = Field(default=None, description="配置名称")
    provider: Optional[str] = Field(default=None, description="供应商")
    api_base_url: Optional[str] = Field(default=None, description="API基础URL")
    api_key: Optional[str] = Field(default=None, description="API Key（为空则不更新）")
    model_name: Optional[str] = Field(default=None, description="模型名称")
    max_tokens: Optional[int] = Field(default=None, description="最大生成token数")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0, description="生成温度")
    system_prompt: Optional[str] = Field(default=None, description="自定义系统提示词")


class AiConfigProfileResponse(BaseModel):
    """AI配置Profile响应（API Key脱敏）."""
    id: int
    profile_name: str
    provider: str
    api_base_url: str
    api_key_masked: str = Field(default="****", description="脱敏后的API Key")
    model_name: str
    max_tokens: int
    temperature: float
    system_prompt: str
    is_active: int
    created_at: str
    updated_at: str


class AiConfigProfileListResponse(BaseModel):
    """AI配置Profile列表响应."""
    items: list[AiConfigProfileResponse] = Field(default_factory=list)
    total: int = 0
    active_id: Optional[int] = Field(default=None, description="当前激活的Profile ID")


class AiTestConnectionRequest(BaseModel):
    """AI连接测试请求."""
    profile_id: int = Field(..., description="要测试的Profile ID")


class AiTestConnectionResponse(BaseModel):
    """AI连接测试响应."""
    success: bool
    message: str
    models: Optional[list[str]] = None


class AiToggleRequest(BaseModel):
    """AI功能开关请求（兼容旧接口）."""
    enabled: int = Field(..., description="0=关闭, 1=开启")


# ============================================================
# AI 分析任务相关
# ============================================================


class AiAnalysisRequest(BaseModel):
    """AI分析请求."""
    host_id: int = Field(..., description="主机ID")
    profile_id: Optional[int] = Field(default=None, description="使用的Profile ID（None则用激活配置）")
    masked_mode: int = Field(default=1, description="是否启用脱敏（0=否, 1=是）")
    mode: str = Field(default="standard", description="分析模式：standard 或 deep_dive")
    focus_area: Optional[str] = Field(default=None, description="深挖焦点领域")
    include_rag_detail: bool = Field(default=True, description="是否返回 RAG 结构化证据")
    include_input_quality: bool = Field(default=True, description="是否返回输入质量评估")
    base_report_id: Optional[int] = Field(default=None, description="基于哪份已有报告继续深挖")


class AiAnalysisTaskResponse(BaseModel):
    """AI分析任务提交响应."""
    task_id: int
    host_id: int
    status: str
    progress: int = 0
    progress_message: str = ""
    created_at: str


class AiTaskStatusResponse(BaseModel):
    """AI任务状态查询响应."""
    id: int
    host_id: int
    profile_id: Optional[int] = None
    status: str
    progress: int = 0
    progress_message: str = ""
    report_id: Optional[int] = None
    error_message: Optional[str] = None
    masked_mode: int = 0
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class AiTaskCancelResponse(BaseModel):
    """AI任务取消响应."""
    task_id: int
    status: str
    message: str


# ============================================================
# AI 分析报告相关
# ============================================================


class AiReportResponse(BaseModel):
    """AI分析报告响应."""
    id: int
    host_id: int
    case_id: int
    version: int = 1
    risk_assessment: str = ""
    threat_analysis: str = ""
    timeline_analysis: str = ""
    recommendations: str = ""
    raw_response: str = ""
    model_used: str = ""
    tokens_used: int = 0
    profile_id: Optional[int] = None
    is_latest: int = 1
    masked_mode: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    created_at: str = ""


class AiReportVersionItem(BaseModel):
    """AI报告版本列表项."""
    id: int
    host_id: int
    version: int
    model_used: str = ""
    tokens_used: int = 0
    is_latest: int = 1
    masked_mode: int = 0
    created_at: str = ""


class AiReportVersionListResponse(BaseModel):
    """AI报告版本列表响应."""
    items: list[AiReportVersionItem] = Field(default_factory=list)
    total: int = 0


# ============================================================
# AI 审计日志相关
# ============================================================


class AiAuditLogQueryParams(BaseModel):
    """审计日志查询参数."""
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数")
    host_id: Optional[int] = Field(default=None, description="按主机ID筛选")
    profile_id: Optional[int] = Field(default=None, description="按Profile ID筛选")
    status: Optional[str] = Field(default=None, description="按状态筛选")
    model_name: Optional[str] = Field(default=None, description="按模型名称筛选")
    start_date: Optional[str] = Field(default=None, description="起始日期")
    end_date: Optional[str] = Field(default=None, description="截止日期")
    masked_mode: Optional[int] = Field(default=None, description="按脱敏模式筛选")
    order_by: str = Field(default="created_at DESC", description="排序方式")


class AiAuditLogResponse(BaseModel):
    """审计日志响应."""
    id: int
    host_id: Optional[int] = None
    host_name: str = ""
    profile_id: Optional[int] = None
    profile_name: str = ""
    model_name: str = ""
    status: str = "success"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    masked_mode: int = 0
    error_message: Optional[str] = None
    ip_address: str = ""
    user_id: Optional[int] = None
    created_at: str = ""


class AiAuditLogListResponse(BaseModel):
    """审计日志列表响应."""
    items: list[AiAuditLogResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class AiAuditLogDetailResponse(AiAuditLogResponse):
    """审计日志详情响应（与列表相同，预留扩展）."""
    pass


# ============================================================
# Token 统计相关
# ============================================================


class AiTokenStatsResponse(BaseModel):
    """Token使用统计响应."""
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    avg_latency_ms: int = 0
    total_cost_estimate: str = "$0.0000"


class AiTokenSummaryItem(BaseModel):
    """Token汇总项."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    avg_latency_ms: int = 0

    # 根据 group_by 动态字段（使用 model_config 允许额外字段）
    model_config = {"extra": "allow"}


class AiTokenSummaryResponse(BaseModel):
    """Token汇总响应."""
    items: list[dict] = Field(default_factory=list)
    group_by: str = "daily"


# ============================================================
# P2 新增 Schema
# ============================================================


class AiChatRequest(BaseModel):
    """多轮对话请求."""
    message: str = Field(..., description="用户消息内容")
    conversation_id: Optional[str] = Field(default=None, description="对话ID，用于多轮对话上下文")
    mode: str = Field(default="follow_up", description="对话模式：follow_up 或 deep_dive")
    focus_area: Optional[str] = Field(default=None, description="深挖焦点领域")
    base_report_id: Optional[int] = Field(default=None, description="关联基础报告ID")
    question_type: Optional[str] = Field(default=None, description="问题类型标签")


class AiChatResponse(BaseModel):
    """多轮对话响应."""
    reply: str = Field(default="", description="AI回复内容")
    conversation_id: Optional[str] = Field(default=None, description="对话ID")
    model_used: str = Field(default="", description="使用的模型名称")
    tokens_used: int = Field(default=0, description="消耗token数")


class CompareRequest(BaseModel):
    """多主机对比分析请求."""
    model_config = {"extra": "ignore"}

    host_ids: list[int] = Field(..., description="要对比的主机ID列表（2-5个）")
    dimensions: list[str] = Field(default=[], description="对比维度，可选: risk, threat, timeline, recommendations")


class CompareTaskResponse(BaseModel):
    """对比分析任务响应."""
    task_id: int
    host_ids: list[int]
    status: str
    message: str = ""


class PromptOptimizeRequest(BaseModel):
    """提示词优化请求."""
    prompt: str = Field(..., description="当前提示词内容")
    feedback: str = Field(default="", description="优化反馈/期望")
    profile_id: Optional[int] = Field(default=None, description="关联的Profile ID")


class PromptOptimizeResponse(BaseModel):
    """提示词优化响应."""
    optimized_prompt: str = Field(default="", description="优化后的提示词")
    version: int = Field(default=1, description="版本号")
    changes: str = Field(default="", description="变更说明")
