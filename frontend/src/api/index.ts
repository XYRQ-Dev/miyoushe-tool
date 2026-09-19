/**
 * Axios HTTP 客户端封装
 * - 自动携带 JWT Token
 * - 401 响应自动跳转登录页
 * - 统一错误处理
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'
import { applyAuthorizationHeader, refreshAuthorizationHeaders } from './authHeader'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：自动携带 Token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    applyAuthorizationHeader(config, token)
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
  register: (data: { username: string; password: string; invite_code?: string }) =>
    api.post('/auth/register', data),
  login: (data: { username: string; password: string }) =>
    api.post('/auth/login', data),
  getRegisterOptions: () => api.get('/auth/register-options'),
  getMe: () => api.get('/auth/me'),
  updateMe: (data: any) => api.put('/auth/me', data),
  refreshToken: () => api.post('/auth/refresh', undefined, {
    headers: refreshAuthorizationHeaders(localStorage.getItem('refresh_token')),
  }),
}

// ===== 账号 API =====
export type QrLoginStartResponse = {
  session_id: string
  credential: string
  expires_in: number
  message: string
}

export type RoleSyncResult = {
  roles_sync_status: 'success' | 'pending'
  roles_count: number | null
}

export type QrLoginSuccessResponse = RoleSyncResult & {
  type: 'success'
  account_id: number
  message: string
}

export type LoginStateResponse = {
  roles_sync_status: 'success' | 'pending' | null
  roles_count: number | null
  account_id: number
  cookie_status: string
  message: string
  last_refresh_status: string | null
  last_refresh_message: string | null
}

export const accountApi = {
  list: () => api.get('/accounts'),
  startQrLogin: () => api.post<QrLoginStartResponse>('/accounts/qr-login'),
  createSmsLoginCaptcha: (data: { mobile: string; aigis?: string }) =>
    api.post('/accounts/sms-login/captcha', data),
  verifySmsLogin: (data: {
    mobile: string
    captcha: string
    action_type: string
    aigis?: string
  }) => api.post('/accounts/sms-login/verify', data),
  delete: (id: number) => api.delete(`/accounts/${id}`),
  refreshCookie: (id: number) => api.post<QrLoginStartResponse>(`/accounts/${id}/refresh-cookie`),
  checkLoginState: (id: number) => api.post<LoginStateResponse>(`/accounts/${id}/refresh-login-state`, undefined, { timeout: 90000 }),
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
  getRewards: (params?: { game?: string; game_role_id?: number | null }) =>
    api.get('/logs/rewards', { params }),
}

// ===== 管理员 API =====
export const adminApi = {
  listUsers: () => api.get('/admin/users'),
  toggleUser: (id: number) => api.put(`/admin/users/${id}/toggle-active`),
  deleteUser: (id: number) => api.delete<{ message: string; deleted: boolean }>(`/admin/users/${id}`),
  getStats: () => api.get('/admin/stats'),
  getMenuVisibility: () => api.get('/admin/menu-visibility'),
  updateMenuVisibility: (data: {
    items: Array<{
      key: string
      user_visible: boolean
      admin_visible: boolean
    }>
  }) => api.put('/admin/menu-visibility', data),
  getEmailSettings: () => api.get('/admin/system-settings/email'),
  updateEmailSettings: (data: {
    smtp_enabled: boolean
    smtp_host: string
    smtp_port: number
    smtp_user: string
    smtp_password?: string
    smtp_use_ssl: boolean
    smtp_sender_name: string
    smtp_sender_email: string
  }) => api.put('/admin/system-settings/email', data),
  getInviteCodeSettings: () => api.get('/admin/system-settings/invite-code'),
  updateInviteCodeSettings: (data: {
    invite_code_enabled: boolean
    invite_code: string
  }) => api.put('/admin/system-settings/invite-code', data),
  broadcastEmail: (data: { subject: string; body: string }) =>
    api.post('/admin/notifications/broadcast-email', data),
}

export default api
