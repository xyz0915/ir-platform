<template>
  <div class="cluster-view">
    <!-- 顶部工具条 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-select
          v-model="severityFilter"
          placeholder="全部严重度"
          clearable
          size="default"
          style="width: 160px"
          @change="loadClusters"
        >
          <el-option label="严重 (critical)" value="critical" />
          <el-option label="高危 (high)" value="high" />
          <el-option label="中危 (medium)" value="medium" />
          <el-option label="低危 (low)" value="low" />
        </el-select>
        <el-button :icon="Refresh" @click="loadClusters">刷新</el-button>
      </div>
      <div class="toolbar-right">
        <el-button type="primary" :icon="MagicStick" :loading="reClustering" @click="reCluster">
          重新语义归并
        </el-button>
      </div>
    </div>

    <!-- 簇列表 -->
    <el-card shadow="never" class="list-card">
      <el-table
        :data="clusters"
        v-loading="loading"
        row-key="cluster_id"
        @row-click="openDetail"
        class="cluster-table"
      >
        <el-table-column prop="title" label="归并簇标题" min-width="220">
          <template #default="{ row }">
            <span class="cluster-title">{{ row.title || '(未命名)' }}</span>
            <el-tag size="small" type="success" effect="plain" class="ml-6">
              AI 语义
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="严重度" width="110">
          <template #default="{ row }">
            <el-tag :type="severityType(row.severity)" size="small">{{ row.severity || 'medium' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="置信度" width="160">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.round((row.confidence || 0) * 100)"
              :color="confidenceColor(Math.round((row.confidence || 0) * 100))"
              :stroke-width="12"
              :text-inside="true"
            />
          </template>
        </el-table-column>
        <el-table-column label="主机数" width="90" align="center">
          <template #default="{ row }">{{ (row.host_ids || []).length }}</template>
        </el-table-column>
        <el-table-column label="事件数" width="90" align="center">
          <template #default="{ row }">{{ (row.member_event_ids || []).length }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="生成时间" min-width="170" />
      </el-table>

      <el-empty v-if="!loading && !clusters.length" description="暂无归并簇，点击右上角「重新语义归并」生成" />

      <div class="pager" v-if="total > pageSize">
        <el-pagination
          background
          layout="prev, pager, next, total"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="onPage"
        />
      </div>
    </el-card>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawer" title="归并簇详情" size="46%" :destroy-on-close="true">
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="标题">{{ detail.title }}</el-descriptions-item>
          <el-descriptions-item label="严重度">
            <el-tag :type="severityType(detail.severity)" size="small">{{ detail.severity }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="置信度">
            {{ Math.round((detail.confidence || 0) * 100) }}%
          </el-descriptions-item>
          <el-descriptions-item label="生成时间">{{ detail.created_at }}</el-descriptions-item>
        </el-descriptions>

        <h4 class="section-title">AI 摘要</h4>
        <p class="summary-text">{{ detail.summary || '（无摘要）' }}</p>

        <h4 class="section-title">涉及主机 ({{ (detail.host_ids || []).length }})</h4>
        <div class="tag-wrap">
          <el-tag v-for="h in (detail.host_ids || [])" :key="h" class="tag-item" type="info">
            主机 {{ h }}
          </el-tag>
        </div>

        <h4 class="section-title">成员事件 ({{ (detail.member_event_ids || []).length }})</h4>
        <div class="tag-wrap">
          <el-tag
            v-for="eid in (detail.member_event_ids || [])"
            :key="eid"
            class="tag-item"
            @click="jumpEvent(eid)"
          >
            #{{ eid }}
          </el-tag>
        </div>

        <h4 class="section-title">AI 研判聚合</h4>
        <el-descriptions :column="1" border size="small" v-if="detail.ai_verdict_agg">
          <el-descriptions-item label="标签分布">
            <span v-for="(cnt, label) in (detail.ai_verdict_agg.labels || {})" :key="label">
              <el-tag size="small" class="tag-item">{{ label }}: {{ cnt }}</el-tag>
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="平均置信度">
            {{ Math.round((detail.ai_verdict_agg.avg_confidence || 0) * 100) }}%
          </el-descriptions-item>
          <el-descriptions-item label="攻击类型">
            <span v-for="at in (detail.ai_verdict_agg.attack_types || [])" :key="at">
              <el-tag size="small" type="danger" effect="plain" class="tag-item">{{ at }}</el-tag>
            </span>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { listIncidentClusters, correlateIncidents } from '@/api/incidents'

const router = useRouter()

const loading = ref(false)
const reClustering = ref(false)
const clusters = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const severityFilter = ref('')

const drawer = ref(false)
const detail = ref(null)

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

async function loadClusters() {
  loading.value = true
  try {
    const res = await listIncidentClusters({
      severity: severityFilter.value || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    const payload = res?.data || {}
    clusters.value = payload.items || []
    total.value = payload.total || 0
  } catch (e) {
    clusters.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function reCluster() {
  reClustering.value = true
  try {
    const res = await correlateIncidents({ mode: 'semantic' })
    const payload = res?.data || {}
    const n = payload.total || (payload.clusters || []).length || 0
    ElMessage.success(`语义归并完成，生成 ${n} 个归并簇`)
    page.value = 1
    await loadClusters()
  } catch (e) {
    // 错误已由拦截器提示
  } finally {
    reClustering.value = false
  }
}

function onPage(p) {
  page.value = p
  loadClusters()
}

function openDetail(row) {
  detail.value = row
  drawer.value = true
}

function jumpEvent(eid) {
  router.push(`/analysis-center/event/${eid}`)
}

onMounted(loadClusters)
</script>

<style scoped>
.cluster-view { padding: 16px; }
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.toolbar-left, .toolbar-right { display: flex; gap: 8px; align-items: center; }
.list-card { border-radius: 10px; }
.cluster-table :deep(.el-table__row) { cursor: pointer; }
.cluster-title { font-weight: 600; }
.ml-6 { margin-left: 6px; }
.section-title { margin: 18px 0 8px; font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); }
.summary-text { line-height: 1.7; color: var(--el-text-color-regular); white-space: pre-wrap; }
.tag-wrap { display: flex; flex-wrap: wrap; gap: 6px; }
.tag-item { margin: 2px; cursor: pointer; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
</style>
