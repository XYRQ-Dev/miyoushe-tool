import { APP_MENUS, type AppMenuDefinition, type AppMenuKey } from '../constants/appMenus.ts'

export function getVisibleMenus(visibleMenuKeys: string[]): AppMenuDefinition[] {
  const visibleSet = new Set(visibleMenuKeys)
  return APP_MENUS.filter((item) => visibleSet.has(item.key) && item.navigable !== false)
}

export function hasMenuAccess(menuKey: AppMenuKey | string | undefined, visibleMenuKeys: string[]): boolean {
  if (!menuKey) return true
  return visibleMenuKeys.includes(menuKey)
}

export function getMenuDenyTarget(isAdmin: boolean) {
  // 管理员被菜单策略拦截时，必须导回仍然可恢复配置的后台入口；
  // 如果这里和普通用户一样退回首页，一旦管理员把后台菜单全关掉，就失去自助恢复路径。
  return isAdmin ? '/admin/menus' : '/'
}
