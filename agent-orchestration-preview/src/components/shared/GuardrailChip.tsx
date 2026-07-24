import { Box, Chip } from '@mui/material';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import GppMaybeIcon from '@mui/icons-material/GppMaybe';
import RestoreIcon from '@mui/icons-material/Restore';

export interface GuardrailChipProps {
  whitelist_hit: boolean;
  requires_confirm: boolean;
  requires_rollback_plan: boolean;
  passed: boolean;
}

/** 护栏命中 / 白名单 chip 组 */
export function GuardrailChip({
  whitelist_hit,
  requires_confirm,
  requires_rollback_plan,
  passed,
}: GuardrailChipProps) {
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
      <Chip
        size="small"
        color={passed ? 'success' : 'error'}
        icon={passed ? <VerifiedUserIcon /> : <GppMaybeIcon />}
        label={passed ? '护栏通过' : '护栏拦截'}
      />
      {whitelist_hit && (
        <Chip size="small" variant="outlined" color="secondary" label="白名单命中" />
      )}
      {requires_confirm && (
        <Chip size="small" variant="outlined" color="warning" icon={<GppMaybeIcon />} label="需确认" />
      )}
      {requires_rollback_plan && (
        <Chip size="small" variant="outlined" color="info" icon={<RestoreIcon />} label="需回滚预案" />
      )}
    </Box>
  );
}
