<template>
  <div class="remediation-suggestions">
    <div class="rs-title">处置建议</div>
    <div class="rs-list">
      <template v-if="severity === 'critical' || severity === 'high'">
        <div class="rs-item"><span class="rs-num">1.</span><span>立即隔离受感染主机，终止可疑进程，并收集完整的取证数据。</span></div>
        <div class="rs-item"><span class="rs-num">2.</span><span>分析进程创建链，确定感染入口和传播路径。</span></div>
        <div class="rs-item"><span class="rs-num">3.</span><span>对相关文件进行哈希查重（VT 交叉查询），检查同簇主机是否被感染。</span></div>
      </template>
      <template v-else-if="severity === 'medium'">
        <div class="rs-item"><span class="rs-num">1.</span><span>确认进程/网络行为是否为正常业务操作，可查询历史基线。</span></div>
        <div class="rs-item"><span class="rs-num">2.</span><span>清理持久化注册表项，检查启动项完整性。</span></div>
        <div class="rs-item"><span class="rs-num">3.</span><span>对相关主机进行二次扫描，排除横向移动风险。</span></div>
      </template>
      <template v-else>
        <div class="rs-item"><span class="rs-num">1.</span><span>信息性事件，可归档记录，无需立即处置。</span></div>
        <div class="rs-item"><span class="rs-num">2.</span><span>定期复查同类事件，关注趋势变化。</span></div>
      </template>
    </div>
  </div>
</template>

<script setup>
defineProps({
  severity: { type: String, default: 'info' },
})
</script>

<style scoped>
.remediation-suggestions {
  background: var(--color-canvas-default);
  border: 0.5px solid #e5e5e7;
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 12px;
}
.rs-title {
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
  margin-bottom: 8px;
}
.rs-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}
.rs-item {
  display: flex;
  gap: 8px;
  padding: 8px 10px;
  background: #f8f8fa;
  border-radius: 8px;
  line-height: 1.5;
}
.rs-num {
  color: #A32D2D;
  font-weight: 500;
  white-space: nowrap;
}
</style>
