<template>
  <!-- 智能体菜单：直接渲染智能体库（不再包装 AgentManagementView，
       避免误渲染「流水线编排」Tab 导致与 /agent-orchestration/pipeline 内容重复）。 -->
  <AgentLibraryPanel />
</template>

<script setup>
import AgentLibraryPanel from '@/components/agents/AgentLibraryPanel.vue'
</script>
