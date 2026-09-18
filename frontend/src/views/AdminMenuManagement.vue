<template>
  <div v-if="userStore.isAdmin" class="app-page admin-menu-page">
    <el-card class="menu-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <h3>菜单与功能开关</h3>
            <p>按用户类型控制菜单和功能是否可见。隐藏后将同时禁止该用户类型直接访问页面或使用对应功能。</p>
          </div>
          <div class="header-actions">
            <el-button :icon="Refresh" @click="loadMenus" :loading="loading" round>刷新</el-button>
            <el-button type="primary" :loading="saving" @click="saveMenus" round>保存配置</el-button>
          </div>
        </div>
      </template>

      <el-alert
        type="warning"
        :closable="false"
        class="menu-alert"
        title="当前页面始终对管理员可见，避免误操作后无法恢复其他菜单。"
      />

      <el-table :data="menuItems" stripe table-layout="auto">
        <el-table-column label="菜单/功能名称" min-width="220">
          <template #default="{ row }">
            <div class="menu-name-row">
              <div class="menu-name">{{ row.label }}</div>
              <el-tag v-if="row.navigable === false" type="info" size="small" effect="plain">功能开关</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="页面/归属" min-width="220">
          <template #default="{ row }">
            <span class="menu-path">{{ row.navigable === false ? '系统内功能开关（非独立页面）' : row.path }}</span>
          </template>
        </el-table-column>
        <el-table-column label="普通用户可见" min-width="140" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.user_visible" :disabled="!row.editable" />
          </template>
        </el-table-column>
        <el-table-column label="管理员可见" min-width="140" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.admin_visible" :disabled="!row.editable" />
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="140">
          <template #default="{ row }">
            <el-tag v-if="!row.editable" type="warning" size="small">始终可见</el-tag>
            <span v-else-if="row.navigable === false" class="row-tip">按角色控制该功能开关是否生效</span>
            <span v-else class="row-tip">按角色单独生效</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '../api'
import { useUserStore } from '../stores/user'
import { getMenuDenyTarget, hasMenuAccess } from '../utils/menuVisibility'

type AdminMenuItem = {
  key: string
  label: string
  path: string
  user_visible: boolean
  admin_visible: boolean
  editable: boolean
  navigable: boolean
}

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const menuItems = ref<AdminMenuItem[]>([])

async function loadMenus() {
  if (!userStore.isAdmin) {
    menuItems.value = []
    return
  }

  loading.value = true
  try {
    const { data } = await adminApi.getMenuVisibility()
    menuItems.value = data.items || []
  } finally {
    loading.value = false
  }
}

async function saveMenus() {
  saving.value = true
  try {
    const payload = {
      items: menuItems.value
        .filter((item) => item.editable)
        .map((item) => ({
          key: item.key,
          user_visible: item.user_visible,
          admin_visible: item.admin_visible,
        })),
    }
    const { data } = await adminApi.updateMenuVisibility(payload)
    menuItems.value = data.items || []
    await userStore.fetchUserInfo()

    if (!hasMenuAccess(route.meta.menuKey as string | undefined, userStore.visibleMenuKeys)) {
      router.replace(getMenuDenyTarget(userStore.isAdmin))
      return
    }

    ElMessage.success('菜单配置已保存')
  } finally {
    saving.value = false
  }
}

onMounted(loadMenus)
</script>

<style scoped>
.admin-menu-page {
  max-width: 1280px;
  margin: 0 auto;
}

.menu-card {
  border-radius: 16px;
  border: 1px solid var(--border-color);
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.card-header h3 {
  margin: 0;
  font-size: 18px;
  color: var(--text-primary);
}

.card-header p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.header-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.menu-alert {
  margin-bottom: 16px;
}

.menu-name {
  font-weight: 600;
  color: var(--text-primary);
}

.menu-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.menu-path {
  font-family: Consolas, 'Courier New', monospace;
  color: var(--text-secondary);
}

.row-tip {
  font-size: 12px;
  color: var(--text-secondary);
}

@media (max-width: 768px) {
  .card-header {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
