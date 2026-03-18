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

// 这里的前端“源码级断言”需要验证行为语义，而不是绑定模板换行、空格或是否抽成 helper。
// 统一使用正则做宽松匹配，避免后续无行为变更的重构把测试误打红。
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

assert.equal(getNoteStatusText('verification_required'), '需验证')
assert.equal(getNoteStatusType('verification_required'), 'warning')
assert.equal(getNoteNoticeTone('verification_required'), 'warning')
assert.equal(getNoteNoticeTone('error'), 'error')
assert.equal(APP_MENUS.some((item) => item.key === 'admin_menu_management'), true)
assert.equal(
  APP_MENUS.some((item) => item.key === 'notes' && item.navigable === false),
  true,
  'APP_MENUS 应纳入 notes 功能开关，并显式标记为非导航项，避免被侧边栏误渲染成独立页面',
)
assert.deepEqual(
  getVisibleMenus(['dashboard', 'settings']).map((item) => item.key),
  ['dashboard', 'settings'],
)
assert.deepEqual(
  getVisibleMenus(['dashboard', 'notes', 'settings']).map((item) => item.key),
  ['dashboard', 'settings'],
  '侧边栏可见菜单应过滤掉 notes 这类仅用于功能开关的非导航项',
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
assertSourceMatches(
  dashboardView,
  /const\s+hasNotesAccess\s*=\s*computed\s*\(\s*\(\s*\)\s*=>\s*hasMenuAccess\s*\(\s*['"]notes['"]\s*,\s*userStore\.visibleMenuKeys\s*\)\s*\)/,
  'Dashboard.vue 应基于菜单权限计算实时便笺功能开关，避免在功能关闭时继续请求便笺接口',
)
assertSourceMatches(
  dashboardView,
  /async\s+function\s+loadData\s*\(\s*\)\s*\{[\s\S]*?if\s*\(\s*hasNotesAccess\.value\s*\)\s*\{[\s\S]*?await\s+loadNotesPanel\s*\(\s*\)\s*[\s\S]*?\}/,
  'Dashboard.vue 的 loadData 应保留 hasNotesAccess 为 true 时调用 loadNotesPanel() 的分支',
)
assertSourceMatches(
  dashboardView,
  /async\s+function\s+loadData\s*\(\s*\)\s*\{[\s\S]*?if\s*\(\s*hasNotesAccess\.value\s*\)\s*\{[\s\S]*?\}\s*else\s*\{[\s\S]*?resetNotesPanelState\s*\(\s*\)\s*[\s\S]*?\}/,
  'Dashboard.vue 的 loadData 应保留与 if (hasNotesAccess.value) 成对的 else 分支，并在未授权时执行 resetNotesPanelState()',
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
assert.equal(
  layoutView.includes('item.navigable !== false'),
  true,
  'Layout.vue 或其依赖逻辑应明确排除非导航功能项，避免 notes 出现在侧边栏',
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
assert.equal(
  adminMenusView.includes('菜单与功能开关'),
  true,
  '管理页文案应升级为菜单与功能开关，明确 notes 属于仪表盘内功能开关而不是独立页面',
)
assertSourceMatches(
  adminMenusView,
  /(?:row\.key\s*===\s*['"]notes['"]|function\s+\w+\s*\(\s*row:\s*AdminMenuItem\s*\)\s*\{[\s\S]*?row\.key\s*===\s*['"]notes['"][\s\S]*?\})/,
  '管理页应显式按 notes 判断实时便笺专属文案，避免未来其它非导航功能项被误标成实时便笺',
)
assertSourceMatches(
  adminMenusView,
  /isNotesMenuItem\s*\(\s*row\s*\)[\s\S]{0,200}实时便笺区块（非独立页面）/,
  '管理页应把实时便笺页面归属文案绑定到 notes 专属识别，而不是泛化到所有非导航项',
)
assertSourceOmits(
  adminMenusView,
  /row\.navigable\s*===\s*false[\s\S]{0,120}实时便笺区块（非独立页面）/,
  '页面归属文案不能再把所有非导航项都映射为实时便笺，否则后续新增功能开关会被错误标注',
)
assertSourceMatches(
  adminMenusView,
  /isNotesMenuItem\s*\(\s*row\s*\)[\s\S]{0,200}关闭后会同时停止首页便笺渲染与数据请求/,
  '管理页应把实时便笺停用说明绑定到 notes 专属识别，而不是依赖模板的具体写法',
)
assertSourceOmits(
  adminMenusView,
  /row\.navigable\s*===\s*false[\s\S]{0,120}关闭后会同时停止首页便笺渲染与数据请求/,
  '实时便笺停用说明不能继续直接绑定 row.navigable === false，否则非 notes 功能开关会继承错误副作用描述',
)

console.log('accountRoutePrefill tests passed')
