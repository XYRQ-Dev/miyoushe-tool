export type AppMenuKey =
  | 'dashboard'
  | 'notes'
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
  // notes 需要进入统一菜单权限体系，保证后台可以按角色关闭实时便笺；
  // 但它本质上是仪表盘内的功能开关而不是独立页面，误当成导航项会让侧边栏出现一个无法单独访问的伪菜单。
  { key: 'notes', label: '实时便笺', path: '/#dashboard-notes', navigable: false },
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
