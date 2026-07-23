<template>
  <div class="process-tree-card" v-if="tree && tree.length">
    <div class="pt-title">进程链树</div>

    <!-- 加载状态 -->
    <div class="pt-loading" v-if="loading">加载中…</div>

    <!-- 进程树 -->
    <div class="pt-tree" v-else>
      <div
        v-for="(node, i) in tree"
        :key="node.pid"
        class="pt-node"
        :class="{ 'pt-current': node.pid === currentPid }"
        :style="{ paddingLeft: ((node.depth || 0) * 20 + 8) + 'px' }"
      >
        <svg v-if="i > 0" class="pt-line" width="20" height="28">
          <line x1="0" y1="0" x2="0" y2="14" stroke="#aaa" stroke-width="1.5"/>
          <line x1="0" y1="14" x2="14" y2="14" stroke="#aaa" stroke-width="1.5"/>
        </svg>
        <span class="pt-icon">⚙</span>
        <strong>{{ node.name }}</strong>
        <span class="pt-pid">({{ node.pid }})</span>
        <span class="pt-cmdline" :title="node.cmdline">{{ node.cmdline ? node.cmdline.substring(0, 60) : '' }}</span>
      </div>
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
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 12px;
}
.pt-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 10px;
}
.pt-loading {
  font-size: 12px;
  color: var(--color-fg-light);
  padding: 8px 0;
}
.pt-tree {
  font-size: 12px;
}
.pt-node {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 0;
  white-space: nowrap;
  overflow: hidden;
}
.pt-node.pt-current {
  background: var(--color-accent-subtle, #eff6ff);
  border-radius: 4px;
}
.pt-line {
  flex-shrink: 0;
}
.pt-icon {
  font-size: 13px;
}
.pt-pid {
  color: var(--color-fg-subtle);
  font-size: 11px;
}
.pt-cmdline {
  color: var(--color-fg-light);
  font-size: 11px;
  margin-left: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 400px;
}
</style>
