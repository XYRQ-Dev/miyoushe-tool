/**
 * 用户状态管理
 * 管理登录状态、用户信息、深色模式
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../api'

export interface UserInfo {
  id: number
  username: string
  email: string | null
  email_notify: boolean
  notify_on: string
  role: string
  is_active: boolean
}

export const useUserStore = defineStore('user', () => {
  const userInfo = ref<UserInfo | null>(null)
  const darkMode = ref(localStorage.getItem('dark_mode') === 'true')

  const isLoggedIn = computed(() => !!localStorage.getItem('access_token'))
  const isAdmin = computed(() => userInfo.value?.role === 'admin')

  async function login(username: string, password: string) {
    const { data } = await authApi.login({ username, password })
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    await fetchUserInfo()
  }

  async function register(username: string, password: string) {
    await authApi.register({ username, password })
  }

  async function fetchUserInfo() {
    try {
      const { data } = await authApi.getMe()
      userInfo.value = data
    } catch {
      logout()
    }
  }

  function logout() {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    userInfo.value = null
  }

  function toggleDarkMode() {
    darkMode.value = !darkMode.value
    localStorage.setItem('dark_mode', String(darkMode.value))
    if (darkMode.value) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }

  // 初始化深色模式
  if (darkMode.value) {
    document.documentElement.classList.add('dark')
  }

  return {
    userInfo,
    darkMode,
    isLoggedIn,
    isAdmin,
    login,
    register,
    fetchUserInfo,
    logout,
    toggleDarkMode,
  }
})
