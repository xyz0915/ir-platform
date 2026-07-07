import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const currentCase = ref(null)
  const loading = ref(false)

  function setCurrentCase(caseData) {
    currentCase.value = caseData
  }

  function setLoading(val) {
    loading.value = val
  }

  return {
    currentCase,
    loading,
    setCurrentCase,
    setLoading
  }
})
