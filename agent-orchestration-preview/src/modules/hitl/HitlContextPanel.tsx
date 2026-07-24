import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import type { ReactNode } from 'react';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import { GuardrailChip } from '@/components/shared/GuardrailChip';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { EmptyState } from '@/components/shared/EmptyState';
import { useHitlStore } from '@/store/useHitlStore';
import type { HitlTask } from '@/types';

export interface HitlContextPanelProps {
  taskId: string | null;
}

/** HITL 上下文 + 护栏联动面板（流程③：查看上下文 → 护栏校验 → 批准/拒绝） */
export function HitlContextPanel({ taskId }: HitlContextPanelProps) {
  const task = useHitlStore((s) => s.tasks.find((t) => t.approval_id === taskId)) as HitlTask | undefined;
  const approve = useHitlStore((s) => s.approve);
  const reject = useHitlStore((s) => s.reject);

  const [rejectOpen, setRejectOpen] = useState(false);
  const [reason, setReason] = useState('');

  if (!task) {
    return <EmptyState title="选择左侧待审任务" description="查看完整上下文与护栏校验结果，并做出批准 / 拒绝。" />;
  }

  const decided = task.status !== 'pending';

  return (
    <Paper variant="outlined" sx={{ p: 2.5, height: '100%' }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          {task.action}
        </Typography>
        <StatusBadge status={task.status} />
      </Stack>
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
        触发智能体：{task.agent_name} · 指派：{task.assigned_to ?? '—'}
      </Typography>

      <Divider sx={{ my: 2 }} />

      <Section title="影响范围">
        <Typography variant="body2">{task.impact_scope}</Typography>
      </Section>

      <Section title="触发上下文">
        <Stack spacing={0.5}>
          {Object.entries(task.context).map(([k, v]) => (
            <Box key={k} sx={{ display: 'flex', gap: 1 }}>
              <Typography variant="body2" sx={{ color: 'text.secondary', minWidth: 90 }}>
                {labelOf(k)}：
              </Typography>
              <Typography variant="body2">{String(v)}</Typography>
            </Box>
          ))}
        </Stack>
      </Section>

      <Section title="护栏校验结果">
        <GuardrailChip
          whitelist_hit={task.guardrail_result.whitelist_hit}
          requires_confirm={task.guardrail_result.requires_confirm}
          requires_rollback_plan={task.guardrail_result.requires_rollback_plan}
          passed={task.guardrail_result.passed}
        />
      </Section>

      <Divider sx={{ my: 2 }} />

      {decided ? (
        <Alert severity={task.status === 'approved' ? 'success' : 'error'}>
          {task.status === 'approved' ? '已批准，运行继续。' : '已拒绝，运行终止。'}
          {task.reason && (
            <Box component="div" sx={{ mt: 0.5, fontSize: 13 }}>
              原因：{task.reason}
            </Box>
          )}
        </Alert>
      ) : (
        <Stack direction="row" spacing={1}>
          <Button
            variant="contained"
            color="success"
            startIcon={<CheckCircleIcon />}
            fullWidth
            onClick={() => approve(task.approval_id)}
          >
            批准（继续）
          </Button>
          <Button
            variant="outlined"
            color="error"
            startIcon={<CancelIcon />}
            fullWidth
            onClick={() => setRejectOpen(true)}
          >
            拒绝（终止）
          </Button>
        </Stack>
      )}

      <Dialog open={rejectOpen} onClose={() => setRejectOpen(false)}>
        <DialogTitle>拒绝并终止运行</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 1 }}>
            请填写拒绝原因（将写回审计并终止关联运行）。
          </DialogContentText>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={2}
            label="拒绝原因"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectOpen(false)}>取消</Button>
          <Button
            color="error"
            variant="contained"
            disabled={!reason.trim()}
            onClick={() => {
              reject(task.approval_id, reason.trim());
              setReason('');
              setRejectOpen(false);
            }}
          >
            确认拒绝
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 0.5 }}>
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function labelOf(key: string): string {
  const map: Record<string, string> = {
    trigger_agent: '触发智能体',
    evidence: '证据',
    risk: '风险',
    suggested_by: '建议来源',
  };
  return map[key] ?? key;
}
