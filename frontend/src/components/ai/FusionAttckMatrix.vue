<template>
  <div class="fusion-attck-matrix">
    <div class="am-title">
      ATT&amp;CK 融合技术矩阵
      <span class="am-count">{{ techniques.length }} 项 / 命中 {{ hitCount }} 项</span>
    </div>

    <!-- 统一矩阵：始终展示 6 项融合技术点，命中时点亮 -->
    <div class="am-chips">
      <el-tooltip
        v-for="t in techniques"
        :key="t.id"
        :content="t.desc"
        placement="top"
      >
        <el-tag
          :type="hitIds.has(t.id) ? 'danger' : 'info'"
          :effect="hitIds.has(t.id) ? 'dark' : 'plain'"
          class="am-chip"
        >
          <span class="chip-dot" :class="{ hit: hitIds.has(t.id) }" />
          {{ t.id }} · {{ t.name }}
          <span class="chip-tactic">[{{ t.tactic }}]</span>
        </el-tag>
      </el-tooltip>
    </div>

    <div v-if="!hitCount" class="am-empty">暂无 incident 命中技术点</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // incidents: correlate_incident 结果列表，每项含 attck_techniques
  incidents: { type: Array, default: () => [] }
})

// 融合方案关注的 6 项 ATT&CK 技术点目录（设计依据 §3.3 / §5.3）
const techniques = [
  { id: 'T1505.003', name: 'Web Shell', tactic: '持久化', desc: '服务器软件组件：Web Shell（文件型 WebShell）' },
  { id: 'T1609', name: '内存马', tactic: '防御规避', desc: '容器/进程内存驻留内存马（Java Agent / PHP 扩展等）' },
  { id: 'T1055', name: '进程注入', tactic: '防御规避', desc: 'Process Injection（注入到合法进程执行）' },
  { id: 'T1547', name: '持久化', tactic: '持久化', desc: 'Boot or Logon Autostart Execution（自启动持久化）' },
  { id: 'T1059', name: '命令解释器', tactic: '执行', desc: 'Command and Scripting Interpreter（命令行/脚本执行）' },
  { id: 'T1564', name: '隐藏工件', tactic: '防御规避', desc: 'Hide Artifacts（隐藏文件/进程/注册表等）' },
]

// 收集所有 incident 的 attck_techniques（兼容字符串数组 / 对象数组 / attck_technique_map）
const hitIds = computed(() => {
  const ids = new Set()
  for (const inc of props.incidents || []) {
    const techs = inc?.attck_techniques
    if (Array.isArray(techs)) {
      for (const t of techs) {
        if (typeof t === 'string') ids.add(t.trim())
        else if (t && typeof t === 'object' && t.id) ids.add(String(t.id).trim())
      }
    }
    const tmap = inc?.attck_technique_map
    if (tmap && typeof tmap === 'object') {
      for (const k of Object.keys(tmap)) ids.add(String(k).trim())
    }
  }
  return ids
})

const hitCount = computed(() => {
  let n = 0
  for (const t of techniques) {
    if (hitIds.value.has(t.id)) n++
  }
  return n
})
</script>

<style scoped>
.fusion-attck-matrix {
  border: 1px solid var(--el-border-color, #dcdfe6);
  border-radius: 8px;
  padding: 12px 14px;
}
.am-title {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.am-count { font-size: 12px; color: #999; font-weight: 400; }
.am-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.am-chip { font-family: monospace; display: inline-flex; align-items: center; }
.chip-tactic { font-size: 11px; opacity: 0.75; margin-left: 4px; }
.chip-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c0c4cc;
  margin-right: 6px;
}
.chip-dot.hit { background: #fef0f0; box-shadow: 0 0 0 2px #f56c6c; }
.am-empty { margin-top: 10px; font-size: 12px; color: #bbb; }
</style>
