import type { ISODateTime } from './common';
import type { AgentRun } from './agent';

/** Dashboard 聚合统计 */
export interface DashboardStats {
  running_agents: number;
  success_rate: number;
  pending_hitl: number;
  guardrail_blocks: number;
  recent_runs: AgentRun[];
  trend: { ts: ISODateTime; success_rate: number }[];
}
