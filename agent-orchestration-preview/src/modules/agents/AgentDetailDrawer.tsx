import {
  Box,
  Chip,
  Divider,
  Drawer,
  IconButton,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import type { ReactNode } from 'react';
import CloseIcon from '@mui/icons-material/Close';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { JsonViewer } from '@/components/shared/JsonViewer';
import type { AgentConfig } from '@/types';
import { listToolsSync } from '@/mocks/tools';
import { listModelProfilesSync } from '@/mocks/settings';

export interface AgentDetailDrawerProps {
  agent: AgentConfig | null;
  open: boolean;
  onClose: () => void;
}

/** Agent 详情抽屉 */
export function AgentDetailDrawer({ agent, open, onClose }: AgentDetailDrawerProps) {
  const tools = listToolsSync();
  const profiles = listModelProfilesSync();

  return (
    <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ sx: { width: { xs: '100%', sm: 480 } } }}>
      {agent && (
        <Box sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
            <Typography variant="h6">{agent.display_name}</Typography>
            <IconButton onClick={onClose} aria-label="关闭">
              <CloseIcon />
            </IconButton>
          </Box>

          <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
            <StatusBadge status={agent.kind} label={agent.kind === 'builtin' ? '内置' : '自定义'} />
            <StatusBadge status={agent.status} />
          </Stack>

          <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
            {agent.description}
          </Typography>

          <Divider sx={{ my: 2 }} />

          <DetailRow label="数据来源">
            {agent.data_sources.length ? (
              agent.data_sources.map((d) => (
                <Chip key={d} size="small" variant="outlined" label={d} sx={{ mr: 0.5 }} />
              ))
            ) : (
              <Typography variant="body2" color="text.secondary">—</Typography>
            )}
          </DetailRow>

          <DetailRow label="依赖">
            {agent.depends_on.length ? (
              agent.depends_on.map((d) => (
                <Chip key={d} size="small" color="secondary" variant="outlined" label={d} sx={{ mr: 0.5 }} />
              ))
            ) : (
              <Typography variant="body2" color="text.secondary">无</Typography>
            )}
          </DetailRow>

          <DetailRow label="模型 Profile">
            <Typography variant="body2">
              {profiles.find((p) => p.profile_id === agent.model_profile)?.name ?? agent.model_profile}
            </Typography>
          </DetailRow>

          <Box sx={{ mt: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>关联工具（{agent.tools.length}）</Typography>
            <Stack spacing={1}>
              {agent.tools.map((tid) => {
                const t = tools.find((x) => x.tool_id === tid);
                return (
                  <Paper key={tid} variant="outlined" sx={{ p: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>{t?.name ?? tid}</Typography>
                    {t && (
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                        {t.category} · 超时 {t.timeout_ms}ms · 重试 {t.retries}
                      </Typography>
                    )}
                  </Paper>
                );
              })}
              {agent.tools.length === 0 && (
                <Typography variant="body2" color="text.secondary">未关联工具</Typography>
              )}
            </Stack>
          </Box>

          <Box sx={{ mt: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>原始配置（mock）</Typography>
            <JsonViewer value={agent} maxHeight={260} />
          </Box>
        </Box>
      )}
    </Drawer>
  );
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box sx={{ mb: 1.5 }}>
      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 0.5 }}>
        {label}
      </Typography>
      {children}
    </Box>
  );
}
