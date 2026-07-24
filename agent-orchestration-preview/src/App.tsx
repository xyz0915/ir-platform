import { useMemo } from 'react';
import { CssBaseline, ThemeProvider } from '@mui/material';
import { RouterProvider } from 'react-router-dom';
import { buildTheme } from './theme';
import { router } from './router';
import { useAppStore } from './store/useAppStore';

export function App() {
  const mode = useAppStore((s) => s.mode);
  const theme = useMemo(() => buildTheme(mode), [mode]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <RouterProvider router={router} />
    </ThemeProvider>
  );
}
