/**
 * 基础公共类型 —— 对齐优化方案语义。
 * 所有时间字段统一使用 ISO 8601 字符串。
 */

/** 通用 ID（字符串） */
export type ID = string;

/** ISO 8601 时间字符串，如 '2026-07-06T17:00:00.000Z' */
export type ISODateTime = string;

/**
 * 运行态状态机。
 * - pending: 排队中
 * - running: 运行中
 * - success: 成功
 * - failed: 失败
 * - waiting_hitl: 等待人工审核（运行挂起）
 * - cancelled: 已取消
 */
export type RunStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'waiting_hitl'
  | 'cancelled';

/** 风险/严重级别 */
export type Severity = 'low' | 'medium' | 'high' | 'critical';

/** 顶部角色切换器：分析师 / SOC 主管 / 编排管理员 */
export type Role = 'analyst' | 'soc_lead' | 'admin';

/** 角色中文标签映射 */
export const ROLE_LABELS: Record<Role, string> = {
  analyst: '安全分析师',
  soc_lead: 'SOC 主管',
  admin: '编排管理员',
};

/** 运行态状态中文标签映射 */
export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  pending: '排队中',
  running: '运行中',
  success: '成功',
  failed: '失败',
  waiting_hitl: '等待审核',
  cancelled: '已取消',
};

/** 严重级别中文标签映射 */
export const SEVERITY_LABELS: Record<Severity, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '严重',
};
