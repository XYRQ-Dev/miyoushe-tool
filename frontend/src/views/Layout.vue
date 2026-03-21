<template>
  <div class="shell-layout">
    <aside v-if="!isMobileViewport" :class="['shell-sidebar', { 'shell-sidebar-collapsed': isSidebarCollapsed }]">
      <div class="brand-block">
        <div class="brand-mark">
          <el-icon :size="isSidebarCollapsed ? 22 : 20"><Star /></el-icon>
        </div>
        <div v-if="!isSidebarCollapsed" class="brand-copy">
          <div class="brand-name">MiHaYou Tool</div>
          <div class="brand-subtitle">签到与账号管理</div>
        </div>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="isSidebarCollapsed"
        router
        class="sidebar-menu"
        background-color="transparent"
        text-color="rgba(231, 240, 251, 0.72)"
        active-text-color="#f8fbff"
      >
        <el-menu-item v-for="menu in visibleMenus" :key="menu.key" :index="menu.path">
          <el-icon><component :is="menuIconMap[menu.key]" /></el-icon>
          <template #title>{{ menu.label }}</template>
        </el-menu-item>
      </el-menu>

      <div v-if="!isCompactLayout" class="sidebar-footer">
        <el-button
          :icon="isCollapse ? Expand : Fold"
          class="sidebar-toggle"
          text
          @click="isCollapse = !isCollapse"
        >
          <span v-if="!isCollapse">收起导航</span>
        </el-button>
      </div>
    </aside>

    <el-drawer
      v-model="mobileDrawerVisible"
      direction="ltr"
      :with-header="false"
      size="260px"
      class="mobile-drawer-sidebar"
    >
      <div class="shell-sidebar shell-sidebar-mobile">
        <div class="brand-block">
          <div class="brand-mark">
            <el-icon :size="20"><Star /></el-icon>
          </div>
          <div class="brand-copy">
            <div class="brand-name">MiHaYou Tool</div>
            <div class="brand-subtitle">签到与账号管理</div>
          </div>
        </div>

        <el-menu
          :default-active="activeMenu"
          router
          class="sidebar-menu"
          background-color="transparent"
          text-color="rgba(231, 240, 251, 0.72)"
          active-text-color="#f8fbff"
          @select="mobileDrawerVisible = false"
        >
          <el-menu-item v-for="menu in visibleMenus" :key="menu.key" :index="menu.path">
            <el-icon><component :is="menuIconMap[menu.key]" /></el-icon>
            <template #title>{{ menu.label }}</template>
          </el-menu-item>
        </el-menu>
      </div>
    </el-drawer>

    <div class="shell-main">
      <header class="shell-topbar">
        <div class="topbar-copy">
          <el-button
            v-if="isMobileViewport"
            :icon="Expand"
            circle
            class="topbar-icon-button hamburger-btn"
            @click="mobileDrawerVisible = true"
          />
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="topbar-actions">
          <el-button
            :icon="userStore.darkMode ? Sunny : Moon"
            circle
            class="topbar-icon-button"
            @click="userStore.toggleDarkMode()"
          />
          <el-dropdown trigger="click">
            <button type="button" class="user-entry">
              <el-avatar :size="34" class="user-avatar">
                {{ userStore.userInfo?.username?.charAt(0)?.toUpperCase() }}
              </el-avatar>
              <div class="user-copy">
                <span class="user-name">{{ userStore.userInfo?.username }}</span>
                <span class="user-role">{{ userStore.isAdmin ? '管理员' : '普通用户' }}</span>
              </div>
              <el-icon class="user-arrow"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="settingsVisible" @click="router.push('/settings')">
                  <el-icon><Setting /></el-icon>系统设置
                </el-dropdown-item>
                <el-dropdown-item divided @click="handleLogout">
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="shell-content">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  Star, Odometer, User, UserFilled, Document, Setting, Collection,
  Expand, Fold, ArrowDown, SwitchButton, Sunny, Moon, Ticket, Warning,
} from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'
import { APP_MENUS, type AppMenuKey } from '../constants/appMenus'
import { getVisibleMenus, hasMenuAccess } from '../utils/menuVisibility'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const isCollapse = ref(false)
const isTabletViewport = ref(false)
const isMobileViewport = ref(false)
const mobileDrawerVisible = ref(false)

const menuIconMap: Record<AppMenuKey, unknown> = {
  dashboard: Odometer,
  accounts: User,
  logs: Document,
  gacha: Collection,
  assets: Collection,
  health: Warning,
  redeem: Ticket,
  settings: Setting,
  admin_users: UserFilled,
  admin_menu_management: Setting,
}

