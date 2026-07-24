import { Box, Paper } from '@mui/material';
import { useTheme } from '@mui/material';

export interface JsonViewerProps {
  value: unknown;
  maxHeight?: number | string;
  title?: string;
}

/** JSON 预览（等宽字体），用于工具 schema / HITL 上下文展示 */
export function JsonViewer({ value, maxHeight = 320, title }: JsonViewerProps) {
  const theme = useTheme();
  const text =
    typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  return (
    <Paper
      variant="outlined"
      sx={{ bgcolor: 'background.default', overflow: 'auto', maxHeight }}
    >
      {title && (
        <Box sx={{ px: 1.5, py: 0.5, borderBottom: '1px solid', borderColor: 'divider', color: 'text.secondary', fontSize: 12 }}>
          {title}
        </Box>
      )}
      <Box
        component="pre"
        sx={{
          m: 0,
          p: 1.5,
          fontFamily: theme.typography.mono,
          fontSize: 12,
          lineHeight: 1.6,
          color: 'text.primary',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        {text}
      </Box>
    </Paper>
  );
}
