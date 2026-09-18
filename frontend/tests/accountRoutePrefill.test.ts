import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import { applyAuthorizationHeader } from '../src/api/authHeader.ts'
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

assert.equal(APP_MENUS.some((item) => item.key === 'admin_menu_management'), true)
assert.equal(
  APP_MENUS.some((item) => item.key === 'notes'),
  false,
  '便笺功能已下线，APP_MENUS 不应继续保留 notes 菜单或功能开关键',
)
assert.equal(
  APP_MENUS.some((item) => item.key === 'gacha' || item.key === 'redeem' || item.key === 'assets'),
  false,
  '抽卡记录、兑换码中心与角色资产已下线，APP_MENUS 不应继续保留这些菜单',
)
assert.deepEqual(
  getVisibleMenus(['dashboard', 'settings']).map((item) => item.key),
  ['dashboard', 'settings'],
)
assert.equal(
  APP_MENUS.some((item) => item.key === 'health'),
  false,
  '账号健康中心已下线，APP_MENUS 不应继续保留 health 菜单',
)
assert.equal(hasMenuAccess('accounts', ['dashboard', 'settings']), false)
assert.equal(hasMenuAccess('accounts', ['dashboard', 'accounts']), true)
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

assert.equal(
  fs.existsSync(path.resolve(import.meta.dirname, '../src/views/HealthCenter.vue')),
  false,
  '账号健康中心已下线，不应继续保留 HealthCenter.vue',
)

const accountsView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/Accounts.vue'),
  'utf8',
)
assertSourceOmits(
  accountsView,
  /healthCenterApi|\/health-center\//,
  'Accounts.vue 不应继续请求已下线的健康中心接口',
)
assertSourceOmits(
  accountsView,
  /notes_auth_status|\/gacha|\/redeem|jumpToAsset/,
  'Accounts.vue 不应继续引用已下线的便笺、抽卡记录或兑换码中心',
)

const apiSource = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/api/index.ts'),
  'utf8',
)
assertSourceOmits(
  apiSource,
  /gachaApi|redeemApi|assetApi|\/gacha\/|\/redeem\/|\/assets\/overview/,
  '前端 API 封装不应继续保留抽卡记录、兑换码中心或角色资产接口',
)
assertSourceOmits(
  apiSource,
  /healthCenterApi|\/health-center\//,
  '前端 API 封装不应继续保留已下线的账号健康中心接口',
)
assertSourceMatches(
  apiSource,
  /broadcastEmail:\s*\(data:\s*\{[\s\S]*subject:\s*string[\s\S]*body:\s*string[\s\S]*\}\)\s*=>\s*api\.post\('\/admin\/notifications\/broadcast-email'/,
  'adminApi.broadcastEmail 必须指向管理员群发邮件接口',
)
assertSourceMatches(
  apiSource,
  /getRegisterOptions:\s*\(\s*\)\s*=>\s*api\.get\('\/auth\/register-options'/,
  'authApi.getRegisterOptions 必须指向公开注册探测接口',
)
assertSourceMatches(
  apiSource,
  /getInviteCodeSettings:\s*\(\s*\)\s*=>\s*api\.get\('\/admin\/system-settings\/invite-code'/,
  'adminApi.getInviteCodeSettings 必须指向管理员邀请码配置接口',
)
assertSourceMatches(
  apiSource,
  /updateInviteCodeSettings:\s*\(data:\s*\{[\s\S]*invite_code_enabled:\s*boolean[\s\S]*invite_code:\s*string[\s\S]*\}\)\s*=>\s*api\.put\('\/admin\/system-settings\/invite-code'/,
  'adminApi.updateInviteCodeSettings 必须指向管理员邀请码更新接口',
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
assert.equal(routerSource.includes('HealthCenter'), false, '路由不应继续加载 HealthCenter.vue')
assert.equal(routerSource.includes("menuKey: 'health'"), false, '路由不应继续把 /health 当作独立菜单页')
assertSourceMatches(
  routerSource,
  /path:\s*'health'[\s\S]*redirect:\s*'\/accounts'/,
  '旧的 /health 地址应重定向到账号管理',
)
assert.equal(routerSource.includes("path: 'gacha'"), false, '路由不应继续注册抽卡记录页')
assert.equal(routerSource.includes("path: 'redeem'"), false, '路由不应继续注册兑换码中心页')
assert.equal(routerSource.includes("path: 'assets'"), false, '路由不应继续注册角色资产页')
assert.equal(routerSource.includes('RoleAssets'), false, '路由不应继续加载 RoleAssets.vue')

const settingsView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/Settings.vue'),
  'utf8',
)
assert.equal(
  settingsView.includes('await userStore.ensureUserInfoLoaded()'),
  true,
  'Settings.vue 首屏加载前应等待用户信息恢复，避免管理员信息与表单回填为空',
)
assert.equal(
  settingsView.includes('注册邀请码'),
  true,
  'Settings.vue 需要提供管理员邀请码配置卡片',
)
assertSourceMatches(
  settingsView,
  /adminApi\.updateInviteCodeSettings\(/,
  'Settings.vue 保存邀请码必须走管理员接口，不能只改前端状态',
)

const loginView = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/views/Login.vue'),
  'utf8',
)
assertSourceMatches(
  loginView,
  /authApi\.getRegisterOptions\(/,
  'Login.vue 注册前应探测是否需要邀请码',
)
assertSourceMatches(
  loginView,
  /inviteRequired\.value\s*\?\s*registerForm\.invite_code/,
  'Login.vue 在需要邀请码时应把邀请码传给注册接口',
)

const userStoreSource = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/stores/user.ts'),
  'utf8',
)
assertSourceMatches(
  userStoreSource,
  /async function register\(username: string, password: string, inviteCode\?: string\)/,
  'user store 的 register 需要接收可选邀请码',
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
assertSourceOmits(
  layoutView,
  /gacha\s*:|redeem\s*:|assets\s*:/,
  'Layout.vue 不应继续给已下线的抽卡记录、兑换码中心或角色资产注册图标',
)
assertSourceOmits(
  layoutView,
  /health\s*:/,
  'Layout.vue 不应继续给已下线的账号健康中心注册图标',
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
