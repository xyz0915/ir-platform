/**
 * 智能体编排模块统一标签 / 颜色映射常量。
 *
 * 移植自 demo types/common.ts / hitl.ts / pipeline.ts / tool.ts 的 LABELS，
 * 供 StatusBadge / GuardrailChip 等组件复用，避免散落硬编码。
 */

/** 运行态 RunStatus → 中文标签 */
export const RUN_STATUS_LABELS = {
  pending: '排队中',
  running: '运行中',
  success: '成功',
  failed: '失败',
  waiting_hitl: '等待审核',
  cancelled: '已取消',
}

/** 运行态 RunStatus → Element Plus tag 颜色 */
export const RUN_STATUS_TAG = {
  pending: 'info',
  running: 'primary',
  success: 'success',
  failed: 'danger',
  waiting_hitl: 'warning',
  cancelled: 'info',
}

/** 严重级别 Severity → 中文标签 */
export const SEVERITY_LABELS = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '严重',
}

/** 严重级别 Severity → 颜色 */
export const SEVERITY_COLOR = {
  low: '#22C55E',
  medium: '#3B82F6',
  high: '#F59E0B',
  critical: '#EF4444',
}

/** 角色 Role → 中文标签 */
export const ROLE_LABELS = {
  analyst: '安全分析师',
  soc_lead: 'SOC 主管',
  admin: '编排管理员',
}

/** HITL 决策 HitlDecision → 中文标签 */
export const HITL_DECISION_LABELS = {
  pending: '待审核',
  approved: '已批准',
  rejected: '已拒绝',
}

/** HITL 决策 → 颜色 */
export const HITL_DECISION_COLOR = {
  pending: '#F59E0B',
  approved: '#22C55E',
  rejected: '#EF4444',
}

/** DAG 节点类型 → 中文标签 */
export const NODE_TYPE_LABELS = {
  trigger: '触发',
  investigate: '调查',
  forensic: '取证',
  remediate: '处置',
  guardrail: '护栏',
  hitl: '人工审核',
  end: '结束',
}

/** DAG 节点类型 → 主题色 */
export const NODE_TYPE_COLOR = {
  trigger: '#64748B',
  investigate: '#3B82F6',
  forensic: '#8B5CF6',
  remediate: '#EF4444',
  guardrail: '#F59E0B',
  hitl: '#22C55E',
  end: '#10B981',
}

/** 工具状态 ToolStatus → 中文标签 / 颜色 */
export const TOOL_STATUS_LABELS = {
  available: '可用',
  degraded: '降级',
  disabled: '停用',
}
export const TOOL_STATUS_COLOR = {
  available: '#22C55E',
  degraded: '#F59E0B',
  disabled: '#94A3B8',
}

/** MCP 服务器状态 → 中文标签 / 颜色 */
export const MCP_STATUS_LABELS = {
  online: '在线',
  offline: '离线',
  degraded: '降级',
}
export const MCP_STATUS_COLOR = {
  online: '#22C55E',
  offline: '#EF4444',
  degraded: '#F59E0B',
}
