import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import {
  getEvents,
  getEventStats,
  getEventFilters,
  getEventDetail,
  updateEventStatus,
  batchUpdateStatus,
  assignEvent,
  batchAssign,
  getTimelineData,
  getRelatedEvents,
  getEventHistory,
  getEventContext,
  getEventHostStats,
  getEventImpact,
  getDispositions,
  addDisposition,
} from '@/api/events'

export const useAnalysisStore = defineStore('analysis', () => {
  // ── 原有状态 ──
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
  const timelineEvents = ref([])
  const detailVisible = ref(false)

  // ── 事件详情增强数据 ──
  const eventContext = ref([])
  const hostStats = ref(null)
  const impactScope = ref(null)
  const dispositions = ref([])
  const contextLoading = ref(false)

  // ── 新增：规则匹配降噪状态 ──
  const items = ref([])
  const elapsedMs = ref(0)

  const ruleFilters = reactive({
    caseId: null,
    hostId: null,
    viewFilter: 'matched',   // all | matched | unmatched
    severity: [],
    eventType: [],
    timeRange: 'all',
    ruleId: null,
    ruleCategory: [],
    confidenceMin: null,
    keyword: '',
    page: 1,
    pageSize: 20,
  })

  const filterMeta = reactive({
    cases: [],
    hosts: [],
    hitRules: [],
    hitRuleCategories: [],
    eventTypeCounts: [],
    severityCounts: [],
  })

  const stats = reactive({
    totalEvents: 0,
    matchedEvents: 0,
    unmatchedEvents: 0,
    distinctRulesHit: 0,
    todayNew: 0,
    todayMatched: 0,
  })

  // ── 原有筛选参数构建 ──
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

  // ── 新增：规则匹配筛选参数构建 ──
  function buildRuleParams() {
    const params = {
      page: ruleFilters.page,
      page_size: ruleFilters.pageSize,
    }
    if (ruleFilters.viewFilter !== 'all') params.filter = ruleFilters.viewFilter
    if (ruleFilters.caseId) params.case_id = ruleFilters.caseId
    if (ruleFilters.hostId) params.host_id = ruleFilters.hostId
    if (ruleFilters.severity.length) params.severity = ruleFilters.severity.join(',')
    if (ruleFilters.eventType.length) params.event_type = ruleFilters.eventType.join(',')
    if (ruleFilters.timeRange !== 'all') params.time_range = ruleFilters.timeRange
    if (ruleFilters.ruleId) params.rule_id = ruleFilters.ruleId
    if (ruleFilters.ruleCategory.length) params.rule_category = ruleFilters.ruleCategory.join(',')
    if (ruleFilters.confidenceMin) params.rule_confidence_min = ruleFilters.confidenceMin
    if (ruleFilters.keyword) params.keyword = ruleFilters.keyword
    return params
  }

  // ── 原有 Action：获取事件列表 ──
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

  // ── 新增：规则匹配事件列表 ──
  async function fetchRuleEvents() {
    loading.value = true
    const startTime = Date.now()
    try {
      const res = await getEvents(buildRuleParams())
      items.value = res.data.items || []
      total.value = res.data.total || 0
      if (res.data.stats) {
        stats.totalEvents = res.data.stats.total || stats.totalEvents
        stats.matchedEvents = res.data.stats.matched || stats.matchedEvents
        stats.unmatchedEvents = res.data.stats.unmatched || stats.unmatchedEvents
        stats.distinctRulesHit = res.data.stats.distinct_rules_hit || stats.distinctRulesHit
      }
    } catch (e) {
      items.value = []
      total.value = 0
    } finally {
      elapsedMs.value = Date.now() - startTime
      loading.value = false
    }
  }

  // ── 新增：获取筛选元数据 ──
  async function fetchFilterMeta() {
    try {
      const params = {}
      if (ruleFilters.caseId) params.case_id = ruleFilters.caseId
      if (ruleFilters.hostId) params.host_id = ruleFilters.hostId
      if (ruleFilters.viewFilter !== 'all') params.filter = ruleFilters.viewFilter
      if (ruleFilters.timeRange !== 'all') params.time_range = ruleFilters.timeRange
      if (ruleFilters.severity.length) params.severity = ruleFilters.severity.join(',')
      if (ruleFilters.eventType.length) params.event_type = ruleFilters.eventType.join(',')
      if (ruleFilters.ruleId) params.rule_id = ruleFilters.ruleId
      if (ruleFilters.ruleCategory.length) params.rule_category = ruleFilters.ruleCategory.join(',')
      if (ruleFilters.confidenceMin) params.rule_confidence_min = ruleFilters.confidenceMin
      if (ruleFilters.keyword) params.keyword = ruleFilters.keyword
      const res = await getEventFilters(params)
      const d = res.data
      filterMeta.cases = d.cases || []
      filterMeta.hosts = d.hosts || []
      filterMeta.hitRules = d.hit_rules || []
      filterMeta.hitRuleCategories = d.hit_rule_categories || []
      filterMeta.eventTypeCounts = d.event_type_counts || []
      filterMeta.severityCounts = d.severity_counts || []
    } catch (e) {
      // ignore
    }
  }

  // ── 新增：获取统计卡片 ──
  async function fetchStats() {
    try {
      const params = {}
      if (ruleFilters.caseId) params.case_id = ruleFilters.caseId
      if (ruleFilters.hostId) params.host_id = ruleFilters.hostId
      if (ruleFilters.viewFilter !== 'all') params.filter = ruleFilters.viewFilter
      const res = await getEventStats(params)
      const d = res.data
      stats.totalEvents = d.total_events || 0
      stats.matchedEvents = d.matched_events || 0
      stats.unmatchedEvents = d.unmatched_events || 0
      stats.distinctRulesHit = d.distinct_rules_hit || 0
      stats.todayNew = d.today_new || 0
      stats.todayMatched = d.today_matched || 0
    } catch (e) {
      // ignore
    }
  }

  // ── 新增：设置单个筛选 ──
  function setFilter(key, value) {
    ruleFilters[key] = value
    if (key !== 'page' && key !== 'pageSize') {
      ruleFilters.page = 1
    }
    fetchRuleEvents()
    fetchFilterMeta()
    fetchStats()
  }

  // ── 新增：重置全部筛选 ──
  function resetRuleFilters() {
    ruleFilters.caseId = null
    ruleFilters.hostId = null
    ruleFilters.viewFilter = 'matched'
    ruleFilters.severity = []
    ruleFilters.eventType = []
    ruleFilters.timeRange = 'all'
    ruleFilters.ruleId = null
    ruleFilters.ruleCategory = []
    ruleFilters.confidenceMin = null
    ruleFilters.keyword = ''
    ruleFilters.page = 1
    ruleFilters.pageSize = 20
    fetchRuleEvents()
  }

  // ── 原有 Action：获取时间轴数据 ──
  async function fetchTimeline() {
    try {
      const res = await getTimelineData(buildParams())
      timelineData.value = res.data.chains || []
      timelineEvents.value = res.data.events || []
    } catch (e) {
      timelineData.value = []
      timelineEvents.value = []
    }
  }

  // ── 原有 Action：获取事件详情 ──
  async function fetchEventDetail(id) {
    if (!id) return
    try {
      const res = await getEventDetail(id)
      selectedEvent.value = res.data
      detailVisible.value = true
    } catch (e) {
      selectedEvent.value = null
    }
  }

  // ── 新增：获取事件详情增强数据 ──
  async function fetchEventDetailEnhanced(eventId) {
    contextLoading.value = true
    try {
      const results = await Promise.allSettled([
        getEventContext(eventId),
        getEventHostStats(eventId),
        getEventImpact(eventId),
        getDispositions(eventId),
      ])
      if (results[0].status === 'fulfilled') eventContext.value = results[0].value.data || []
      if (results[1].status === 'fulfilled') hostStats.value = results[1].value.data || null
      if (results[2].status === 'fulfilled') impactScope.value = results[2].value.data || null
      if (results[3].status === 'fulfilled') dispositions.value = results[3].value.data?.items || []
    } finally {
      contextLoading.value = false
    }
  }

  // ── 新增：添加处置记录 ──
  async function addDispositionForEvent(eventId, data) {
    const res = await addDisposition(eventId, data)
    if (res.code === 0) {
      const r = await getDispositions(eventId)
      dispositions.value = r.data?.items || []
    }
    return res
  }

  // ── 原有 Action：更新状态 ──
  async function updateStatus(id, status, comment = '') {
    await updateEventStatus(id, { status, comment })
    await fetchEvents()
    if (selectedEvent.value && selectedEvent.value.id === id) {
      await fetchEventDetail(id)
    }
  }

  // ── 原有 Action：批量更新状态 ──
  async function batchUpdate(ids, status, comment = '') {
    await batchUpdateStatus({ event_ids: ids, status, comment })
    selectedEventIds.value = []
    await fetchEvents()
  }

  // ── 原有 Action：指派 ──
  async function assign(id, assignee) {
    await assignEvent(id, { assignee })
    await fetchEvents()
  }

  // ── 原有 Action：批量指派 ──
  async function batchAssignAction(ids, assignee) {
    await batchAssign({ event_ids: ids, assignee })
    selectedEventIds.value = []
    await fetchEvents()
  }

  // ── 原有 Action：设置筛选 ──
  function setFilters(newFilters) {
    Object.assign(filters, newFilters)
    pagination.page = 1
  }

  // ── 原有 Action：重置筛选 ──
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
    // state — 原有
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
    timelineEvents,
    detailVisible,
    // state — 新增规则匹配
    items,
    elapsedMs,
    ruleFilters,
    filterMeta,
    stats,
    // state — 事件详情增强
    eventContext,
    hostStats,
    impactScope,
    dispositions,
    contextLoading,
    // actions — 原有
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
    // actions — 新增规则匹配
    fetchRuleEvents,
    fetchFilterMeta,
    fetchStats,
    setFilter,
    resetRuleFilters,
    buildRuleParams,
    // actions — 事件详情增强
    fetchEventDetailEnhanced,
    addDispositionForEvent,
  }
})
