export type AppMenuKey =
  | 'dashboard'
  | 'accounts'
  | 'logs'
  | 'gacha'
  | 'assets'
  | 'health'
  | 'redeem'
  | 'settings'
  | 'admin_users'
  | 'admin_menu_management'

export type AppMenuDefinition = {
  key: AppMenuKey
  label: string
  path: string
  navigable?: boolean
}

export const APP_MENUS: AppMenuDefinition[] = [
  { key: 'dashboard', label: '仪表盘', path: '/' },
  { key: 'accounts', label: '账号管理', path: '/accounts' },
  { key: 'logs', label: '签到日志', path: '/logs' },
  { key: 'gacha', label: '抽卡记录', path: '/gacha' },
  { key: 'assets', label: '角色资产', path: '/assets' },
  { key: 'health', label: '账号健康中心', path: '/health' },
  { key: 'redeem', label: '兑换码中心', path: '/redeem' },
  { key: 'settings', label: '系统设置', path: '/settings' },
  { key: 'admin_users', label: '用户信息列表', path: '/admin/users' },
  { key: 'admin_menu_management', label: '菜单与功能开关', path: '/admin/menus' },
]

export const APP_MENU_MAP = Object.fromEntries(APP_MENUS.map((item) => [item.key, item])) as Record<AppMenuKey, AppMenuDefinition>
