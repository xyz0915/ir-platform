<template>
  <div class="root-cause-panel" v-loading="loading">
    <el-empty v-if="!loading && !hasResult" description="暂无根因分析结果，请在左侧输入主机并发起分析" />

    <template v-if="result && hasResult">
      <!-- 根节点（第一触发点）-->
      <el-card shadow="never" class="root-card" :class="{ abnormal: rootNode?.is_abnormal }">
        <div class="root-head">
          <el-icon :size="18" class="root-icon"><Flag /></el-icon>
          <span class="root-label">第一触发点（Root Node）</span>
          <el-tag v-if="rootNode?.is_abnormal" type="danger" size="small" effect="dark">异常</el-tag>
        </div>
        <div class="root-body">
          <div class="kv">
            <span class="k">进程</span>
            <span class="v mono">{{ rootNode?.process_name || '—' }}</span>
          </div>
          <div class="kv">
            <span class="k">PID / PPID</span>
            <span class="v mono">{{ rootNode?.pid ?? '—' }} / {{ rootNode?.ppid ?? '—' }}</span>
          </div>
          <div class="kv">
            <span class="k">启动时间</span>
            <span class="v mono">{{ rootNode?.time || '—' }}</span>
          </div>
          <div class="kv" v-if="rootNode?.parent_name">
            <span class="k">父进程</span>
            <span class="v mono">{{ rootNode?.parent_name }}</span>
          </div>
          <div class="kv wide">
            <span class="k">命令行</span>
            <span class="v mono cmd">{{ rootNode?.command_line || '—' }}</span>
          </div>
        </div>
      </el-card>

      <!-- 置信度 + 降级标记 -->
      <div class="meta-row">
        <span class="meta-item">
          置信度：
          <el-progress
            :percentage="Math.round((result.confidence || 0) * 100)"
            :color="confidenceColor(Math.round((result.confidence || 0) * 100))"
            :stroke-width="12"
            :text-inside="true"
            style="width: 140px; display: inline-block; vertical-align: middle"
          />
        </span>
        <el-tag v-if="isDegraded" type="warning" size="small" effect="plain">
          LLM 解释不可用（已降级为结构化链）
        </el-tag>
      </div>

      <!-- 因果链 -->
      <h4 class="section-title">
        因果链（父 → 子，共 {{ (result.causal_chain || []).length }} 个节点）
      </h4>
      <div class="chain" v-if="(result.causal_chain || []).length">
        <div
          v-for="(step, i) in result.causal_chain"
          :key="i"
          class="chain-step"
          :class="{ abnormal: step.is_abnormal }"
          :style="{ marginLeft: Math.min(i, 6) * 18 + 'px' }"
        >
          <div class="step-dot">{{ i + 1 }}</div>
          <div class="step-main">
            <div class="step-line1">
              <span class="proc mono">{{ step.process_name || '(未知)' }}</span>
              <el-tag v-if="step.is_abnormal" type="danger" size="small" effect="dark">异常</el-tag>
              <el-tag v-if="step.severity" :type="severityType(step.severity)" size="small" effect="plain">
                {{ step.severity }}
              </el-tag>
              <span class="pid mono">pid={{ step.pid }} ppid={{ step.ppid }}</span>
            </div>
            <div class="step-line2 mono" v-if="step.command_line">{{ step.command_line }}</div>
            <div class="step-line3" v-if="step.time">
              时间：{{ step.time }}
              <span class="ref" v-if="step.ref">· {{ step.ref }}</span>
            </div>
            <div class="step-line3 attack" v-if="step.attack_path">
              攻击路径：{{ step.attack_path }}
            </div>
          </div>
        </div>
      </div>
      <el-empty v-else description="无进程事件可回溯" :image-size="48" />

      <!-- 自然语言解释 -->
      <h4 class="section-title">根因解释</h4>
      <p class="explanation">{{ explanationText || '（无解释）' }}</p>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Flag } from '@element-plus/icons-vue'

const props = defineProps({
  result: { type: Object, default: () => null },
  loading: { type: Boolean, default: false },
})

const hasResult = computed(() => {
  const r = props.result
  if (!r) return false
  return !!(r.root_node || (r.causal_chain && r.causal_chain.length) || r.summary || r.explanation)
})

const rootNode = computed(() => props.result?.root_node || null)

// 后端返回 explanation（LLM 自然语言解释，降级时回退为结构化 summary）+ degraded 标记
const explanationText = computed(() => props.result?.explanation || props.result?.summary || '')

// 降级判定：后端 degraded=true 表示 LLM 不可用，仅返回结构化因果链
const isDegraded = computed(() => props.result?.degraded === true)

function severityType(severity) {
  const map = { critical: 'danger', high: 'danger', medium: 'warning', low: 'primary', info: 'info' }
  return map[severity] || 'info'
}

function confidenceColor(c) {
  if (c >= 80) return '#F56C6C'
  if (c >= 50) return '#E6A23C'
  if (c >= 20) return '#409EFF'
  return '#67C23A'
}
</script>

<style scoped>
.root-cause-panel { width: 100%; min-height: 200px; }
.root-card {
  border-left: 4px solid #409eff;
  border-radius: 8px;
  margin-bottom: 12px;
}
.root-card.abnormal { border-left-color: #f56c6c; }
.root-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.root-icon { color: #409eff; }
.root-card.abnormal .root-icon { color: #f56c6c; }
.root-label { font-weight: 600; }
.root-body { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; }
.kv { display: flex; gap: 8px; font-size: 13px; }
.kv.wide { grid-column: 1 / -1; }
.k { color: var(--el-text-color-secondary); min-width: 84px; }
.v { color: var(--el-text-color-primary); word-break: break-all; }
.mono { font-family: monospace; }
.cmd { font-size: 12px; color: var(--el-text-color-regular); }

.meta-row { display: flex; align-items: center; gap: 14px; margin: 10px 0; flex-wrap: wrap; }
.meta-item { font-size: 13px; color: var(--el-text-color-regular); }

.section-title { margin: 16px 0 8px; font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); }

.chain { display: flex; flex-direction: column; gap: 8px; }
.chain-step {
  display: flex;
  gap: 10px;
  background: var(--el-fill-color-light, #f5f7fa);
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 8px;
  padding: 8px 10px;
}
.chain-step.abnormal { border-color: #f56c6c; background: #fef0f0; }
.step-dot {
  flex-shrink: 0;
  width: 20px; height: 20px;
  border-radius: 50%;
  background: #409eff; color: #fff;
  font-size: 11px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.chain-step.abnormal .step-dot { background: #f56c6c; }
.step-main { flex: 1; min-width: 0; }
.step-line1 { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.step-line2 { font-size: 12px; color: var(--el-text-color-regular); margin-top: 4px; word-break: break-all; }
.step-line3 { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.step-line3.attack { color: #f56c6c; }
.pid { color: var(--el-text-color-secondary); font-size: 12px; }
.ref { color: #909399; }

.explanation {
  line-height: 1.7;
  color: var(--el-text-color-regular);
  white-space: pre-wrap;
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 8px;
  padding: 10px 12px;
}
</style>
