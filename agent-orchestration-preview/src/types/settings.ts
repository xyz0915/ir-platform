import type { ID } from './common';

/** 多模型 profile —— 对齐 F10 流式多模型 */
export interface ModelProfile {
  profile_id: ID;
  name: string;
  provider: string;
  model: string;
  enabled: boolean;
}

/** 部署配置 —— 对齐 F14 无状态部署 / M0 */
export interface DeploymentConfig {
  /** F14 无状态部署开关 */
  stateless_enabled: boolean;
  /** 外置 Redis 状态 */
  redis_connected: boolean;
  /** 统一 step_* SSE 协议 */
  sse_protocol: string;
  /** 统一审批协议 */
  hitl_protocol: string;
}
