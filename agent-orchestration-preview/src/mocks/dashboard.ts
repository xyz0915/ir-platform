import type { DashboardStats } from '@/types';
import { clone, delay, ok, type ApiResponse } from './util';
import { AGENT_RUNS } from './agents';
import { HITL_TASKS } from './hitl';
import { GUARDRAIL_HITS } from './guardrails';

/** 计算 Dashboard 聚合统计（与 agents / hitl / guardrails 同源 mock） */
const buildStats = (): DashboardStats => {
  const running = AGENT_RUNS.filter((r) => r.status === 'running').length;
  const pending = HITL_TASKS.filter((t) => t.status === 'pending').length;
  const finished = AGENT_RUNS.filter(
    (r) => r.status === 'success' || r.status === 'failed'
  );
  const successCount = finished.filter((r) => r.status === 'success').length;
  const successRate = finished.length
    ? Math.round((successCount / finished.length) * 1000) / 10
    : 0;
  const guardrailBlocks = GUARDRAIL_HITS.filter((h) => !h.passed).length;

  const trend = Array.from({ length: 7 }).map((_, i) => {
    const base = 88 + ((i * 13) % 9) - 2;
    return {
      ts: new Date(Date.now() - (6 - i) * 86400000).toISOString(),
      success_rate: Math.max(80, Math.min(99, base)),
    };
  });

  return {
    running_agents: running,
    success_rate: successRate,
    pending_hitl: pending,
    guardrail_blocks: guardrailBlocks,
    recent_runs: AGENT_RUNS.slice(0, 6),
    trend,
  };
};

/** 读取 Dashboard 聚合统计 */
export const getDashboardStats = async (): Promise<ApiResponse<DashboardStats>> => {
  await delay();
  return ok(clone(buildStats()));
};
