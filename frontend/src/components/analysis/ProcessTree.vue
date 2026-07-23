<template>
  <div class="process-tree-card">
    <div class="pt-title">进程链</div>

    <!-- 加载状态 -->
    <div class="pt-loading" v-if="loading">加载中…</div>

    <!-- 进程树（真实数据） -->
    <div class="pt-tree" v-else-if="tree && tree.length">
      <div
        v-for="(node, i) in tree"
        :key="node.pid || i"
        class="pt-node"
        :class="{ 'pt-current': node.pid === currentPid }"
        :style="{ paddingLeft: ((node.depth || 0) * 16 + 8) + 'px' }"
      >
        <svg v-if="i > 0" class="pt-line" width="16" height="24" viewBox="0 0 16 24">
          <line x1="0" y1="0" x2="0" y2="12" stroke="#d3d1c7" stroke-width="1.5"/>
          <line x1="0" y1="12" x2="12" y2="12" stroke="#d3d1c7" stroke-width="1.5"/>
        </svg>
        <span class="pt-icon">{{ i === 0 ? '┗' : '└' }}</span>
        <strong :class="{ 'pt-highlight': node.pid === currentPid }">{{ node.name }}</strong>
        <span class="pt-pid">(PID {{ node.pid }})</span>
        <span v-if="node.tag" class="pt-tag" :class="'pt-tag-' + node.tag.type">{{ node.tag.text }}</span>
        <span class="pt-cmdline" :title="node.cmdline">{{ node.cmdline ? node.cmdline.substring(0, 60) : '' }}</span>
      </div>
    </div>

    <!-- 进程树（降级：空状态） -->
    <div class="pt-empty" v-else>
      <span>暂无进程链数据</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  tree: { type: Array, default: () => [] },
  currentPid: { type: Number, default: null },
  loading: { type: Boolean, default: false },
})
</script>

<style scoped>
.process-tree-card {
  background: var(--color-canvas-default);
  border: 0.5px solid #e5e5e7;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.pt-title {
  font-size: 13px;
  font-weight: 500;
  color: #1d1d1f;
  margin-bottom: 10px;
}
.pt-loading {
  font-size: 12px;
  color: #888780;
  padding: 8px 0;
}
.pt-tree {
  padding: 12px;
  background: #f8f8fa;
  border-radius: 8px;
  font-family: "SF Mono", "JetBrains Mono", "Cascadia Code", monospace;
  font-size: 11px;
  line-height: 2;
}
.pt-node {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 0;
  white-space: nowrap;
  overflow: hidden;
}
.pt-node.pt-current {
  background: var(--color-accent-subtle, #eff6ff);
  border-radius: 4px;
  padding: 2px 4px;
  margin-left: -4px;
  font-weight: 500;
  color: #1d1d1f;
}
.pt-node-muted {
  color: #b4b2a9;
}
.pt-line {
  flex-shrink: 0;
}
.pt-icon {
  font-size: 12px;
  color: #b4b2a9;
  flex-shrink: 0;
}
.pt-icon-red {
  color: #A32D2D;
}
.pt-icon-warn {
  color: #854F0B;
}
.pt-pid {
  color: #888780;
  font-size: 10px;
}
.pt-highlight {
  color: #1d1d1f;
}
.pt-tag {
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 3px;
  font-family: sans-serif;
}
.pt-tag-danger {
  background: #FCEBEB;
  color: #A32D2D;
}
.pt-node-name {
  font-weight: 500;
}
.pt-name-red {
  color: #A32D2D;
}
.pt-name-warn {
  color: #854F0B;
}
.pt-node-meta {
  color: #b4b2a9;
  font-size: 10px;
  font-family: sans-serif;
}
.pt-cmdline {
  color: #b4b2a9;
  font-size: 10px;
  margin-left: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 400px;
  font-family: sans-serif;
}
.pt-empty {
  padding: 24px;
  text-align: center;
  font-size: 12px;
  color: #b4b2a9;
  background: #f8f8fa;
  border-radius: 8px;
}
</style>
