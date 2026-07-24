import { useState } from 'react';
import {
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Chip,
  Divider,
  Drawer,
  IconButton,
  Paper,
  Snackbar,
  Alert,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import SchemaIcon from '@mui/icons-material/Schema';
import { StepFlow, type StepItem } from '@/components/shared/StepFlow';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { useAgentStore } from '@/store/useAgentStore';
import { listToolsSync } from '@/mocks/tools';
import { listModelProfilesSync } from '@/mocks/settings';

export interface AgentFormProps {
  open: boolean;
  onClose: () => void;
}

/** 新建自定义 Agent 表单（流程①：填写 → 配置工具 → 保存落库） */
export function AgentForm({ open, onClose }: AgentFormProps) {
  const addAgent = useAgentStore((s) => s.addAgent);
  const agents = useAgentStore((s) => s.agents);
  const tools = listToolsSync();
  const profiles = listModelProfilesSync();

  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [dataSources, setDataSources] = useState<string[]>([]);
  const [dependsOn, setDependsOn] = useState<string[]>([]);
  const [modelProfile, setModelProfile] = useState(profiles[0]?.profile_id ?? '');
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [toast, setToast] = useState(false);

  const reset = () => {
    setDisplayName('');
    setDescription('');
    setDataSources([]);
    setDependsOn([]);
    setModelProfile(profiles[0]?.profile_id ?? '');
    setSelectedTools([]);
    setExpandedTool(null);
    setError('');
  };

  const steps: StepItem[] = [
    { label: '填写信息', state: displayName ? 'done' : 'active' },
    { label: '配置工具', state: selectedTools.length ? 'done' : 'todo', hint: `${selectedTools.length} 项已选` },
    { label: '保存落库', state: 'todo' },
  ];

  const toggleTool = (id: string) => {
    setSelectedTools((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]
    );
  };

  const handleSave = () => {
    if (!displayName.trim()) {
      setError('请填写 Agent 名称');
      return;
    }
    addAgent({
      display_name: displayName.trim(),
      description: description.trim() || '（暂无描述）',
      data_sources: dataSources,
      depends_on: dependsOn,
      tools: selectedTools,
      model_profile: modelProfile || profiles[0]?.profile_id || '',
    });
    setToast(true);
    reset();
    onClose();
  };

  return (
    <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ sx: { width: { xs: '100%', sm: 560 } } }}>
      <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', height: '100%' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="h6">新建自定义 Agent</Typography>
          <IconButton onClick={onClose} aria-label="关闭">
            <CloseIcon />
          </IconButton>
        </Box>

        {/* 流程① 步骤条 */}
        <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: 'background.default' }}>
          <StepFlow steps={steps} />
        </Paper>

        <Box sx={{ flexGrow: 1, overflowY: 'auto', pr: 0.5 }}>
          <Stack spacing={2.5}>
            <TextField
              label="Agent 名称"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              fullWidth
              required
              error={Boolean(error)}
              helperText={error || '如「钓鱼事件快处 Agent」'}
            />
            <TextField
              label="描述"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              fullWidth
              multiline
              minRows={2}
            />
            <Autocomplete
              multiple
              freeSolo
              options={['终端日志', '网络流量', '威胁情报', 'SIEM 事件', '身份目录', '样本库']}
              value={dataSources}
              onChange={(_, v) => setDataSources(v as string[])}
              renderTags={(value, getTagProps) =>
                value.map((option, index) => (
                  <Chip variant="outlined" label={option} size="small" {...getTagProps({ index })} key={option} />
                ))
              }
              renderInput={(params) => <TextField {...params} label="数据来源" placeholder="输入后回车添加" />}
            />
            <Autocomplete
              multiple
              options={agents.map((a) => ({ id: a.agent_id, label: a.display_name }))}
              getOptionLabel={(o) => (typeof o === 'string' ? o : o.label)}
              isOptionEqualToValue={(o, v) => o.id === v.id}
              value={agents.filter((a) => dependsOn.includes(a.agent_id)).map((a) => ({ id: a.agent_id, label: a.display_name }))}
              onChange={(_, v) => setDependsOn(v.map((x) => (typeof x === 'string' ? x : x.id)))}
              renderInput={(params) => <TextField {...params} label="依赖（其它 Agent）" />}
            />
            <TextField
              select
              label="模型 Profile"
              value={modelProfile}
              onChange={(e) => setModelProfile(e.target.value)}
              fullWidth
            >
              {profiles.map((p) => (
                <option key={p.profile_id} value={p.profile_id}>
                  {p.name}（{p.provider}）
                </option>
              ))}
            </TextField>

            {/* 工具勾选 + schema 预览 */}
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                从 ToolRegistry 勾选工具（点击展开 schema 预览）
              </Typography>
              <Stack spacing={1}>
                {tools.map((t) => (
                  <Paper key={t.tool_id} variant="outlined" sx={{ p: 1.25 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Checkbox
                        size="small"
                        checked={selectedTools.includes(t.tool_id)}
                        onChange={() => toggleTool(t.tool_id)}
                      />
                      <Box sx={{ flexGrow: 1 }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {t.name}
                        </Typography>
                        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                          {t.category} · 幂等键 {t.idempotency_key}
                        </Typography>
                      </Box>
                      <IconButton
                        size="small"
                        onClick={() => setExpandedTool((prev) => (prev === t.tool_id ? null : t.tool_id))}
                        aria-label="预览 schema"
                      >
                        <SchemaIcon fontSize="small" />
                      </IconButton>
                    </Box>
                    {expandedTool === t.tool_id && (
                      <Box sx={{ mt: 1 }}>
                        <JsonViewer value={t.schema} maxHeight={180} title="JSON Schema" />
                      </Box>
                    )}
                  </Paper>
                ))}
              </Stack>
            </Box>
          </Stack>
        </Box>

        <Divider sx={{ my: 2 }} />
        <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
          <Button onClick={onClose}>取消</Button>
          <Button variant="contained" onClick={handleSave}>
            保存
          </Button>
        </Box>
      </Box>

      <Snackbar
        open={toast}
        autoHideDuration={2500}
        onClose={() => setToast(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity="success" variant="filled">
          自定义 Agent 已创建并加入列表（mock 落库）
        </Alert>
      </Snackbar>
    </Drawer>
  );
}
