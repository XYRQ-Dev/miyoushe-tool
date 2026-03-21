/**
 * Axios HTTP 客户端封装
 * - 自动携带 JWT Token
 * - 401 响应自动跳转登录页
 * - 统一错误处理
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'
import { applyAuthorizationHeader } from './authHeader'

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
  createSmsLoginCaptcha: (data: { mobile: string; aigis?: string }) =>
    api.post('/accounts/sms-login/captcha', data),
  verifySmsLogin: (data: {
    mobile: string
    captcha: string
    action_type: string
    aigis?: string
  }) => api.post('/accounts/sms-login/verify', data),
  delete: (id: number) => api.delete(`/accounts/${id}`),
  refreshCookie: (id: number) => api.post(`/accounts/${id}/refresh-cookie`),
  checkLoginState: (id: number) => api.post(`/accounts/${id}/refresh-login-state`),
}

// ===== 角色资产总览 API =====
export const assetApi = {
  getOverview: () => api.get('/assets/overview'),
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
}

// ===== 抽卡记录 API =====
export const gachaApi = {
  getAccounts: () => api.get('/gacha/accounts'),
  import: (data: { account_id: number | null; game: string; game_uid: string; import_url: string }) =>
    api.post('/gacha/import', data),
  importFromAccount: (data: { account_id: number; game: string; game_uid: string }) =>
    api.post('/gacha/import-from-account', data),
  // 正式文件交换协议已经切换到 UIGF。
  // 前端继续保留“自定义 records 数组”只会制造第二套私有协议，后续前后端很容易再次漂移。
  importUigf: (data: {
    account_id: number | null
    game: string
    game_uid: string
    source_name?: string
    uigf_json: string | Record<string, any>
  }) => api.post('/gacha/import-uigf', data),
  importJson: (data: {
    account_id: number | null
    game: string
    game_uid: string
    source_name?: string
    uigf_json: string | Record<string, any>
  }) => api.post('/gacha/import-json', data),
  getSummary: (params: { account_id: number; game: string; game_uid: string }) =>
    api.get('/gacha/summary', { params }),
  listRecords: (params: {
    account_id: number
    game: string
    game_uid: string
    pool_type?: string
    page: number
    page_size: number
  }) =>
    api.get('/gacha/records', { params }),
  exportUigf: (params: { account_id: number; game: string; game_uid: string }) =>
    api.get('/gacha/export-uigf', { params }),
  exportJson: (params: { account_id: number; game: string; game_uid: string }) =>
    api.get('/gacha/export', { params }),
  reset: (params: { account_id: number; game: string; game_uid: string }) =>
    api.delete('/gacha/reset', { params }),
}

// ===== 账号健康中心 API =====
export const healthCenterApi = {
  getOverview: () => api.get('/health-center/overview'),
}

// ===== 兑换码中心 API =====
// 这一组接口由后端兑换码中心提供，前端统一在此封装以便不同页面共享流水操作与批次列表
export const redeemApi = {
  listAccounts: () => api.get('/redeem/accounts'),
  execute: (data: { game: string; code: string; account_ids: number[] }) =>
    api.post('/redeem/execute', data),
  listBatches: (params?: Record<string, any>) => api.get('/redeem/batches', { params }),
  getBatch: (id: number) => api.get(`/redeem/batches/${id}`),
}

export default api
