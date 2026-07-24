/**
 * M9 设置 Mock 适配器。
 *
 * 暴露：listModelProfiles() / getDeploymentConfig()
 * 字段对齐 demo types/settings.ts 的 ModelProfile / DeploymentConfig。
 *
 * 设计依据：01-api-spec.md §9。
 */
import { clone, delay, ok } from './util'

/** 多模型 profile（F10 流式多模型） */
const MODEL_PROFILES = [
  { profile_id: 'mp-gpt4o', name: 'GPT-4o', provider: 'OpenAI', model: 'gpt-4o', enabled: true },
  { profile_id: 'mp-claude', name: 'Claude 3.5 Sonnet', provider: 'Anthropic', model: 'claude-3-5-sonnet', enabled: true },
  { profile_id: 'mp-qwen', name: '通义千问 Max', provider: '阿里云', model: 'qwen-max', enabled: true },
  { profile_id: 'mp-gemini', name: 'Gemini 1.5 Pro', provider: 'Google', model: 'gemini-1.5-pro', enabled: false },
]

/** 部署配置（F14 无状态 / M0） */
const DEPLOYMENT_CONFIG = {
  stateless_enabled: true,
  redis_connected: true,
  sse_protocol: 'step_* (Orchestrator 统一)',
  hitl_protocol: 'hitl_approval + resume',
}

export async function listModelProfiles() {
  await delay()
  return ok(clone(MODEL_PROFILES))
}

export async function getDeploymentConfig() {
  await delay()
  return ok(clone(DEPLOYMENT_CONFIG))
}
