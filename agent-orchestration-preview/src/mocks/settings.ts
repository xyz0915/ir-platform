import type { DeploymentConfig, ModelProfile } from '@/types';
import { clone, delay, ok, type ApiResponse } from './util';

/** 多模型 profile（F10 流式多模型） */
const MODEL_PROFILES: ModelProfile[] = [
  { profile_id: 'mp-gpt4o', name: 'GPT-4o', provider: 'OpenAI', model: 'gpt-4o', enabled: true },
  { profile_id: 'mp-claude', name: 'Claude 3.5 Sonnet', provider: 'Anthropic', model: 'claude-3-5-sonnet', enabled: true },
  { profile_id: 'mp-qwen', name: '通义千问 Max', provider: '阿里云', model: 'qwen-max', enabled: true },
  { profile_id: 'mp-gemini', name: 'Gemini 1.5 Pro', provider: 'Google', model: 'gemini-1.5-pro', enabled: false },
];

/** 部署配置（F14 无状态 / M0） */
const DEPLOYMENT_CONFIG: DeploymentConfig = {
  stateless_enabled: true,
  redis_connected: true,
  sse_protocol: 'step_* (Orchestrator 统一)',
  hitl_protocol: 'hitl_approval + resume',
};

/** 读取多模型 profile */
export const getModelProfiles = async (): Promise<ApiResponse<ModelProfile[]>> => {
  await delay();
  return ok(clone(MODEL_PROFILES));
};

/** 读取部署配置 */
export const getDeploymentConfig = async (): Promise<ApiResponse<DeploymentConfig>> => {
  await delay();
  return ok(clone(DEPLOYMENT_CONFIG));
};

/** 同步读取多模型 profile（AgentForm 选项，mock 场景可接受） */
export const listModelProfilesSync = (): ModelProfile[] => MODEL_PROFILES;
