import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import { applyAuthorizationHeader } from '../src/api/authHeader.ts'
import { resolveRouteAccountPrefill } from '../src/utils/accountRoutePrefill.ts'
import { resolveRouteGamePrefill } from '../src/utils/gameRoutePrefill.ts'
import {
  getNoteNoticeTone,
  getNoteStatusText,
  getNoteStatusType,
} from '../src/utils/noteStatus.ts'
import {
  getMenuDenyTarget,
  getVisibleMenus,
  hasMenuAccess,
} from '../src/utils/menuVisibility.ts'
import { APP_MENUS } from '../src/constants/appMenus.ts'

const firstLoad = resolveRouteAccountPrefill('12', {
  consumed: false,
  availableAccountIds: [7, 12, 18],
})
assert.equal(firstLoad.preferredAccountId, 12)
assert.equal(firstLoad.consumed, true)

const consumedAgain = resolveRouteAccountPrefill('12', {
  consumed: true,
  availableAccountIds: [7, 12, 18],
})
assert.equal(consumedAgain.preferredAccountId, null)
assert.equal(consumedAgain.consumed, true)

const invalid = resolveRouteAccountPrefill('abc', {
  consumed: false,
  availableAccountIds: [7, 12, 18],
})
const missing = resolveRouteAccountPrefill('99', {
  consumed: false,
  availableAccountIds: [7, 12, 18],
})
assert.deepEqual(invalid, { preferredAccountId: null, consumed: true })
assert.deepEqual(missing, { preferredAccountId: null, consumed: true })

const emptyOnFirstLoad = resolveRouteAccountPrefill('12', {
  consumed: false,
  availableAccountIds: [],
})
assert.deepEqual(emptyOnFirstLoad, { preferredAccountId: null, consumed: true })

const shouldNotReplayAfterEmptyLoad = resolveRouteAccountPrefill('12', {
  consumed: emptyOnFirstLoad.consumed,
  availableAccountIds: [7, 12, 18],
})
assert.deepEqual(shouldNotReplayAfterEmptyLoad, { preferredAccountId: null, consumed: true })

const firstGameLoad = resolveRouteGamePrefill('starrail', {
  consumed: false,
  availableGames: ['genshin', 'starrail'],
})
assert.deepEqual(firstGameLoad, { preferredGame: 'starrail', consumed: true })

const invalidGame = resolveRouteGamePrefill('zzz', {
  consumed: false,
  availableGames: ['genshin', 'starrail'],
})
assert.deepEqual(invalidGame, { preferredGame: null, consumed: true })

const emptyGameOnFirstLoad = resolveRouteGamePrefill('starrail', {
  consumed: false,
  availableGames: [],
})
assert.deepEqual(emptyGameOnFirstLoad, { preferredGame: null, consumed: true })

const shouldNotReplayGameAfterEmptyLoad = resolveRouteGamePrefill('starrail', {
  consumed: emptyGameOnFirstLoad.consumed,
  availableGames: ['genshin', 'starrail'],
})
assert.deepEqual(shouldNotReplayGameAfterEmptyLoad, { preferredGame: null, consumed: true })

assert.equal(getNoteStatusText('verification_required'), '需验证')
assert.equal(getNoteStatusType('verification_required'), 'warning')
assert.equal(getNoteNoticeTone('verification_required'), 'warning')
assert.equal(getNoteNoticeTone('error'), 'error')
assert.equal(APP_MENUS.some((item) => item.key === 'admin_menu_management'), true)
assert.deepEqual(
  getVisibleMenus(['dashboard', 'settings']).map((item) => item.key),
  ['dashboard', 'settings'],
)
assert.equal(hasMenuAccess('gacha', ['dashboard', 'settings']), false)
assert.equal(hasMenuAccess('gacha', ['dashboard', 'gacha']), true)
assert.equal(getMenuDenyTarget(false), '/')
assert.equal(getMenuDenyTarget(true), '/admin/menus')

const plainHeaderConfig = applyAuthorizationHeader({ headers: {} }, 'plain-token')
assert.equal(plainHeaderConfig.headers.Authorization, 'Bearer plain-token')

let axiosHeaderAuthorization = ''
applyAuthorizationHeader(
  {
    headers: {
      set(name: string, value: string) {
        if (name === 'Authorization') {
          axiosHeaderAuthorization = value
        }
      },
    },
  },
  'axios-token',
)
assert.equal(
  axiosHeaderAuthorization,
  'Bearer axios-token',
  'AxiosHeaders 风格对象应通过 set() 正确写入 Authorization',
)

const healthCenterView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/HealthCenter.vue'),
  'utf8',
)
assert.equal(
  healthCenterView.includes('<el-radio-button label='),
  false,
  'HealthCenter.vue 不应继续使用 el-radio-button 的 label 作为 value',
)

const routerSource = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/router/index.ts'),
  'utf8',
)
assert.equal(
  routerSource.includes('await userStore.ensureUserInfoLoaded()'),
  true,
  '路由守卫应在鉴权判断前恢复用户信息，避免刷新管理员页时被误判',
)
assert.equal(
  routerSource.includes("path: 'admin/menus'"),
  true,
  '路由表应新增管理员菜单管理页面',
)
assert.equal(
  routerSource.includes("menuKey: 'admin_menu_management'"),
  true,
  '路由元信息应包含菜单 key，供菜单守卫统一判断可见性与可访问性',
)
assert.equal(
  routerSource.includes('hasMenuAccess('),
  true,
  '路由守卫应通过统一菜单访问工具判断隐藏菜单的直接访问行为',
)

const settingsView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/Settings.vue'),
  'utf8',
)
assert.equal(
  settingsView.includes('await userStore.ensureUserInfoLoaded()'),
  true,
  'Settings.vue 首屏加载前应等待用户信息恢复，避免管理员信息与表单回填为空',
)

const dashboardView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/Dashboard.vue'),
  'utf8',
)
assert.equal(
  dashboardView.includes('note-notice-warning'),
  true,
  'Dashboard.vue 应为 verification_required 提供 warning 视觉语义，避免继续复用普通错误态样式',
)
assert.equal(
  dashboardView.includes('getNoteNoticeTone(card.status)'),
  true,
  'Dashboard.vue 应通过统一状态工具计算 notice 语义，避免模板内散落状态分支',
)

const layoutView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/Layout.vue'),
  'utf8',
)
assert.equal(
  layoutView.includes('visibleMenus'),
  true,
  'Layout.vue 应改为根据后端下发菜单 key 过滤侧边栏菜单',
)
assert.equal(
  layoutView.includes('APP_MENUS'),
  true,
  'Layout.vue 应复用统一菜单目录，避免侧边栏与路由维护两份菜单定义',
)

const adminMenusView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/AdminMenuManagement.vue'),
  'utf8',
)
assert.equal(
  adminMenusView.includes('隐藏后将同时禁止该用户类型直接访问页面'),
  true,
  '菜单管理页应明确告知隐藏菜单会同时禁用直接访问，避免管理员误解行为语义',
)

console.log('accountRoutePrefill tests passed')
