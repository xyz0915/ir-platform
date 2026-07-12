<template>
  <div class="incident-panel">
    <!-- 顶部：统一 ATT&CK 矩阵（incident 命中点亮） -->
    <FusionAttckMatrix :incidents="data" class="mb-16" />

    <!-- 空态 -->
    <el-empty
      v-if="!data.length"
      description="暂无融合事件 / 告警"
      :image-size="64"
    />

    <!-- 事件列表 -->
    <div v-else class="incident-list">
      <div
        v-for="inc in data"
        :key="inc.incident_id || (inc.type + (inc.confidence ?? ''))"
        class="incident-card"
        :class="{ 'is-incident': isIncident(inc), 'is-alert': !isIncident(inc) }"
      >
        <!-- 头部 -->
        <div class="ic-header">
          <div class="ic-title">
            <span class="ic-id">#{{ inc.incident_id ?? '-' }}</span>
            <el-tag size="small" :type="isIncident(inc) ? 'danger' : 'warning'">
              {{ isIncident(inc) ? '事件 (incident)' : '单告警 (single_alert)' }}
            </el-tag>
            <el-tag v-if="inc.type" size="small" effect="plain">{{ inc.type }}</el-tag>
            <el-tag :type="severityType(inc.severity)" size="small">
              {{ inc.severity || 'info' }}
            </el-tag>
            <el-tag v-if="inc.needs_review" type="warning" size="small" effect="dark">
              待复核
            </el-tag>
          </div>
          <div class="ic-confidence">
            <span class="conf-label">置信度</span>
            <el-progress
              :percentage="Number(inc.confidence ?? 0)"
              :color="confidenceColor(Number(inc.confidence ?? 0))"
              :stroke-width="14"
              :text-inside="true"
              style="width: 160px"
            />
          </div>
        </div>

        <!-- 攻击路径时序链 -->
        <div v-if="pathSteps(inc).length" class="ic-section">
          <div class="ic-section-title">攻击路径</div>
          <div class="attack-path">
            <template v-for="(step, i) in pathSteps(inc)" :key="i">
              <div class="path-step">
                <span class="step-no">{{ i + 1 }}</span>
                <div class="step-body">
                  <div class="step-label">{{ stepLabel(step) }}</div>
                  <div v-if="stepTechnique(step)" class="step-tech">{{ stepTechnique(step) }}</div>
                </div>
              </div>
              <span v-if="i < pathSteps(inc).length - 1" class="path-arrow">→</span>
            </template>
          </div>
        </div>

        <!-- ATT&CK 技术标签 -->
        <div v-if="techniqueList(inc).length" class="ic-section">
          <div class="ic-section-title">ATT&amp;CK 技术</div>
          <el-tag
            v-for="(t, i) in techniqueList(inc)"
            :key="i"
            type="danger"
            size="small"
            effect="plain"
            class="ic-tag"
          >{{ t }}</el-tag>
        </div>

        <!-- 关联发现 -->
        <div v-if="relatedList(inc).length" class="ic-section">
          <div class="ic-section-title">关联发现</div>
          <el-tag
            v-for="(rf, i) in relatedList(inc)"
            :key="i"
            type="primary"
            size="small"
            class="ic-tag clickable"
            @click="$emit('jump-finding', rf)"
          >{{ relatedLabel(rf) }}</el-tag>
        </div>

        <!-- 信号 -->
        <div v-if="signalList(inc).length" class="ic-section">
          <div class="ic-section-title">信号</div>
          <el-tag
            v-for="(s, i) in signalList(inc)"
            :key="i"
            type="info"
            size="small"
            effect="plain"
            class="ic-tag"
          >{{ s }}</el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import FusionAttckMatrix from './FusionAttckMatrix.vue'

defineEmits(['jump-finding'])

const props = defineProps({
  data: { type: Array, default: () => [] }
})

// 兼容：未提供 kind 时，type 含 incident 视为 incident，否则 single_alert
function isIncident(inc) {
  if (inc?.kind) return inc.kind === 'incident'
  const t = String(inc?.type || '').toLowerCase()
  return t.includes('incident')
}

function pathSteps(inc) {
  const p = inc?.attack_path
  return Array.isArray(p) ? p : []
}

function stepLabel(step) {
  if (typeof step === 'string') return step
  return step?.action || step?.description || step?.label || step?.step || step?.name || JSON.stringify(step)
}

function stepTechnique(step) {
  if (typeof step === 'object' && step) {
    return step?.technique_id || step?.technique || step?.mitre_technique || ''
  }
  return ''
}

function techniqueList(inc) {
  const out = []
  const techs = inc?.attck_techniques
  if (Array.isArray(techs)) {
    for (const t of techs) {
      if (typeof t === 'string') out.push(t)
      else if (t && typeof t === 'object' && t.id) out.push(`${t.id}${t.name ? ' · ' + t.name : ''}`)
    }
  }
  const tmap = inc?.attck_technique_map
  if (tmap && typeof tmap === 'object') {
    for (const [k, v] of Object.entries(tmap)) {
      out.push(`${k}${v ? ' · ' + v : ''}`)
    }
  }
  return out
}

function relatedList(inc) {
  const rf = inc?.related_findings
  return Array.isArray(rf) ? rf : []
}

function relatedLabel(rf) {
  if (typeof rf === 'string') return rf
  return rf?.label || rf?.ref || rf?.id || rf?.type || JSON.stringify(rf)
}

function signalList(inc) {
  const sig = inc?.signals
  if (Array.isArray(sig)) return sig.map(s => (typeof s === 'string' ? s : (s?.name || s?.label || JSON.stringify(s))))
  if (sig && typeof sig === 'object') {
    return Object.entries(sig).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
  }
  return []
}

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
.incident-panel { width: 100%; }
.mb-16 { margin-bottom: 16px; }

.incident-list { display: flex; flex-direction: column; gap: 14px; }

.incident-card {
  border: 1px solid var(--el-border-color, #dcdfe6);
  border-left: 4px solid #e6a23c;
  border-radius: 8px;
  padding: 14px 16px;
  background: var(--el-bg-color, #fff);
}
.incident-card.is-incident { border-left-color: #f56c6c; }
.incident-card.is-alert { border-left-color: #e6a23c; }

.ic-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}
.ic-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ic-id { font-weight: 700; font-family: monospace; color: var(--color-fg-default, #303133); }
.ic-confidence { display: flex; align-items: center; gap: 8px; }
.conf-label { font-size: 12px; color: var(--color-fg-muted, #909399); }

.ic-section { margin-top: 10px; }
.ic-section-title { font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--color-fg-default, #303133); }
.ic-tag { margin: 2px 4px; }
.ic-tag.clickable { cursor: pointer; }

.attack-path { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.path-step {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--color-canvas-subtle, #f5f7fa);
  border: 1px solid var(--color-border-default, #ebeef5);
  border-radius: 6px;
  padding: 4px 8px;
}
.step-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}
.step-label { font-size: 13px; }
.step-tech { font-size: 11px; color: #f56c6c; font-family: monospace; }
.path-arrow { color: #c0c4cc; font-weight: 700; }
</style>
