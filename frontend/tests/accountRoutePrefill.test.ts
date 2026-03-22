import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import { applyAuthorizationHeader } from '../src/api/authHeader.ts'
import { resolveRouteAccountPrefill } from '../src/utils/accountRoutePrefill.ts'
import { resolveRouteGamePrefill } from '../src/utils/gameRoutePrefill.ts'
import {
  formatGachaRoleLabel,
  resolveRouteGameUidPrefill,
} from '../src/utils/gameUidRoutePrefill.ts'
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

const firstUidLoad = resolveRouteGameUidPrefill('10001', {
  consumed: false,
  availableGameUids: ['10001', '10002'],
})
assert.deepEqual(firstUidLoad, { preferredGameUid: '10001', consumed: true })

const invalidUid = resolveRouteGameUidPrefill('99999', {
  consumed: false,
  availableGameUids: ['10001', '10002'],
})
assert.deepEqual(invalidUid, { preferredGameUid: null, consumed: true })

const emptyUidOnFirstLoad = resolveRouteGameUidPrefill('10001', {
  consumed: false,
  availableGameUids: [],
})
assert.deepEqual(emptyUidOnFirstLoad, { preferredGameUid: null, consumed: true })

const shouldNotReplayUidAfterEmptyLoad = resolveRouteGameUidPrefill('10001', {
  consumed: emptyUidOnFirstLoad.consumed,
  availableGameUids: ['10001', '10002'],
})
assert.deepEqual(shouldNotReplayUidAfterEmptyLoad, { preferredGameUid: null, consumed: true })

assert.equal(
  formatGachaRoleLabel({ nickname: '荧', game_uid: '10001' }),
  '荧 (10001)',
)
assert.equal(
  formatGachaRoleLabel({ nickname: '', game_uid: '10001' }),
  '10001 (10001)',
)

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
assertSourceMatches(
  healthCenterView,
  /supported_games\.length === 1[\s\S]*query\.game = account\.supported_games\[0\]/,
  'HealthCenter.vue 在拿不到角色 UID 时，至多只能把单游戏账号安全预填到游戏维度',
)
assertSourceMatches(
  healthCenterView,
  /不伪造不存在的角色 UID|不伪造.*game_uid/,
  'HealthCenter.vue 需要用中文维护注释解释为何不能在账号级响应上伪造 game_uid',
)

const gachaApiSource = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/api/index.ts'),
  'utf8',
)
assertSourceMatches(
  gachaApiSource,
  /import:\s*\(data:\s*\{[\s\S]*?game_uid:\s*string[\s\S]*?\}\)\s*=>\s*api\.post\('\/gacha\/import'/,
  'gachaApi.import 必须要求 game_uid',
)
assertSourceMatches(
  gachaApiSource,
  /importFromAccount:\s*\(data:\s*\{[\s\S]*?game_uid:\s*string[\s\S]*?\}\)\s*=>\s*api\.post\('\/gacha\/import-from-account'/,
  'gachaApi.importFromAccount 必须要求 game_uid',
)
assertSourceMatches(
  gachaApiSource,
  /importUigf:\s*\(data:\s*\{[\s\S]*?game_uid:\s*string[\s\S]*?\}\)\s*=>\s*api\.post\('\/gacha\/import-uigf'/,
  'gachaApi.importUigf 必须要求 game_uid',
)
assertSourceMatches(
  gachaApiSource,
  /getSummary:\s*\(params:\s*\{[\s\S]*?game_uid:\s*string[\s\S]*?\}\)\s*=>/,
  'gachaApi.getSummary 必须要求 game_uid',
)
assertSourceMatches(
  gachaApiSource,
  /listRecords:\s*\(params:\s*\{[\s\S]*?game_uid:\s*string[\s\S]*?\}\)\s*=>/,
  'gachaApi.listRecords 必须要求 game_uid',
)
assertSourceMatches(
  gachaApiSource,
  /exportUigf:\s*\(params:\s*\{[\s\S]*?game_uid:\s*string[\s\S]*?\}\)\s*=>/,
  'gachaApi.exportUigf 必须要求 game_uid',
)
assertSourceMatches(
  gachaApiSource,
  /exportJson:\s*\(params:\s*\{[\s\S]*?game_uid:\s*string[\s\S]*?\}\)\s*=>/,
  'gachaApi.exportJson 必须要求 game_uid',
)
assertSourceMatches(
  gachaApiSource,
  /reset:\s*\(params:\s*\{[\s\S]*?game_uid:\s*string[\s\S]*?\}\)\s*=>/,
  'gachaApi.reset 必须要求 game_uid',
)
assertSourceMatches(
  gachaApiSource,
  /broadcastEmail:\s*\(data:\s*\{[\s\S]*subject:\s*string[\s\S]*body:\s*string[\s\S]*\}\)\s*=>\s*api\.post\('\/admin\/notifications\/broadcast-email'/,
  'adminApi.broadcastEmail 必须指向管理员群发邮件接口',
)

const gachaRecordsView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/GachaRecords.vue'),
  'utf8',
)
assert.equal(
  gachaRecordsView.includes("const selectedGameUid = ref('')"),
  true,
  'GachaRecords.vue 需要维护 selectedGameUid 状态',
)
assert.equal(
  gachaRecordsView.includes('const availableRoles = computed(() =>'),
  true,
  'GachaRecords.vue 需要维护当前账号游戏下的 availableRoles',
)
assert.equal(
  gachaRecordsView.includes('const currentRole = computed(() =>'),
  true,
  'GachaRecords.vue 需要维护当前选中角色 currentRole',
)
assert.equal(
  gachaRecordsView.includes('resolveRouteGameUidPrefill(route.query.game_uid'),
  true,
  'GachaRecords.vue 需要消费 query 中的 game_uid 预填',
)
assertSourceMatches(
  gachaRecordsView,
  /query 中显式带入了 game_uid|回退到当前账号游戏下的第一个合法 UID/,
  'GachaRecords.vue 需要用中文维护注释解释 UID 预填与回退的原因、边界和误改风险',
)
assert.equal(
  (gachaRecordsView.match(/game_uid:\s*selectedGameUid\.value/g) || []).length >= 7,
  true,
  'GachaRecords.vue 的所有抽卡请求都必须透传 selectedGameUid',
)

const roleAssetsView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/RoleAssets.vue'),
  'utf8',
)
assertSourceMatches(
  roleAssetsView,
  /query:\s*\{[\s\S]*account_id:\s*String\(accountId\),[\s\S]*game,[\s\S]*game_uid:\s*gameUid/,
  'RoleAssets.vue 跳转到抽卡页时必须透传 role.game_uid',
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

const adminUsersView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/AdminUsers.vue'),
  'utf8',
)
assert.equal(
  adminUsersView.includes('群发通知'),
  true,
  'AdminUsers.vue 需要提供群发通知入口',
)
assertSourceMatches(
  adminUsersView,
  /已绑定邮箱且账号启用的用户|忽略个人邮件通知开关/,
  'AdminUsers.vue 需要明确说明管理员公告的收件规则，避免和个人通知偏好混淆',
)

console.log('accountRoutePrefill tests passed')
