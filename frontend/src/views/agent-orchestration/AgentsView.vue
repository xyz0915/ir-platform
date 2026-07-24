<template>
  <!-- M2 容器：包装增强后的 AgentManagementView（含「智能体库」Tab）。
       保持原有 Pipeline Builder / Execution History 可用实现不变。 -->
  <AgentManagementView />
</template>

<script setup>
import AgentManagementView from '@/views/AgentManagementView.vue'
</script>
