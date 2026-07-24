import { useEffect, useState } from 'react';
import { Box, Button, Card, CardContent, Grid, Stack, Typography } from '@mui/material';
import AddAlertIcon from '@mui/icons-material/AddAlert';
import dayjs from 'dayjs';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { EmptyState } from '@/components/shared/EmptyState';
import { StepFlow, type StepItem } from '@/components/shared/StepFlow';
import { useHitlStore } from '@/store/useHitlStore';
import type { HitlTask } from '@/types';
import { HitlContextPanel } from './HitlContextPanel';

export function HitlQueuePage() {
  const tasks = useHitlStore((s) => s.tasks);
  const loading = useHitlStore((s) => s.loading);
  const enqueue = useHitlStore((s) => s.enqueue);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (tasks.length && !selectedId) {
      const firstPending = tasks.find((t) => t.status === 'pending');
      setSelectedId((firstPending ?? tasks[0]).approval_id);
    }
  }, [tasks, selectedId]);

  const pending = tasks.filter((t) => t.status === 'pending').length;

  const flowSteps: StepItem[] = [
    { label: '待审入队', state: pending > 0 ? 'done' : 'todo' },
    { label: '查看上下文', state: selectedId ? 'active' : 'todo' },
    { label: '护栏校验', state: 'done' },
    { label: '批准/拒绝', state: 'todo' },
  ];

  return (
    <Box>
      <PageHeader
        title="人工审核台（HITL）"
        subtitle="统一审批中台：高风险动作必经人工确认（F6 / M0）"
        action={
          <Button variant="contained" startIcon={<AddAlertIcon />} onClick={enqueue}>
            模拟新待审任务
          </Button>
        }
      />

      <Box sx={{ mb: 2 }}>
        <StepFlow steps={flowSteps} />
      </Box>

      <Grid container spacing={2}>
        <Grid item xs={12} md={5}>
          <Stack spacing={1.5}>
            {loading && tasks.length === 0 ? (
              <EmptyState title="加载中…" />
            ) : tasks.length === 0 ? (
              <EmptyState title="队列为空" description="点击「模拟新待审任务」生成一条。" />
            ) : (
              tasks.map((t) => (
                <TaskCard
                  key={t.approval_id}
                  task={t}
                  selected={t.approval_id === selectedId}
                  onClick={() => setSelectedId(t.approval_id)}
                />
              ))
            )}
          </Stack>
        </Grid>
        <Grid item xs={12} md={7}>
          <HitlContextPanel taskId={selectedId} />
        </Grid>
      </Grid>
    </Box>
  );
}

function TaskCard({ task, selected, onClick }: { task: HitlTask; selected: boolean; onClick: () => void }) {
  return (
    <Card
      sx={{
        cursor: 'pointer',
        borderColor: selected ? 'primary.main' : 'divider',
        borderWidth: selected ? 2 : 1,
        boxShadow: selected ? 2 : 0,
      }}
      onClick={onClick}
    >
      <CardContent sx={{ py: 1.5 }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, flexGrow: 1 }}>
            {task.action}
          </Typography>
          <StatusBadge status={task.status} />
        </Stack>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          {task.agent_name} · 影响 {task.impact_scope}
        </Typography>
        <Box sx={{ mt: 0.5 }}>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            入队 {dayjs(task.created_at).format('MM-DD HH:mm')}
            {task.decided_at && ` · 处理 ${dayjs(task.decided_at).format('MM-DD HH:mm')}`}
          </Typography>
        </Box>
      </CardContent>
    </Card>
  );
}
