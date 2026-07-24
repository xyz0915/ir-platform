import { Box, Chip, Typography } from '@mui/material';
import type { NodeType } from '@/types';
import { NODE_TYPE_LABELS } from '@/types';

const PALETTE: { type: NodeType; color: string }[] = [
  { type: 'trigger', color: '#3B82F6' },
  { type: 'investigate', color: '#60A5FA' },
  { type: 'forensic', color: '#10B981' },
  { type: 'remediate', color: '#F59E0B' },
  { type: 'guardrail', color: '#EF4444' },
  { type: 'hitl', color: '#F97316' },
  { type: 'end', color: '#94A3B8' },
];

export interface NodePaletteProps {
  /** 点击添加（无拖拽时的回退，以及移动端） */
  onAdd: (type: NodeType) => void;
}

/** 节点面板（拖拽源 / 点击添加） */
export function NodePalette({ onAdd }: NodePaletteProps) {
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        节点面板
      </Typography>
      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 1.5 }}>
        拖拽到画布，或点击添加
      </Typography>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {PALETTE.map((item) => (
          <Chip
            key={item.type}
            label={NODE_TYPE_LABELS[item.type]}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData('application/x-node-type', item.type);
              e.dataTransfer.effectAllowed = 'copy';
            }}
            onClick={() => onAdd(item.type)}
            sx={{
              justifyContent: 'flex-start',
              px: 1,
              cursor: 'grab',
              borderLeft: `4px solid ${item.color}`,
              fontWeight: 600,
              '&:active': { cursor: 'grabbing' },
            }}
          />
        ))}
      </Box>
    </Box>
  );
}
