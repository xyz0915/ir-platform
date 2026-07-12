import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getAlerts, getAlertStats } from '@/api/alerts'

export const useAlertStore = defineStore('alert', () => {
  const alerts = ref([])
  const stats = ref({ total: 0, open: 0, critical: 0, today: 0 })
  const unreadCount = ref(0)
  const loading = ref(false)

  const openAlerts = computed(() => alerts.value.filter(a => a.status === 'open'))

  async function fetchAlerts(params = {}) {
    loading.value = true
    try {
      const res = await getAlerts(params)
      alerts.value = res.data || []
    } catch (e) {
      console.error('Fetch alerts failed:', e)
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    try {
      const res = await getAlertStats()
      stats.value = res.data || {}
      unreadCount.value = res.data?.open || 0
    } catch (e) {
      console.error('Fetch alert stats failed:', e)
    }
  }

  function addAlert(alert) {
    alerts.value.unshift(alert)
    if (alert.status === 'open') unreadCount.value++
    stats.value.total++
    stats.value.open++
    if (alert.severity === 'critical') stats.value.critical++
  }

  function updateAlertStatus(alertId, status) {
    const idx = alerts.value.findIndex(a => a.id === alertId)
    if (idx !== -1) {
      const old = alerts.value[idx].status
      alerts.value[idx].status = status
      if (old === 'open' && status !== 'open') unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
  }

  return {
    alerts, stats, unreadCount, loading,
    openAlerts,
    fetchAlerts, fetchStats, addAlert, updateAlertStatus,
  }
})
