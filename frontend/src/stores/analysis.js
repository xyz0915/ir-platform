import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import {
  getEvents,
  getEventStats,
  getEventDetail,
  updateEventStatus,
  batchUpdateStatus,
  assignEvent,
  batchAssign,
  getTimelineData,
  getRelatedEvents,
  getEventHistory,
} from '@/api/events'

export const useAnalysisStore = defineStore('analysis', () => {
  // ── 状态 ──
  const events = ref([])
  const total = ref(0)
  const loading = ref(false)

  const filters = reactive({
    keyword: '',
    timeRange: [null, null],
    eventTypes: [],
    severities: [],
    statuses: [],
    attackStages: [],
    quickTag: '',
  })

  const pagination = reactive({
    page: 1,
    pageSize: 50,
  })

  const sortField = ref('timestamp')
  const sortOrder = ref('desc')
  const selectedEvent = ref(null)
  const selectedEventIds = ref([])
  const timelineData = ref([])
  const detailVisible = ref(false)

  // ── 筛选参数构建 ──
  function buildParams() {
    const params = {
      page: pagination.page,
      page_size: pagination.pageSize,
      sort_field: sortField.value,
      sort_order: sortOrder.value,
    }

    if (filters.keyword) params.keyword = filters.keyword
    if (filters.timeRange[0]) params.start_time = filters.timeRange[0]
    if (filters.timeRange[1]) params.end_time = filters.timeRange[1]
    if (filters.eventTypes.length) params.event_types = filters.eventTypes.join(',')
    if (filters.severities.length) params.severities = filters.severities.join(',')
    if (filters.statuses.length) params.statuses = filters.statuses.join(',')
    if (filters.attackStages.length) params.attack_stages = filters.attackStages.join(',')

    return params
  }

  // ── Action：获取事件列表 ──
  async function fetchEvents() {
    loading.value = true
    try {
      const res = await getEvents(buildParams())
      events.value = res.data.items || []
      total.value = res.data.total || 0
    } catch (e) {
      events.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  // ── Action：获取时间轴数据 ──
  async function fetchTimeline() {
    try {
      const res = await getTimelineData(buildParams())
      timelineData.value = res.data.chains || []
    } catch (e) {
      timelineData.value = []
    }
  }

  // ── Action：获取事件详情 ──
  async function fetchEventDetail(id) {
    try {
      const res = await getEventDetail(id)
      selectedEvent.value = res.data
      detailVisible.value = true
    } catch (e) {
      selectedEvent.value = null
    }
  }

  // ── Action：更新状态 ──
  async function updateStatus(id, status, comment = '') {
    await updateEventStatus(id, { status, comment })
    await fetchEvents()
    if (selectedEvent.value && selectedEvent.value.id === id) {
      await fetchEventDetail(id)
    }
  }

  // ── Action：批量更新状态 ──
  async function batchUpdate(ids, status, comment = '') {
    await batchUpdateStatus({ event_ids: ids, status, comment })
    selectedEventIds.value = []
    await fetchEvents()
  }

  // ── Action：指派 ──
  async function assign(id, assignee) {
    await assignEvent(id, { assignee })
    await fetchEvents()
  }

  // ── Action：批量指派 ──
  async function batchAssignAction(ids, assignee) {
    await batchAssign({ event_ids: ids, assignee })
    selectedEventIds.value = []
    await fetchEvents()
  }

  // ── Action：设置筛选 ──
  function setFilters(newFilters) {
    Object.assign(filters, newFilters)
    pagination.page = 1
  }

  // ── Action：重置筛选 ──
  function resetFilters() {
    filters.keyword = ''
    filters.timeRange = [null, null]
    filters.eventTypes = []
    filters.severities = []
    filters.statuses = []
    filters.attackStages = []
    filters.quickTag = ''
    pagination.page = 1
  }

  return {
    // state
    events,
    total,
    loading,
    filters,
    pagination,
    sortField,
    sortOrder,
    selectedEvent,
    selectedEventIds,
    timelineData,
    detailVisible,
    // actions
    fetchEvents,
    fetchTimeline,
    fetchEventDetail,
    updateStatus,
    batchUpdate,
    assign,
    batchAssignAction,
    setFilters,
    resetFilters,
    buildParams,
  }
})
