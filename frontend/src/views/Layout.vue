<template>
  <el-container class="app-layout">
    <!-- 侧边栏 -->
    <el-aside :width="isCollapse ? '64px' : '220px'" class="sidebar">
      <div class="sidebar-header">
        <div class="logo-mini" v-if="isCollapse">
          <el-icon :size="24"><Star /></el-icon>
        </div>
        <div class="logo-full" v-else>
          <el-icon :size="20"><Star /></el-icon>
          <span>米游社签到</span>
        </div>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        router
        class="sidebar-menu"
        background-color="transparent"
        text-color="rgba(255,255,255,0.7)"
        active-text-color="#fff"
      >
        <el-menu-item v-for="menu in visibleMenus" :key="menu.key" :index="menu.path">
          <el-icon><component :is="menuIconMap[menu.key]" /></el-icon>
          <template #title>{{ menu.label }}</template>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <el-button
          :icon="isCollapse ? Expand : Fold"
          text
          class="collapse-btn"
          @click="isCollapse = !isCollapse"
        />
      </div>
    </el-aside>

    <!-- 主内容区域 -->
    <el-container>
      <!-- 顶部导航栏 -->
      <el-header class="topbar" height="60px">
        <div class="topbar-left">
          <h2>{{ pageTitle }}</h2>
        </div>
        <div class="topbar-right">
          <el-button
            :icon="userStore.darkMode ? Sunny : Moon"
            circle
            size="small"
            @click="userStore.toggleDarkMode()"
          />
          <el-dropdown trigger="click">
            <div class="user-avatar">
              <el-avatar :size="32" :style="{ background: 'var(--primary-color)' }">
                {{ userStore.userInfo?.username?.charAt(0)?.toUpperCase() }}
              </el-avatar>
              <span class="username">{{ userStore.userInfo?.username }}</span>
              <el-icon><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="settingsVisible" @click="router.push('/settings')">
                  <el-icon><Setting /></el-icon>设置
                </el-dropdown-item>
                <el-dropdown-item divided @click="handleLogout">
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <!-- 页面内容 -->
      <el-main class="main-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
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
const visibleMenus = computed(() => getVisibleMenus(userStore.visibleMenuKeys))
const settingsVisible = computed(() => hasMenuAccess('settings', userStore.visibleMenuKeys))

const pageTitle = computed(() => {
  const matchedMenu = APP_MENUS.find((item) => item.path === route.path)
  return matchedMenu?.label || '米游社签到'
})

function handleLogout() {
  userStore.logout()
  router.push('/login')
}

onMounted(() => {
  userStore.ensureUserInfoLoaded()
})
</script>

<style scoped>
.app-layout {
  min-height: 100vh;
}

.sidebar {
  background: linear-gradient(180deg, #1e1b4b 0%, #312e81 100%);
  transition: width 0.3s;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-header {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.logo-mini {
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
}

.logo-full {
  display: flex;
  align-items: center;
  gap: 8px;
  color: white;
  font-size: 16px;
  font-weight: 600;
}

.sidebar-menu {
  flex: 1;
  border-right: none;
  padding: 8px;
}

.sidebar-menu :deep(.el-menu-item) {
  border-radius: 8px;
  margin-bottom: 4px;
  height: 44px;
}

.sidebar-menu :deep(.el-menu-item.is-active) {
  background: rgba(255, 255, 255, 0.15) !important;
}

.sidebar-menu :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.1) !important;
}

.sidebar-footer {
  padding: 12px;
  display: flex;
  justify-content: center;
}

.collapse-btn {
  color: rgba(255, 255, 255, 0.6);
}

.topbar {
  background: var(--card-bg);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.topbar h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-avatar {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background 0.2s;
}

.user-avatar:hover {
  background: var(--bg-color);
}

.username {
  font-size: 14px;
  color: var(--text-primary);
}

.main-content {
  background: var(--bg-color);
  padding: 24px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
