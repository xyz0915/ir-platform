import { useEffect, useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  Grid,
  IconButton,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import dayjs from 'dayjs';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { StatCard } from '@/components/shared/StatCard';
import { EmptyState } from '@/components/shared/EmptyState';
import { getGuardrailPolicies, getGuardrailHits } from '@/mocks/guardrails';
import type { GuardrailHit, GuardrailPolicy, Severity } from '@/types';

const RISK_LEVELS: Severity[] = ['low', 'medium', 'high', 'critical'];

export function GuardrailPage() {
  const [policies, setPolicies] = useState<GuardrailPolicy[]>([]);
  const [hits, setHits] = useState<GuardrailHit[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({
    name: '',
    action_pattern: '',
    risk_level: 'high' as Severity,
    require_confirm: true,
    rollback_plan: '',
  });

  useEffect(() => {
    let alive = true;
    Promise.all([getGuardrailPolicies(), getGuardrailHits()]).then(([p, h]) => {
      if (!alive) return;
      setPolicies(p.data);
      setHits(h.data);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const toggleEnabled = (id: string) => {
    setPolicies((prev) => prev.map((p) => (p.policy_id === id ? { ...p, enabled: !p.enabled } : p)));
  };

  const removePolicy = (id: string) => {
    setPolicies((prev) => prev.filter((p) => p.policy_id !== id));
  };

  const savePolicy = () => {
    if (!form.name.trim() || !form.action_pattern.trim()) return;
    const policy: GuardrailPolicy = {
      policy_id: `gp-custom-${Date.now()}`,
      name: form.name.trim(),
      action_pattern: form.action_pattern.trim(),
      whitelist: [],
      risk_level: form.risk_level,
      require_confirm: form.require_confirm,
      rollback_plan: form.rollback_plan.trim() || '（未配置）',
      enabled: true,
    };
    setPolicies((prev) => [policy, ...prev]);
    setDialogOpen(false);
    setForm({ name: '', action_pattern: '', risk_level: 'high', require_confirm: true, rollback_plan: '' });
  };

  const enabledCount = policies.filter((p) => p.enabled).length;
  const blockCount = hits.filter((h) => !h.passed).length;

  return (
    <Box>
      <PageHeader
        title="护栏与安全"
        subtitle="action 白名单 + 高危确认 + 回滚预案（F8 P0，上线硬前提）"
        action={
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialogOpen(true)}>
            新增策略
          </Button>
        }
      />

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} md={3}>
          <StatCard label="策略总数" value={policies.length} tone="primary" />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard label="已启用" value={enabledCount} tone="success" />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard label="命中次数" value={hits.length} tone="info" />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard label="拦截次数" value={blockCount} tone="error" />
        </Grid>
      </Grid>

      <Typography variant="subtitle1" sx={{ mb: 1.5 }}>
        护栏策略
      </Typography>
      {loading ? (
        <EmptyState title="加载中…" />
      ) : (
        <Grid container spacing={2}>
          {policies.map((p) => (
            <Grid item xs={12} md={6} key={p.policy_id}>
              <Card>
                <CardContent>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700, flexGrow: 1 }}>
                      {p.name}
                    </Typography>
                    <StatusBadge status={p.risk_level} label={`风险:${riskLabel(p.risk_level)}`} />
                  </Stack>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    模式：<Box component="span" sx={{ fontFamily: 'monospace' }}>{p.action_pattern}</Box>
                  </Typography>
                  <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5, my: 1 }}>
                    {p.require_confirm && <Chip size="small" color="warning" variant="outlined" label="需确认" />}
                    <Chip size="small" color="info" variant="outlined" label="需回滚预案" />
                    {p.whitelist.length > 0 && <Chip size="small" color="secondary" variant="outlined" label={`白名单 ${p.whitelist.length}`} />}
                  </Stack>
                  <Typography variant="body2" sx={{ color: 'text.secondary', mb: 1 }}>
                    回滚：{p.rollback_plan}
                  </Typography>
                  <Divider sx={{ my: 1 }} />
                  <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                    <FormControlLabel
                      control={<Switch checked={p.enabled} onChange={() => toggleEnabled(p.policy_id)} />}
                      label={p.enabled ? '已启用' : '已停用'}
                    />
                    <Tooltip title="删除策略">
                      <IconButton size="small" onClick={() => removePolicy(p.policy_id)} aria-label="删除">
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      <Divider sx={{ my: 3 }} />

      <Typography variant="subtitle1" sx={{ mb: 1.5 }}>
        近期命中记录
      </Typography>
      <Stack spacing={1.5}>
        {hits.map((h, i) => (
          <Card key={i}>
            <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <Box sx={{ flexGrow: 1 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {h.action}
                </Typography>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  策略 {h.policy_id} · {dayjs(h.timestamp).format('MM-DD HH:mm')}
                </Typography>
              </Box>
              <StatusBadge status={h.passed ? 'success' : 'failed'} label={h.passed ? '通过' : '拦截'} />
            </CardContent>
          </Card>
        ))}
        {hits.length === 0 && <EmptyState title="暂无命中" />}
      </Stack>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>新增护栏策略</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="策略名称"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              fullWidth
            />
            <TextField
              label="action 模式（如 host:isolate:*）"
              value={form.action_pattern}
              onChange={(e) => setForm({ ...form, action_pattern: e.target.value })}
              fullWidth
            />
            <TextField
              select
              label="风险级别"
              value={form.risk_level}
              onChange={(e) => setForm({ ...form, risk_level: e.target.value as Severity })}
              fullWidth
            >
              {RISK_LEVELS.map((r) => (
                <option key={r} value={r}>
                  {riskLabel(r)}
                </option>
              ))}
            </TextField>
            <FormControlLabel
              control={
                <Switch
                  checked={form.require_confirm}
                  onChange={(e) => setForm({ ...form, require_confirm: e.target.checked })}
                />
              }
              label="强制人工确认"
            />
            <TextField
              label="回滚预案"
              value={form.rollback_plan}
              onChange={(e) => setForm({ ...form, rollback_plan: e.target.value })}
              fullWidth
              multiline
              minRows={2}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>取消</Button>
          <Button variant="contained" onClick={savePolicy}>
            保存
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function riskLabel(r: Severity): string {
  return { low: '低', medium: '中', high: '高', critical: '严重' }[r];
}
