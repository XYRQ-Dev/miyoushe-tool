<template>
  <div v-if="userStore.isAdmin" class="admin-menu-page">
    <el-card class="menu-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <h3>菜单管理</h3>
            <p>按用户类型控制侧边栏菜单是否显示。隐藏后将同时禁止该用户类型直接访问页面。</p>
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
        title="菜单管理页是管理员保底入口，不参与隐藏配置，避免误操作后无法恢复后台访问。"
      />

      <el-table :data="menuItems" stripe table-layout="auto">
        <el-table-column label="菜单名称" min-width="180">
          <template #default="{ row }">
            <div class="menu-name">{{ row.label }}</div>
          </template>
        </el-table-column>
        <el-table-column label="路径" min-width="180">
          <template #default="{ row }">
            <span class="menu-path">{{ row.path }}</span>
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
            <el-tag v-if="!row.editable" type="warning" size="small">保底入口</el-tag>
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
