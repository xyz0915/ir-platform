import { useEffect, useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  FormControlLabel,
  Grid,
  Paper,
  Stack,
  Switch,
  Typography,
} from '@mui/material';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import CloudDoneIcon from '@mui/icons-material/CloudDone';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { EmptyState } from '@/components/shared/EmptyState';
import { getModelProfiles, getDeploymentConfig } from '@/mocks/settings';
import type { DeploymentConfig, ModelProfile } from '@/types';

export function SettingsPage() {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [deploy, setDeploy] = useState<DeploymentConfig | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    Promise.all([getModelProfiles(), getDeploymentConfig()]).then(([p, d]) => {
      if (!alive) return;
      setProfiles(p.data);
      setDeploy(d.data);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const toggleProfile = (id: string) => {
    setProfiles((prev) => prev.map((p) => (p.profile_id === id ? { ...p, enabled: !p.enabled } : p)));
  };

  if (loading) return <EmptyState title="加载中…" />;

  return (
    <Box>
      <PageHeader title="设置" subtitle="多模型配置（F10）与无状态部署（F14 / M0）" />

      <Grid container spacing={2}>
        {/* 多模型配置 */}
        <Grid item xs={12} md={7}>
          <Card>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
                <SmartToyIcon color="primary" />
                <Typography variant="h6">多模型配置（F10）</Typography>
              </Stack>
              <Stack spacing={1.5}>
                {profiles.map((p) => (
                  <Paper key={p.profile_id} variant="outlined" sx={{ p: 1.5 }}>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Box sx={{ flexGrow: 1 }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                          {p.name}
                        </Typography>
                        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                          {p.provider} · {p.model}
                        </Typography>
                      </Box>
                      <Chip
                        size="small"
                        label={p.enabled ? '启用' : '停用'}
                        color={p.enabled ? 'success' : 'default'}
                      />
                      <Switch checked={p.enabled} onChange={() => toggleProfile(p.profile_id)} />
                    </Stack>
                  </Paper>
                ))}
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        {/* 无状态部署 */}
        <Grid item xs={12} md={5}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
                <CloudDoneIcon color="secondary" />
                <Typography variant="h6">无状态部署（F14）</Typography>
              </Stack>

              {deploy && (
                <Stack spacing={2}>
                  <Paper variant="outlined" sx={{ p: 1.5 }}>
                    <FormControlLabel
                      control={
                        <Switch
                          checked={deploy.stateless_enabled}
                          onChange={(e) => setDeploy({ ...deploy, stateless_enabled: e.target.checked })}
                        />
                      }
                      label="无状态部署开关"
                    />
                    <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                      将运行态 / HITL 事件 / SSE 队列外置 Redis，支持水平扩展（M0 硬前提）。
                    </Typography>
                  </Paper>

                  <Box>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      外置 Redis 状态
                    </Typography>
                    <Box sx={{ mt: 0.5 }}>
                      <StatusBadge status={deploy.redis_connected ? 'online' : 'offline'} label={deploy.redis_connected ? '已连接' : '未连接'} />
                    </Box>
                  </Box>

                  <Divider />

                  <Box>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      SSE 协议（统一 step_*）
                    </Typography>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                      {deploy.sse_protocol}
                    </Typography>
                  </Box>
                  <Box>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      HITL 协议（统一审批）
                    </Typography>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                      {deploy.hitl_protocol}
                    </Typography>
                  </Box>
                </Stack>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
