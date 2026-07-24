import { Box, Typography } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import ErrorIcon from '@mui/icons-material/Error';
import AutorenewIcon from '@mui/icons-material/Autorenew';

export type StepState = 'done' | 'active' | 'todo' | 'error';

export interface StepItem {
  label: string;
  state: StepState;
  hint?: string;
}

export interface StepFlowProps {
  steps: StepItem[];
  direction?: 'row' | 'column';
}

/** 步骤条：3 条关键用户流程可视化（步骤条 + 状态色 + 轻动画） */
export function StepFlow({ steps, direction = 'row' }: StepFlowProps) {
  const colorOf = (s: StepState): string => {
    switch (s) {
      case 'done':
        return 'success.main';
      case 'active':
        return 'primary.main';
      case 'error':
        return 'error.main';
      default:
        return 'text.disabled';
    }
  };

  const iconOf = (s: StepState) => {
    const color = colorOf(s);
    if (s === 'done') return <CheckCircleIcon sx={{ color }} />;
    if (s === 'error') return <ErrorIcon sx={{ color }} />;
    if (s === 'active')
      return <AutorenewIcon sx={{ color, animation: 'spin 1.2s linear infinite' }} />;
    return <RadioButtonUncheckedIcon sx={{ color }} />;
  };

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: direction,
        gap: 0,
        [`@keyframes spin`]: { from: { transform: 'rotate(0)' }, to: { transform: 'rotate(360deg)' } },
      }}
    >
      {steps.map((step, idx) => {
        const last = idx === steps.length - 1;
        const connectorColor = step.state === 'done' ? 'success.main' : 'divider';
        return (
          <Box
            key={idx}
            sx={{
              display: 'flex',
              flexDirection: direction === 'row' ? 'row' : 'column',
              alignItems: direction === 'row' ? 'center' : 'flex-start',
              flex: direction === 'row' ? 1 : undefined,
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {iconOf(step.state)}
              <Box>
                <Typography
                  variant="body2"
                  sx={{ fontWeight: 600, color: step.state === 'todo' ? 'text.disabled' : 'text.primary' }}
                >
                  {step.label}
                </Typography>
                {step.hint && (
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    {step.hint}
                  </Typography>
                )}
              </Box>
            </Box>
            {!last && (
              <Box
                sx={
                  direction === 'row'
                    ? { flex: 1, height: 2, mx: 1.5, backgroundColor: connectorColor, borderRadius: 1 }
                    : { width: 2, height: 20, my: 0.5, ml: '11px', backgroundColor: connectorColor, borderRadius: 1 }
                }
              />
            )}
          </Box>
        );
      })}
    </Box>
  );
}
