/** 日志检索 Pinia Store */

import { defineStore } from 'pinia'
import { searchLogs, searchAdvanced, getTrend } from '@/api/logs'
import request from '@/api/index'

export const useLogSearchStore = defineStore('logSearch', {
  state: () => ({
    // 搜索条件
    keyword: '',
    selectedCaseId: null,
    selectedHostId: null,

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
          hosts: (c.children || c.hosts || []).map(h => ({
            ...h,
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
     * 执行搜索
     */
    async search() {
      this.loading = true
      this.error = null
      try {
        const params = {
          keyword: this.keyword,
          case_id: this.selectedCaseId || undefined,
          host_id: this.selectedHostId || undefined,
          page: this.page,
          page_size: this.pageSize,
        }

        // 判断是否使用高级搜索
        let res
        if (this.keyword && (this.keyword.includes('==') || this.keyword.includes('!=') || this.keyword.includes('~') || this.keyword.includes('contains') || this.keyword.includes(' in '))) {
          res = await searchAdvanced({ query: this.keyword, ...params })
        } else {
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