const activeMenu = computed(() => route.path)
const visibleMenus = computed(() => getVisibleMenus(userStore.visibleMenuKeys).filter((item) => item.navigable !== false))
const settingsVisible = computed(() => hasMenuAccess('settings', userStore.visibleMenuKeys))
const isCompactLayout = computed(() => isTabletViewport.value || isMobileViewport.value)
const isSidebarCollapsed = computed(() => {
  // 平板断点需要强制进入菜单折叠态，否则 CSS 已经把侧栏压窄，el-menu 仍按展开态排版，
  // 会出现文案被裁切但交互仍视为“展开”的错位状态。
  // 移动端改为独立堆叠布局，必须显式忽略桌面遗留的手动折叠状态；否则用户若先在桌面收起导航，
  // 再切到手机宽度，就会看到菜单仍处于折叠态且当前断点下没有按钮可恢复展开。
  if (isMobileViewport.value) return false
  if (isTabletViewport.value) return true
  return isCollapse.value
})

const pageTitle = computed(() => {
  const matchedMenu = APP_MENUS.find((item) => item.path === route.path)
  return matchedMenu?.label || '米游社工具台'
})

function handleLogout() {
  userStore.logout()
  router.push('/login')
}

function syncViewportState() {
  const width = window.innerWidth
  isMobileViewport.value = width <= 768
  isTabletViewport.value = width > 768 && width <= 1080
}

onMounted(() => {
  userStore.ensureUserInfoLoaded()
  syncViewportState()
  window.addEventListener('resize', syncViewportState)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncViewportState)
})
</script>

<style scoped>
.shell-layout {
  min-height: 100vh;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
}

.shell-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  width: 252px;
  padding: 18px 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  background: var(--bg-sidebar);
  box-shadow: var(--shadow-sidebar);
  transition: width var(--transition-medium), padding var(--transition-medium);
}

.shell-sidebar-collapsed {
  width: 92px;
  padding-inline: 12px;
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 64px;
  padding: 12px;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid var(--border-soft);
}

.brand-mark {
  width: 40px;
  height: 40px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #f8fbff;
  background: var(--bg-elevated);
  box-shadow: var(--shadow-soft);
}

.brand-copy {
  min-width: 0;
}

.brand-name {
  font-size: 16px;
  font-weight: 800;
  color: #f8fbff;
}

.brand-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(231, 240, 251, 0.72);
}

.sidebar-menu {
  flex: 1;
  border-right: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sidebar-menu :deep(.el-menu-item) {
  height: 46px;
  margin-bottom: 6px;
  border-radius: 16px;
  transition: background var(--transition-fast), color var(--transition-fast), transform var(--transition-fast);
}

.sidebar-menu :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.08) !important;
  transform: translateX(1px);
}

.sidebar-menu :deep(.el-menu-item.is-active) {
  background: var(--bg-sidebar-active) !important;
  box-shadow: inset 0 0 0 1px rgba(125, 211, 252, 0.16);
}

.sidebar-footer {
  padding-top: 6px;
}

.sidebar-toggle {
  width: 100%;
  justify-content: center;
  color: rgba(231, 240, 251, 0.7);
}

.shell-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.shell-topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 28px 14px;
  background: var(--bg-elevated);
  backdrop-filter: blur(20px);
}

.topbar-copy {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.topbar-kicker {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--brand-secondary);
}

.topbar-copy h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.1;
  color: var(--text-primary);
}

.hamburger-btn {
  margin-right: var(--space-2);
}

.shell-sidebar-mobile {
  position: relative;
  width: 100%;
  height: 100%;
}

.mobile-drawer-sidebar :deep(.el-drawer__body) {
  padding: 0;
  background: var(--bg-sidebar);
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.topbar-icon-button {
  flex: 0 0 auto;
}

.user-entry {
  border: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px 6px 6px;
  border-radius: 18px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-soft);
  color: var(--text-primary);
  cursor: pointer;
  box-shadow: var(--shadow-soft);
}

.user-avatar {
  background: var(--bg-primary);
  color: #f8fbff;
}

.user-copy {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 0;
}

.user-name {
  font-size: 14px;
  font-weight: 700;
}

.user-role {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-secondary);
}

.user-arrow {
  color: var(--text-tertiary);
}

.shell-content {
  min-width: 0;
  padding: 10px 28px 28px;
}

.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity var(--transition-fast), transform var(--transition-fast);
}

.page-fade-enter-from,
.page-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

@media (max-width: 1080px) and (min-width: 769px) {
  .shell-layout {
    grid-template-columns: 92px minmax(0, 1fr);
  }

  .shell-sidebar {
    width: 92px;
    padding-inline: 12px;
  }

  .brand-copy,
  .sidebar-toggle span {
    display: none;
  }
}

@media (max-width: 768px) {
  .shell-layout {
    display: block;
  }

  .shell-topbar,
  .shell-content {
    padding-inline: 16px;
  }

  .shell-topbar {
    align-items: center;
    flex-direction: row;
  }

  .topbar-copy h1 {
    font-size: 20px;
  }

  .user-copy {
    display: none;
  }
}

.topbar-icon-button {
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
}
</style>
