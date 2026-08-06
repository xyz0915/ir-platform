/** 日志检索 Pinia Store */

import { defineStore } from 'pinia'
import { searchLogs, getTrend } from '@/api/logs'
import request from '@/api/index'
import { quickRangeValue } from '@/utils/time'

export const useLogSearchStore = defineStore('logSearch', {
  state: () => ({
    // 搜索条件
    keyword: '',
    dsl: '',                    // P0-1 字段 DSL（非空时优先于 keyword）
    selectedCaseId: null,
    selectedHostId: null,

    // 筛选条件（P0-2）
    filterEventType: '',
    filterSeverity: '',
    filterAttackStage: '',
    filterSourceCollector: '',
    filterStatus: '',

    // 时间范围（P1-1）：'' | '5m' | '1h' | '24h' | '7d' | 'custom'
    quickRange: '24h',
    startTime: '',
    endTime: '',

    // 搜索范围（P2 统一跨表检索）
    searchScope: 'events',  // events / imports / all

    // 分页
    page: 1,
    pageSize: 20,

    // 案件-主机数据
    casesWithHosts: [],

    // 搜索结果
    items: [],
    total: 0,
    elapsedMs: 0,

    // 趋势数据
    trendData: [],

    // 状态
    loading: false,
    error: null,
  }),

  getters: {
    hasResults: (state) => state.items.length > 0,
    currentCase: (state) => {
      if (!state.selectedCaseId) return null
      return state.casesWithHosts.find(c => c.id === state.selectedCaseId) || null
    },
    currentHost: (state) => {
      for (const c of state.casesWithHosts) {
        const h = (c.hosts || []).find(h => h.id === state.selectedHostId)
        if (h) return h
      }
      return null
    },
  },

  actions: {
    /**
     * 加载案件-主机树形数据
     * 使用已有 API GET /api/cases/with-hosts
     */
    async loadCasesWithHosts() {
      try {
        const res = await request.get('/cases/with-hosts')
        // 兼容 { success, data } 和 { code, data } 两种格式
        const raw = res.success !== undefined ? res.data : (res.data || [])
        this.casesWithHosts = raw.map(c => ({
          ...c,
          id: c.value,  // 兼容：API 返回 value，前端用 c.id
          hosts: (c.children || c.hosts || []).map(h => ({
            ...h,
            id: h.value,  // 兼容：API 返回 value，前端 click host 用 h.id
            hostname: h.label?.split(' ')[0] || h.hostname,
            ip: h.ip || h.ip_address || '',
          })),
        }))
      } catch (err) {
        console.warn('加载案件-主机数据失败:', err)
        // 加载 Mock 数据兜底
        this.casesWithHosts = []
      }
    },

    /**
     * 应用快捷时间范围（P1-1）。
     * @param {string} key '' | '5m' | '1h' | '24h' | '7d' | 'custom'
     */
    applyQuickRange(key) {
      this.quickRange = key
      if (key === 'custom') {
        // 自定义时间保留用户已填值
        return
      }
      if (!key) {
        this.startTime = ''
        this.endTime = ''
        return
      }
      const { start, end } = quickRangeValue(key)
      this.startTime = start
      this.endTime = end
    },

    /**
     * 执行搜索
     */
    async search() {
      this.loading = true
      this.error = null
      try {
        const params = {
          keyword: this.keyword,
          dsl: this.dsl || undefined,
          host_id: this.selectedHostId || undefined,
          case_id: this.selectedCaseId || undefined,
          event_type: this.filterEventType || undefined,
          severity: this.filterSeverity || undefined,
          attack_stage: this.filterAttackStage || undefined,
          source_collector: this.filterSourceCollector || undefined,
          status: this.filterStatus || undefined,
          start_time: this.startTime || undefined,
          end_time: this.endTime || undefined,
          page: this.page,
          page_size: this.pageSize,
        }

        let res
        if (this.searchScope === 'all' || this.searchScope === 'imports') {
          // 统一检索或原始日志检索
          params.scope = this.searchScope
          res = await request.get('/log-search/unified-search', { params })
        } else {
          // 默认：安全事件检索
          res = await searchLogs(params)
        }

        if (res.code === 0 && res.data) {
          this.items = res.data.items || []
          this.total = res.data.total || 0
          this.page = res.data.page || this.page
          this.pageSize = res.data.page_size || this.pageSize
          this.elapsedMs = res.data.elapsed_ms || 0
        } else {
          this.items = []
          this.total = 0
        }
      } catch (err) {
        this.error = err.message || '搜索失败'
        this.items = []
        this.total = 0
      } finally {
        this.loading = false
      }
    },

    /**
     * 加载日志量趋势数据
     */
    async loadTrendData() {
      try {
        const res = await getTrend({ hours: 24 })
        if (res.code === 0 && res.data) {
          this.trendData = res.data
        }
      } catch (err) {
        console.warn('加载趋势数据失败:', err)
        this.trendData = []
      }
    },
  },
})
