import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../stores/user'
import { getMenuDenyTarget, hasMenuAccess } from '../utils/menuVisibility'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/Login.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      component: () => import('../views/Layout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          name: 'Dashboard',
          component: () => import('../views/Dashboard.vue'),
          meta: { menuKey: 'dashboard' },
        },
        {
          path: 'accounts',
          name: 'Accounts',
          component: () => import('../views/Accounts.vue'),
          meta: { menuKey: 'accounts' },
        },
        {
          path: 'logs',
          name: 'TaskLogs',
          component: () => import('../views/TaskLogs.vue'),
          meta: { menuKey: 'logs' },
        },
        {
          path: 'gacha',
          name: 'GachaRecords',
          component: () => import('../views/GachaRecords.vue'),
          meta: { menuKey: 'gacha' },
        },
        {
          path: 'assets',
          name: 'RoleAssets',
          component: () => import('../views/RoleAssets.vue'),
          meta: { menuKey: 'assets' },
        },
        {
          path: 'health',
          name: 'HealthCenter',
          component: () => import('../views/HealthCenter.vue'),
          meta: { menuKey: 'health' },
        },
        // 兑换码中心功能入口
        {
          path: 'redeem',
          name: 'RedeemCodes',
          component: () => import('../views/RedeemCodes.vue'),
          meta: { menuKey: 'redeem' },
        },
        {
          path: 'settings',
          name: 'Settings',
          component: () => import('../views/Settings.vue'),
          meta: { menuKey: 'settings' },
        },
        {
          path: 'admin/users',
          name: 'AdminUsers',
          component: () => import('../views/AdminUsers.vue'),
          meta: { requiresAdmin: true, menuKey: 'admin_users' },
        },
        {
          path: 'admin/menus',
          name: 'AdminMenuManagement',
          component: () => import('../views/AdminMenuManagement.vue'),
          meta: { requiresAdmin: true, menuKey: 'admin_menu_management' },
        },
      ],
    },
  ],
})

// 路由守卫：受保护页面在放行前先恢复用户信息，避免刷新时把管理员误判成普通用户。
router.beforeEach(async (to, from, next) => {
  const token = localStorage.getItem('access_token')
  const userStore = useUserStore()
  if (to.meta.requiresAuth !== false && !token) {
    next('/login')
    return
  }

  if (token) {
    await userStore.ensureUserInfoLoaded()
  }

  if (to.path === '/login' && token) {
    next('/')
  } else if (to.meta.requiresAdmin && !userStore.isAdmin) {
    next('/')
  } else if (!hasMenuAccess(to.meta.menuKey as string | undefined, userStore.visibleMenuKeys)) {
    next(getMenuDenyTarget(userStore.isAdmin))
  } else {
    next()
  }
})

export default router
