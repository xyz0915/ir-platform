import { create } from 'zustand';
import type { AgentRun, HitlTask, ID } from '@/types';
import { getHitlTasks } from '@/mocks/hitl';
import { nowISO } from '@/mocks/util';
import { useAgentStore } from './useAgentStore';

interface HitlState {
  tasks: HitlTask[];
  loading: boolean;

  fetchTasks: () => Promise<void>;
  /** 待审数量（TopBar 角标 / Dashboard 使用） */
  pendingCount: () => number;
  /** 批准（恢复挂起运行） */
  approve: (approvalId: ID, reason?: string) => void;
  /** 拒绝（终止运行并写回原因） */
  reject: (approvalId: ID, reason: string) => void;
  /** 模拟新待审任务入队（演示角标 +1 与运行挂起） */
  enqueue: () => void;
}

export const useHitlStore = create<HitlState>((set, get) => ({
  tasks: [],
  loading: false,

  fetchTasks: async () => {
    set({ loading: true });
    const res = await getHitlTasks();
    set({ tasks: res.data, loading: false });
  },

  pendingCount: () => get().tasks.filter((t) => t.status === 'pending').length,

  approve: (approvalId, reason) => {
    set((s) => ({
      tasks: s.tasks.map((t) =>
        t.approval_id === approvalId
          ? {
              ...t,
              status: 'approved',
              decided_at: nowISO(),
              reason: reason || '已确认动作合规，批准执行。',
            }
          : t
      ),
    }));
    // 联动：恢复对应 AgentRun
    const task = get().tasks.find((t) => t.approval_id === approvalId);
    if (task) useAgentStore.getState().resumeRun(task.run_id);
  },

  reject: (approvalId, reason) => {
    set((s) => ({
      tasks: s.tasks.map((t) =>
        t.approval_id === approvalId
          ? { ...t, status: 'rejected', decided_at: nowISO(), reason }
          : t
      ),
    }));
    const task = get().tasks.find((t) => t.approval_id === approvalId);
    if (task) useAgentStore.getState().cancelRun(task.run_id);
  },

  enqueue: () => {
    const ts = nowISO();
    const runId = `run-sim-${Date.now()}`;
    const approvalId = `hitl-sim-${Date.now()}`;
    // 写入一条等待审核的运行（供审批后恢复）
    const run: AgentRun = {
      run_id: runId,
      agent_id: 'agent-remediate',
      agent_name: '处置响应 Agent',
      status: 'waiting_hitl',
      trigger: 'manual',
      started_at: ts,
      steps: [
        {
          step_id: `s-${Date.now()}`,
          run_id: runId,
          name: '拟执行：隔离可疑主机',
          kind: 'hitl',
          status: 'waiting_hitl',
          started_at: ts,
          hitl_ref: approvalId,
        },
      ],
      guardrail_hits: [],
      hitl_tasks: [approvalId],
      summary: '实时检测到新待审动作，运行已挂起。',
      severity: 'high',
    };
    useAgentStore.getState().addRun(run);

    const task: HitlTask = {
      approval_id: approvalId,
      run_id: runId,
      agent_name: '处置响应 Agent',
      action: '隔离可疑主机 WIN-NEW-99',
      impact_scope: '1 台主机 / 访客网段',
      context: {
        trigger_agent: '处置响应 Agent',
        evidence: '检测到新加入主机的异常外联行为',
        risk: 'high',
        suggested_by: 'netflow: 实时告警',
      },
      guardrail_result: {
        policy_id: 'gp-host-isolate',
        whitelist_hit: false,
        requires_confirm: true,
        requires_rollback_plan: true,
        passed: true,
      },
      status: 'pending',
      assigned_to: 'analyst',
      created_at: ts,
    };
    set((s) => ({ tasks: [task, ...s.tasks] }));
  },
}));
