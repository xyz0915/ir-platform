import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import authApi from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('ir_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('ir_user') || 'null'))

  const isAuthenticated = computed(() => !!token.value)

  async function login(username, password) {
    const res = await authApi.login(username, password)
    token.value = res.data.token
    user.value = res.data.user
    localStorage.setItem('ir_token', token.value)
    localStorage.setItem('ir_user', JSON.stringify(user.value))
    return res
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('ir_token')
    localStorage.removeItem('ir_user')
  }

  async function fetchUser() {
    try {
      const res = await authApi.getMe()
      user.value = res.data
      localStorage.setItem('ir_user', JSON.stringify(user.value))
      return res
    } catch (error) {
      logout()
      throw error
    }
  }

  return {
    token,
    user,
    isAuthenticated,
    login,
    logout,
    fetchUser
  }
})
