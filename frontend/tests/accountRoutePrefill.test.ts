import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import { applyAuthorizationHeader } from '../src/api/authHeader.ts'
import { resolveRouteAccountPrefill } from '../src/utils/accountRoutePrefill.ts'
import { resolveRouteGamePrefill } from '../src/utils/gameRoutePrefill.ts'
import {
  getMenuDenyTarget,
  getVisibleMenus,
  hasMenuAccess,
} from '../src/utils/menuVisibility.ts'
import { APP_MENUS } from '../src/constants/appMenus.ts'

function assertSourceMatches(source: string, pattern: RegExp, message: string) {
  assert.match(source, pattern, message)
}

function assertSourceOmits(source: string, pattern: RegExp, message: string) {
  assert.doesNotMatch(source, pattern, message)
}

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

assert.equal(APP_MENUS.some((item) => item.key === 'admin_menu_management'), true)
assert.equal(
  APP_MENUS.some((item) => item.key === 'notes'),
  false,
  '便笺功能已下线，APP_MENUS 不应继续保留 notes 菜单或功能开关键',
)
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
assert.equal(axiosHeaderAuthorization, 'Bearer axios-token')

const healthCenterView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/HealthCenter.vue'),
  'utf8',
)
assert.equal(
  healthCenterView.includes('<el-radio-button label='),
  false,
  'HealthCenter.vue 不应继续使用 el-radio-button 的 label 作为 value',
)
assert.equal(
  healthCenterView.includes('notes_auth_status'),
  false,
  'HealthCenter.vue 不应继续渲染已下线的便笺状态字段',
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
assert.equal(routerSource.includes("path: 'admin/menus'"), true)
assert.equal(routerSource.includes("menuKey: 'admin_menu_management'"), true)
assert.equal(routerSource.includes('hasMenuAccess('), true)

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
assertSourceOmits(
  dashboardView,
  /notesApi|hasNotesAccess|实时便笺|noteCards|loadNotesPanel/,
  'Dashboard.vue 不应继续保留任何实时便笺请求、状态或展示逻辑',
)
assertSourceMatches(
  dashboardView,
  /async\s+function\s+loadData\s*\(\s*\)\s*\{[\s\S]*?loadDashboardSummary\s*\(\s*\)/,
  'Dashboard.vue 的 loadData 应继续负责拉取签到仪表盘摘要',
)

const layoutView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/Layout.vue'),
  'utf8',
)
assert.equal(layoutView.includes('visibleMenus'), true)
assert.equal(layoutView.includes('APP_MENUS'), true)
assertSourceOmits(
  layoutView,
  /notes\s*:/,
  'Layout.vue 不应继续给已下线的 notes 注册图标或菜单映射',
)

const adminMenusView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/AdminMenuManagement.vue'),
  'utf8',
)
assert.equal(
  adminMenusView.includes('隐藏后将同时禁止该用户类型直接访问页面'),
  true,
)
assertSourceOmits(
  adminMenusView,
  /isNotesMenuItem|实时便笺区块|首页便笺渲染与数据请求/,
  '管理页不应继续保留 notes 专属文案或判定分支',
)

console.log('accountRoutePrefill tests passed')
