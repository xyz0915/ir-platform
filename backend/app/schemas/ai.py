"""AI分析相关的 Pydantic Schema."""

from typing import Optional

from pydantic import BaseModel, Field


class AiConfigCreate(BaseModel):
    """AI配置创建/更新请求."""
    api_base_url: str = Field(..., description="大模型API基础URL", examples=["https://api.openai.com/v1"])
    api_key: Optional[str] = Field(default=None, description="API Key（前端传入明文，后端加密存储；更新时可为空以保留旧值）")
    model_name: str = Field(default="gpt-4o", description="模型名称")
    enabled: int = Field(default=0, description="是否开启（默认关闭）")
    max_tokens: int = Field(default=4096, description="最大生成token数")
    temperature: float = Field(default=0.3, description="生成温度")
    system_prompt: str = Field(default="", description="自定义系统提示词")


class AiConfigResponse(BaseModel):
    """AI配置响应（API Key脱敏）."""
    id: int
    api_base_url: str
    api_key_masked: str = Field(description="脱敏后的API Key（仅显示最后4位）")
    model_name: str
    enabled: int
    max_tokens: int
    temperature: float
    system_prompt: str
    created_at: str
    updated_at: str


class AiToggleRequest(BaseModel):
    """AI功能开关请求."""
    enabled: int = Field(..., description="0=关闭, 1=开启")


class AiAnalysisResponse(BaseModel):
    """AI分析报告响应."""
    id: int
    host_id: int
    case_id: int
    risk_assessment: str = ""
    threat_analysis: str = ""
    timeline_analysis: str = ""
    recommendations: str = ""
    raw_response: str = ""
    model_used: str = ""
    tokens_used: int = 0
    created_at: str = ""
