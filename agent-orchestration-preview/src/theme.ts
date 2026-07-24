import { createTheme, type ThemeOptions } from '@mui/material/styles';

/** 扩展 Typography：增加等宽字体（trace / 日志使用） */
declare module '@mui/material/styles' {
  interface TypographyVariants {
    mono: string;
  }
  interface TypographyVariantsOptions {
    mono?: string;
  }
}

const FONT_SANS = 'Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif';
const FONT_MONO =
  'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace';

/** 暗色 token（SecOps 默认） */
const darkPalette: ThemeOptions['palette'] = {
  mode: 'dark',
  primary: { main: '#3B82F6' },
  secondary: { main: '#10B981' },
  success: { main: '#22C55E' },
  warning: { main: '#F59E0B' },
  error: { main: '#EF4444' },
  info: { main: '#3B82F6' },
  background: { default: '#0F172A', paper: '#1E293B' },
  divider: '#334155',
  text: { primary: '#E2E8F0', secondary: '#94A3B8' },
};

/** 亮色 token（反向映射） */
const lightPalette: ThemeOptions['palette'] = {
  mode: 'light',
  primary: { main: '#2563EB' },
  secondary: { main: '#059669' },
  success: { main: '#16A34A' },
  warning: { main: '#D97706' },
  error: { main: '#DC2626' },
  info: { main: '#2563EB' },
  background: { default: '#F8FAFC', paper: '#FFFFFF' },
  divider: '#E2E8F0',
  text: { primary: '#0F172A', secondary: '#475569' },
};

export const buildTheme = (mode: 'light' | 'dark') => {
  const options: ThemeOptions = {
    palette: mode === 'dark' ? darkPalette : lightPalette,
    shape: { borderRadius: 8 },
    breakpoints: {
      values: { xs: 0, sm: 768, md: 1280, lg: 1536, xl: 1920 },
    },
    typography: {
      fontFamily: FONT_SANS,
      mono: FONT_MONO,
      h5: { fontWeight: 600 },
      h6: { fontWeight: 600 },
      subtitle1: { fontWeight: 600 },
      button: { textTransform: 'none', fontWeight: 600 },
    },
    components: {
      MuiPaper: {
        styleOverrides: {
          root: { backgroundImage: 'none' },
        },
      },
      MuiCard: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: ({ theme }) => ({
            border: `1px solid ${theme.palette.divider}`,
          }),
        },
      },
      MuiAppBar: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: ({ theme }) => ({
            borderBottom: `1px solid ${theme.palette.divider}`,
            backgroundColor: theme.palette.background.paper,
          }),
        },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: ({ theme }) => ({
            backgroundColor: theme.palette.background.paper,
            borderRight: `1px solid ${theme.palette.divider}`,
          }),
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { fontWeight: 600 },
        },
      },
    },
  };
  return createTheme(options);
};
