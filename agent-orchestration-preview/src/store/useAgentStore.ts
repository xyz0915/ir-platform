import { create } from 'zustand';
import type { AgentConfig, AgentRun, ID, RunStatus } from '@/types';
import { getAgents, getAgentRuns } from '@/mocks/agents';
import { nowISO } from '@/mocks/util';

/** 新建自定义 Agent 的入参（kind 固定 custom） */
export type AddAgentPayload = Omit<
  AgentConfig,
  'agent_id' | 'kind' | 'created_at' | 'updated_at' | 'status'
> & { status?: AgentConfig['status'] };

interface AgentState {
  agents: AgentConfig[];
  runs: AgentRun[];
  loadingAgents: boolean;
  loadingRuns: boolean;

  fetchAgents: () => Promise<void>;
  fetchRuns: () => Promise<void>;

  addAgent: (payload: AddAgentPayload) => AgentConfig;
  getAgent: (id: ID) => AgentConfig | undefined;

  /** HITL 批准后恢复挂起的运行 */
  resumeRun: (runId: ID) => void;
  /** HITL 拒绝后终止运行 */
  cancelRun: (runId: ID) => void;
  /** 流水线运行结束后写入一条运行记录 */
  addRun: (run: AgentRun) => void;
}

export const useAgentStore = create<AgentState>((set, get) => ({
  agents: [],
  runs: [],
  loadingAgents: false,
  loadingRuns: false,

  fetchAgents: async () => {
    set({ loadingAgents: true });
    const res = await getAgents();
    set({ agents: res.data, loadingAgents: false });
  },

  fetchRuns: async () => {
    set({ loadingRuns: true });
    const res = await getAgentRuns();
    set({ runs: res.data, loadingRuns: false });
  },

  addAgent: (payload) => {
    const ts = nowISO();
    const agent: AgentConfig = {
      ...payload,
      agent_id: `agent-custom-${Date.now()}`,
      kind: 'custom',
      status: payload.status ?? 'active',
      created_at: ts,
      updated_at: ts,
    };
    set((s) => ({ agents: [agent, ...s.agents] }));
    return agent;
  },

  getAgent: (id) => get().agents.find((a) => a.agent_id === id),

  resumeRun: (runId) => {
    set((s) => ({
      runs: s.runs.map((r) =>
        r.run_id === runId
          ? {
              ...r,
              status: 'running' as RunStatus,
              summary: '人工审核已批准，运行继续。',
              steps: r.steps.map((st) =>
                st.status === 'waiting_hitl'
                  ? { ...st, status: 'success' as RunStatus, finished_at: nowISO() }
                  : st
              ),
            }
          : r
      ),
    }));
  },

  cancelRun: (runId) => {
    set((s) => ({
      runs: s.runs.map((r) =>
        r.run_id === runId
          ? { ...r, status: 'cancelled' as RunStatus, summary: '人工审核已拒绝，运行终止。' }
          : r
      ),
    }));
  },

  addRun: (run) => set((s) => ({ runs: [run, ...s.runs] })),
}));
