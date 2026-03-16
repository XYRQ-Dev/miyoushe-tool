/**
 * Axios HTTP 客户端封装
 * - 自动携带 JWT Token
 * - 401 响应自动跳转登录页
 * - 统一错误处理
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：自动携带 Token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：统一处理错误
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      router.push('/login')
      ElMessage.error('登录已过期，请重新登录')
    } else if (error.response?.data?.detail) {
      ElMessage.error(error.response.data.detail)
    } else {
      ElMessage.error('请求失败，请稍后重试')
    }
    return Promise.reject(error)
  }
)

// ===== 认证 API =====
export const authApi = {
  register: (data: { username: string; password: string }) =>
    api.post('/auth/register', data),
  login: (data: { username: string; password: string }) =>
    api.post('/auth/login', data),
  getMe: () => api.get('/auth/me'),
  updateMe: (data: any) => api.put('/auth/me', data),
  refreshToken: () => api.post('/auth/refresh'),
}

// ===== 账号 API =====
export const accountApi = {
  list: () => api.get('/accounts'),
  startQrLogin: () => api.post('/accounts/qr-login'),
  delete: (id: number) => api.delete(`/accounts/${id}`),
  refreshCookie: (id: number) => api.post(`/accounts/${id}/refresh-cookie`),
}

// ===== 任务 API =====
export const taskApi = {
  getConfig: () => api.get('/tasks/config'),
  updateConfig: (data: { cron_expr: string; is_enabled: boolean }) =>
    api.put('/tasks/config', data),
  execute: () => api.post('/tasks/execute'),
  getStatus: () => api.get('/tasks/status'),
}

// ===== 日志 API =====
export const logApi = {
  list: (params: any) => api.get('/logs', { params }),
  getCalendar: (days: number = 7) => api.get('/logs/calendar', { params: { days } }),
}

// ===== 管理员 API =====
export const adminApi = {
  listUsers: () => api.get('/admin/users'),
  toggleUser: (id: number) => api.put(`/admin/users/${id}/toggle-active`),
  getStats: () => api.get('/admin/stats'),
}

export default api
