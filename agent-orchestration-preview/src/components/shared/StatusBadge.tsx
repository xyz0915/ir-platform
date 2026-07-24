import { Chip, type ChipProps } from '@mui/material';
import type { ReactNode } from 'react';

type StatusKey =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'waiting_hitl'
  | 'cancelled'
  | 'low'
  | 'medium'
  | 'high'
  | 'critical'
  | 'approved'
  | 'rejected'
  | 'available'
  | 'degraded'
  | 'disabled'
  | 'online'
  | 'offline'
  | 'active'
  | 'draft';

const MAP: Record<StatusKey, { color: ChipProps['color']; label: string }> = {
  pending: { color: 'warning', label: '排队中' },
  running: { color: 'info', label: '运行中' },
  success: { color: 'success', label: '成功' },
  failed: { color: 'error', label: '失败' },
  waiting_hitl: { color: 'warning', label: '等待审核' },
  cancelled: { color: 'default', label: '已取消' },
  low: { color: 'default', label: '低' },
  medium: { color: 'warning', label: '中' },
  high: { color: 'error', label: '高' },
  critical: { color: 'error', label: '严重' },
  approved: { color: 'success', label: '已批准' },
  rejected: { color: 'error', label: '已拒绝' },
  available: { color: 'success', label: '可用' },
  degraded: { color: 'warning', label: '降级' },
  disabled: { color: 'default', label: '已禁用' },
  online: { color: 'success', label: '在线' },
  offline: { color: 'error', label: '离线' },
  active: { color: 'success', label: '启用' },
  draft: { color: 'warning', label: '草稿' },
};

export interface StatusBadgeProps {
  status: StatusKey | string;
  label?: string;
  size?: 'small' | 'medium';
}

/** 状态徽标：按运行态/严重级别/决策自动配色，避免组件内硬编码颜色 */
export function StatusBadge({ status, label, size = 'small' }: StatusBadgeProps) {
  const hit = MAP[status as StatusKey];
  const color = hit?.color ?? 'default';
  const text = label ?? hit?.label ?? status;
  return (
    <Chip
      size={size}
      color={color}
      label={text}
      variant={color === 'default' ? 'outlined' : 'filled'}
    />
  );
}

export type { ReactNode };
