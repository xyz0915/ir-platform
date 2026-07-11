<template>
  <div class="knowledge-detail">
    <div class="card-box">
      <div class="flex-between mb-16">
        <h2 class="page-title">知识条目详情</h2>
        <el-button size="small" @click="goBack">
          <el-icon><ArrowLeft /></el-icon> 返回知识库
        </el-button>
      </div>

      <!-- 无法识别的 entryRef（旧数据 / 非预期格式） -->
      <el-alert
        v-if="entryType === 'unknown'"
        type="info"
        :closable="false"
        show-icon
        title="无法识别的证据引用"
        :description="`引用值「${entryRef}」不符合 seed_*/draft_*/rule_* 约定，可能来自旧版本数据。`"
      />

      <!-- 规则引擎命中：无独立知识条目 -->
      <el-card v-else-if="entryType === 'rule'" shadow="never" class="detail-card">
        <el-result icon="info" title="规则引擎命中">
          <template #sub-title>
            <span>该证据来自规则引擎内置规则，没有独立的知识条目详情页。</span>
          </template>
          <template #extra>
            <el-button type="primary" @click="goRules">前往规则库查看</el-button>
          </template>
        </el-result>
      </el-card>

      <!-- 加载中 -->
      <div v-else-if="loading" v-loading="true" class="loading-box" />

      <!-- 空态：草稿被拒绝/撤回 或 种子未找到（含 404） -->
      <el-card v-else-if="notFound" shadow="never" class="detail-card">
        <el-result icon="warning" title="该知识条目已不存在">
          <template #sub-title>
            <span>该知识条目可能已被拒绝 / 撤回，或已不在当前知识库中。</span>
          </template>
          <template #extra>
            <el-button @click="goBack">返回知识库</el-button>
          </template>
        </el-result>
      </el-card>

      <!-- 草稿 / 种子详情 -->
      <el-card v-else shadow="never" class="detail-card">
        <template #header>
          <div class="detail-header">
            <span class="detail-title">{{ detail.title || detail.name || '未命名条目' }}</span>
            <el-tag size="small" :type="entryTypeTag(entryType)">{{ entryTypeLabel(entryType) }}</el-tag>
          </div>
        </template>

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="分类">
            <el-tag size="small" type="info">{{ detail.category || 'auto' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="严重程度">
            <el-tag size="small" :type="severityType(detail.severity)">{{ severityLabel(detail.severity) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.mitre_attack" label="MITRE ATT&CK">
            {{ detail.mitre_attack }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.source" label="来源">
            {{ sourceLabel(detail.source) }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.tactic" label="战术阶段">
            {{ detail.tactic }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.id && entryType === 'seed'" label="MITRE ID">
            {{ detail.id }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="detail-desc">
          <div class="desc-label">描述</div>
          <div class="desc-body">{{ detail.description || '暂无描述' }}</div>
        </div>

        <div v-if="detail.pattern" class="detail-desc">
          <div class="desc-label">检测特征（pattern）</div>
          <div class="desc-body">{{ detail.pattern }}</div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import knowledgeApi from '@/api/knowledge'

const route = useRoute()
const router = useRouter()

const entryRef = computed(() => route.params.entryRef || '')
const parsed = computed(() => parseEntryRef(entryRef.value))
const entryType = computed(() => parsed.value.prefix)

const loading = ref(false)
const notFound = ref(false)
const detail = ref({})

// 与后端 _derive_entry_type / 检索器 entry_ref 约定双写，逻辑一致：
//   seed_{i}_{mitre_id} → 内部定位键 = mitre_id（seedList 按 s.id === internalId）
//   draft_{numeric_id}  → 内部定位键 = numeric_id（调 GET /drafts/{id}）
//   rule_{i}_{name}     → 规则引擎，无独立详情
function parseEntryRef(ref) {
  if (!ref) return { prefix: 'unknown', internalId: '' }
  const [prefix, ...rest] = ref.split('_')
  if (prefix === 'seed') {
    // rest = [i, mitre_id...]；internalId = mitre_id（含 .001 等含点号子技术）
    return { prefix: 'seed', internalId: rest.slice(1).join('_') }
  }
  if (prefix === 'draft') {
    return { prefix: 'draft', internalId: rest.join('_') }
  }
  if (prefix === 'rule') {
    return { prefix: 'rule', internalId: '' }
  }
  return { prefix: 'unknown', internalId: '' }
}

async function loadDetail() {
  loading.value = true
  notFound.value = false
  detail.value = {}
  try {
    if (entryType.value === 'draft') {
      const id = parsed.value.internalId
      const res = await knowledgeApi.getDraftDetail(id)
      const data = res?.data
      if (!data) {
        notFound.value = true
      } else {
        detail.value = data
      }
    } else if (entryType.value === 'seed') {
      const res = await knowledgeApi.getSeeds()
      const seedList = res?.data || []
      const found = seedList.find((s) => s.id === parsed.value.internalId)
      if (!found) {
        notFound.value = true
      } else {
        detail.value = found
      }
    } else if (entryType.value === 'rule') {
      // 规则引擎无需请求
    }
    // unknown 分支：渲染上方 info 提示，不请求
  } catch (e) {
    // 404（草稿被拒绝/撤回）或网络错误 → 渲染友好空态，不抛错不崩溃
    notFound.value = true
  } finally {
    loading.value = false
  }
}

onMounted(loadDetail)

function goBack() {
  router.push('/knowledge')
}

function goRules() {
  router.push('/rules')
}

// ── 标签 / 文案工具函数（与 KnowledgeView 保持一致）──
function severityType(sev) {
  const map = { low: 'info', medium: 'warning', high: 'danger', critical: 'danger' }
  return map[sev] || 'info'
}

function severityLabel(sev) {
  const map = { low: '低', medium: '中', high: '高', critical: '严重' }
  return map[sev] || sev || '中'
}

function sourceLabel(src) {
  const map = { ai_suggest: 'AI 建议', manual: '手动', external: '外部同步' }
  return map[src] || src || 'AI 建议'
}

function entryTypeLabel(type) {
  const map = { seed: '内置种子', draft: 'AI 建议', rule: '规则引擎' }
  return map[type] || '知识库'
}

function entryTypeTag(type) {
  const map = { seed: 'success', draft: 'warning', rule: 'info' }
  return map[type] || 'info'
}
</script>

<style scoped>
.loading-box {
  min-height: 240px;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.detail-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.detail-desc {
  margin-top: 16px;
}

.desc-label {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 6px;
}

.desc-body {
  font-size: 13px;
  color: #303133;
  line-height: 1.7;
  background: #f7f9fc;
  border-radius: 6px;
  padding: 10px 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.mb-16 {
  margin-bottom: 16px;
}
</style>
