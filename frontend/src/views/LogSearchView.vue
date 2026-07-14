<template>
  <div class="log-search-view">
    <!-- Layer 0: 案件-主机筛选器 -->
    <CaseHostSelector
      v-model="store.selectedHostId"
      :cases="store.casesWithHosts"
      @select-host="onSelectHost"
      @switch-case="onSwitchCase"
    />

    <!-- Layer 1: 高级搜索栏 -->
    <div class="layer-spacing">
      <LogSearchBar
        v-model="store.keyword"
        :total="store.total"
        :elapsed-ms="store.elapsedMs"
        :trend-data="store.trendData"
        :current-case-name="currentCaseName"
        :current-host-name="currentHostName"
        @search="onSearch"
        @quick-filter="onQuickFilter"
      />
    </div>

    <!-- Layer 2: 结果列表 -->
    <div class="layer-spacing">
      <LogResultList
        :items="store.items"
        :total="store.total"
        :page="store.page"
        :page-size="store.pageSize"
        :loading="store.loading"
        @view-detail="showDetail"
        @generate-event="onGenerateEvent"
        @update:page="store.page = $event; fetchData()"
        @update:pageSize="store.pageSize = $event; fetchData()"
      />
    </div>

    <!-- 底部操作栏 -->
    <div class="bottom-bar">
      <div class="bottom-left">
        <el-button size="small" @click="exportResults('json')">导出 JSON</el-button>
        <el-button size="small" @click="exportResults('csv')">导出 CSV</el-button>
      </div>
      <div class="bottom-right">
        <el-button size="small" @click="showSaveDialog = true">保存搜索条件</el-button>
      </div>
    </div>

    <!-- JSON 详情弹窗 -->
    <LogDetailPanel
      v-model="showDetailPanel"
      :record="detailRecord"
    />

    <!-- 保存搜索条件弹窗 -->
    <el-dialog v-model="showSaveDialog" title="保存搜索条件" width="400px">
      <el-form :model="saveForm" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="saveForm.name" placeholder="输入搜索条件名称" />
        </el-form-item>
        <el-form-item label="搜索条件">
          <el-input
            v-model="saveForm.query"
            type="textarea"
            :rows="3"
            disabled
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSaveDialog = false">取消</el-button>
        <el-button type="primary" @click="saveSearchCondition">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useLogSearchStore } from '@/stores/logSearch'
import { exportSearch } from '@/api/logs'
import CaseHostSelector from '@/components/logs/CaseHostSelector.vue'
import LogSearchBar from '@/components/logs/LogSearchBar.vue'
import LogResultList from '@/components/logs/LogResultList.vue'
import LogDetailPanel from '@/components/logs/LogDetailPanel.vue'

const route = useRoute()
const store = useLogSearchStore()

// 详情弹窗
const showDetailPanel = ref(false)
const detailRecord = ref(null)

// 保存搜索条件
const showSaveDialog = ref(false)
const saveForm = ref({ name: '', query: '' })

// 当前选中的案件名/主机名
const currentCaseName = computed(() => {
  const c = store.casesWithHosts.find(c => c.id === store.selectedCaseId)
  return c?.name || c?.case_id || ''
})

const currentHostName = computed(() => {
  for (const c of store.casesWithHosts) {
    const h = (c.hosts || []).find(h => h.id === store.selectedHostId)
    if (h) return h.hostname || ''
  }
  return ''
})

// 初始化
onMounted(async () => {
  // 从 URL 参数初始化
  const caseId = route.query.case_id ? Number(route.query.case_id) : null
  const hostId = route.query.host_id ? Number(route.query.host_id) : null
  const importId = route.query.import_id ? Number(route.query.import_id) : null

  await store.loadCasesWithHosts()

  if (caseId) store.selectedCaseId = caseId
  if (hostId) store.selectedHostId = hostId

  // 默认选中第一个有主机的案件
  if (!store.selectedCaseId && store.casesWithHosts.length > 0) {
    store.selectedCaseId = store.casesWithHosts[0].id
  }

  // 默认选中第一个主机
  if (!store.selectedHostId) {
    const caseData = store.casesWithHosts.find(c => c.id === store.selectedCaseId)
    if (caseData?.hosts?.length > 0) {
      store.selectedHostId = caseData.hosts[0].id
    }
  }

  // 加载趋势数据
  await store.loadTrendData()
  // 自动搜索
  await fetchData()
})

// 监听路由参数变化
watch(() => route.query, (q) => {
  if (q.import_id) {
    // 定位到特定导入记录，打开详情
    const importId = Number(q.import_id)
    const item = store.items.find(i => i.id === importId)
    if (item) {
      showDetailPanel.value = true
      detailRecord.value = item
    }
  }
})

async function fetchData() {
  await store.search()
}

function onSelectHost({ host, caseId }) {
  store.selectedHostId = host.id
  store.selectedCaseId = caseId
  store.page = 1
  fetchData()
}

function onSwitchCase(c) {
  store.selectedCaseId = c.id
  store.selectedHostId = null
  store.page = 1
}

function onSearch(keyword) {
  store.keyword = keyword
  store.page = 1
  fetchData()
}

function onQuickFilter(tag) {
  store.keyword = tag.query || ''
  store.page = 1
  fetchData()
}

function showDetail(item) {
  detailRecord.value = item
  showDetailPanel.value = true
}

async function onGenerateEvent(item) {
  try {
    const { data } = await import('@/api/logs').then(m => m.toEvent(item.id))
    ElMessage.success(`事件已生成: ${data.event_id}`)
    // 刷新当前记录状态
    await fetchData()
    // 跳转分析中心
    window.open(`/analysis-center?event_id=${data.event_id}`, '_blank')
  } catch (err) {
    ElMessage.error('事件生成失败: ' + (err.message || '未知错误'))
  }
}

async function exportResults(format) {
  try {
    const blob = await exportSearch({
      keyword: store.keyword,
      case_id: store.selectedCaseId,
      host_id: store.selectedHostId,
      format,
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `log_export_${Date.now()}.${format}`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (err) {
    ElMessage.error('导出失败')
  }
}

function saveSearchCondition() {
  const saved = JSON.parse(localStorage.getItem('ir_saved_searches') || '[]')
  saved.push({
    name: saveForm.value.name,
    query: store.keyword,
    caseId: store.selectedCaseId,
    hostId: store.selectedHostId,
    savedAt: new Date().toISOString(),
  })
  localStorage.setItem('ir_saved_searches', JSON.stringify(saved))
  showSaveDialog.value = false
  saveForm.value = { name: '', query: '' }
  ElMessage.success('搜索条件已保存')
}
</script>

<style scoped>
.log-search-view {
  padding: 16px;
  max-width: 1200px;
  margin: 0 auto;
}

.layer-spacing {
  margin-top: 12px;
}

.bottom-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  margin-top: 8px;
  border-top: 1px solid var(--color-border-default);
}

.bottom-left,
.bottom-right {
  display: flex;
  gap: 8px;
}
</style>
