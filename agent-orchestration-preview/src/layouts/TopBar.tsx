import { useMemo, useState } from 'react';
import {
  AppBar,
  Avatar,
  Badge,
  Box,
  IconButton,
  InputAdornment,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Popper,
  TextField,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import MenuIcon from '@mui/icons-material/Menu';
import SearchIcon from '@mui/icons-material/Search';
import GppGoodIcon from '@mui/icons-material/GppGood';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import ExtensionIcon from '@mui/icons-material/Extension';
import { RunStateDot, type RuntimeState } from '@/components/shared/RunStateDot';
import { useAppStore } from '@/store/useAppStore';
import { useHitlStore } from '@/store/useHitlStore';
import { usePipelineStore } from '@/store/usePipelineStore';
import { useAgentStore } from '@/store/useAgentStore';
import { listToolsSync } from '@/mocks/tools';
import { ROLE_LABELS, type Role } from '@/types';

const ROLES: Role[] = ['analyst', 'soc_lead', 'admin'];

interface SearchResult {
  type: string;
  name: string;
  to: string;
}

/** 顶部栏：运行态灯 / 全局搜索 / HITL 角标 / 主题切换 / 角色切换 / 用户菜单 */
export function TopBar() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));
  const navigate = useNavigate();

  const mode = useAppStore((s) => s.mode);
  const toggleMode = useAppStore((s) => s.toggleMode);
  const role = useAppStore((s) => s.role);
  const setRole = useAppStore((s) => s.setRole);
  const setMobileOpen = useAppStore((s) => s.setMobileOpen);

  const pending = useHitlStore((s) => s.tasks.filter((t) => t.status === 'pending').length);
  const pipelineRunning = usePipelineStore((s) => s.isRunning);
  const agents = useAgentStore((s) => s.agents);

  const tools = useMemo(() => listToolsSync(), []);
  const [query, setQuery] = useState('');
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const [userMenu, setUserMenu] = useState<null | HTMLElement>(null);

  const runtime: RuntimeState = pipelineRunning || pending > 0 ? 'degraded' : 'healthy';

  const results = useMemo<SearchResult[]>(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const a = agents
      .filter((x) => x.display_name.toLowerCase().includes(q))
      .map((x) => ({ type: '智能体', name: x.display_name, to: '/agents' }));
    const t = tools
      .filter((x) => x.name.toLowerCase().includes(q))
      .map((x) => ({ type: '工具', name: x.name, to: '/tools' }));
    return [...a, ...t].slice(0, 8);
  }, [query, agents, tools]);

  return (
    <AppBar
      position="sticky"
      color="default"
      sx={{ top: 0, zIndex: (t) => t.zIndex.drawer + 1 }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, px: { xs: 1.5, md: 3 }, height: 64 }}>
        {isMobile && (
          <IconButton onClick={() => setMobileOpen(true)} aria-label="打开菜单">
            <MenuIcon />
          </IconButton>
        )}

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <RunStateDot state={runtime} withLabel={!isMobile} />
          {!isMobile && (
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>
              编排平台
            </Typography>
          )}
        </Box>

        {/* 全局搜索（桌面优先展示） */}
        <Box sx={{ flexGrow: 1, maxWidth: 420, mx: 'auto', position: 'relative' }}>
          <TextField
            size="small"
            fullWidth
            placeholder="搜索智能体 / 工具 / 运行…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setAnchorEl(e.currentTarget);
            }}
            onFocus={(e) => setAnchorEl(e.currentTarget)}
            onBlur={() => setTimeout(() => setAnchorEl(null), 150)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            }}
            sx={{ bgcolor: 'background.default', borderRadius: 2 }}
          />
          <Popper
            open={Boolean(anchorEl) && results.length > 0}
            anchorEl={anchorEl}
            placement="bottom-start"
            style={{ zIndex: 1300, width: anchorEl?.clientWidth }}
          >
            <Box
              sx={{
                mt: 0.5,
                p: 0.5,
                bgcolor: 'background.paper',
                border: '1px solid',
                borderColor: 'divider',
                borderRadius: 2,
                boxShadow: 3,
              }}
            >
              {results.map((r, i) => (
                <ListItemButton
                  key={i}
                  onClick={() => {
                    navigate(r.to);
                    setQuery('');
                    setAnchorEl(null);
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 32 }}>
                    {r.type === '工具' ? <ExtensionIcon fontSize="small" /> : <SmartToyIcon fontSize="small" />}
                  </ListItemIcon>
                  <ListItemText primary={r.name} secondary={r.type} primaryTypographyProps={{ fontSize: 14 }} />
                </ListItemButton>
              ))}
            </Box>
          </Popper>
        </Box>

        {/* 待审 HITL 角标 */}
        <Tooltip title="人工审核台">
          <IconButton onClick={() => navigate('/hitl')} aria-label="待审任务">
            <Badge color="error" badgeContent={pending} max={99}>
              <GppGoodIcon />
            </Badge>
          </IconButton>
        </Tooltip>

        {/* 主题切换 */}
        <Tooltip title={mode === 'dark' ? '切换到亮色' : '切换到暗色'}>
          <IconButton onClick={toggleMode} aria-label="主题切换">
            {mode === 'dark' ? <Brightness7Icon /> : <Brightness4Icon />}
          </IconButton>
        </Tooltip>

        {/* 角色切换器 */}
        <Box sx={{ minWidth: 120 }}>
          <TextField
            select
            size="small"
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            sx={{ '& .MuiSelect-select': { py: 0.75 } }}
            SelectProps={{ native: true }}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </TextField>
        </Box>

        {/* 用户菜单 */}
        <Tooltip title="用户信息">
          <IconButton onClick={(e) => setUserMenu(e.currentTarget)}>
            <Avatar sx={{ width: 32, height: 32, bgcolor: 'primary.main', fontSize: 14 }}>
              {ROLE_LABELS[role].slice(0, 1)}
            </Avatar>
          </IconButton>
        </Tooltip>
        <Menu anchorEl={userMenu} open={Boolean(userMenu)} onClose={() => setUserMenu(null)}>
          <MenuItem disabled>
            <Typography variant="body2">当前角色：{ROLE_LABELS[role]}</Typography>
          </MenuItem>
          {ROLES.map((r) => (
            <MenuItem
              key={r}
              selected={r === role}
              onClick={() => {
                setRole(r);
                setUserMenu(null);
              }}
            >
              {ROLE_LABELS[r]}
            </MenuItem>
          ))}
        </Menu>
      </Box>
    </AppBar>
  );
}
