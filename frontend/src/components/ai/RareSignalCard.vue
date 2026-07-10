<template>
  <div class="rare-signal-card">
    <div class="rs-header">
      <el-icon class="rs-icon"><WarningFilled /></el-icon>
      <span class="rs-title">稀有高危信号 (强制提级)</span>
      <el-tag type="danger" effect="dark" size="small">{{ rareSignals.length }} 项 P0</el-tag>
    </div>
    <ul class="rs-list">
      <li v-for="(sig, i) in rareSignals" :key="i" class="rs-item">
        <span class="rs-sig">{{ sig.signal }}</span>
        <el-tag size="mini" type="danger" effect="plain">{{ sig.priority }}</el-tag>
        <span class="rs-ev">{{ sig.evidence }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { WarningFilled } from '@element-plus/icons-vue'

defineProps({
  rareSignals: { type: Array, default: () => [] },
})
</script>

<style scoped>
.rare-signal-card { border: 1px solid #f5c2c0; background: #fdecea; border-radius: 8px; padding: 12px 14px; }
.rs-header { display: flex; align-items: center; gap: 8px; }
.rs-icon { color: #c0392b; font-size: 18px; }
.rs-title { font-weight: 700; color: #c0392b; }
.rs-list { list-style: none; padding: 0; margin: 8px 0 0; }
.rs-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; border-top: 1px dashed #f1b0ad; }
.rs-sig { font-family: monospace; font-weight: 600; color: #a5281f; }
.rs-ev { color: #7a3b38; font-size: 12px; }
</style>
