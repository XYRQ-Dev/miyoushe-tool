<template>
  <div class="account-card">
    <div class="card-header">
      <div class="account-info">
        <el-avatar :size="40" :style="{ background: avatarColor }">
          {{ (account.nickname || 'U').charAt(0) }}
        </el-avatar>
        <div class="account-meta">
          <div class="account-name">{{ account.nickname || '未知用户' }}</div>
          <div class="account-uid">UID: {{ account.mihoyo_uid || '-' }}</div>
        </div>
      </div>
      <div class="cookie-status">
        <span class="status-dot" :class="statusClass"></span>
        <span class="status-text">{{ statusText }}</span>
      </div>
    </div>

    <!-- 游戏角色列表 -->
    <div class="roles-section" v-if="account.game_roles?.length">
      <div class="section-title">绑定角色</div>
      <div class="role-list">
        <div v-for="role in account.game_roles" :key="role.id" class="role-item">
          <span class="role-game">{{ gameNames[role.game_biz] || role.game_biz }}</span>
          <span class="role-name">{{ role.nickname || role.game_uid }}</span>
          <span v-if="!isCheckinSupported(role.game_biz)" class="role-unsupported">签到未适配</span>
          <span class="role-level">Lv.{{ role.level || '?' }}</span>
        </div>
      </div>
    </div>
    <div class="roles-section" v-else>
      <el-empty description="暂无游戏角色" :image-size="40" />
    </div>

    <!-- 操作按钮 -->
    <div class="card-actions">
      <el-button size="small" :icon="Refresh" @click="$emit('refresh')">
        刷新 Cookie
      </el-button>
      <el-button size="small" type="danger" :icon="Delete" @click="$emit('delete')">
        删除
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Refresh, Delete } from '@element-plus/icons-vue'

const props = defineProps<{
  account: any
}>()

defineEmits(['refresh', 'delete'])

const gameNames: Record<string, string> = {
  hk4e_cn: '原神',
  hk4e_bilibili: '原神(B服)',
  hkrpg_cn: '星穹铁道',
  hkrpg_bilibili: '星铁(B服)',
  nap_cn: '绝区零',
  bh3_cn: '崩坏3',
}

// 这里的前端支持名单必须与后端实际放开的签到能力保持一致。
// 如果只改后端不改这里，用户会看到“明明能签却仍显示未适配”；反过来若前端先放开，
// 又会把仍未接入的游戏误导成可用状态，增加排障成本。
const supportedCheckinGames = new Set(['hk4e_cn', 'hk4e_bilibili', 'hkrpg_cn', 'hkrpg_bilibili', 'bh3_cn', 'nap_cn'])

function isCheckinSupported(gameBiz: string) {
  return supportedCheckinGames.has(gameBiz)
}

const avatarColor = computed(() => {
  const colors = ['#6366f1', '#8b5cf6', '#ec4899', '#f97316', '#14b8a6']
  return colors[props.account.id % colors.length]
})

const statusClass = computed(() => {
  switch (props.account.cookie_status) {
    case 'valid': return 'status-valid'
    case 'expired': return 'status-expired'
    default: return 'status-unknown'
  }
})

const statusText = computed(() => {
  switch (props.account.cookie_status) {
    case 'valid': return 'Cookie 有效'
    case 'expired': return 'Cookie 已过期'
    default: return '状态未知'
  }
})
</script>

<style scoped>
.account-card {
  background: var(--card-bg);
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  border: 1px solid var(--border-color);
  transition: transform 0.2s, box-shadow 0.2s;
}

.account-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.account-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.account-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.account-uid {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.cookie-status {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-valid { background: #10b981; box-shadow: 0 0 6px rgba(16, 185, 129, 0.4); }
.status-expired { background: #ef4444; box-shadow: 0 0 6px rgba(239, 68, 68, 0.4); }
.status-unknown { background: #f59e0b; }

.status-text {
  font-size: 12px;
  color: var(--text-secondary);
}

.roles-section {
  margin-bottom: 16px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 8px;
}

.role-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-color);
  border-radius: 8px;
  margin-bottom: 4px;
}

.role-game {
  font-size: 12px;
  color: #6366f1;
  background: rgba(99, 102, 241, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}

.role-name {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
}

.role-level {
  font-size: 12px;
  color: var(--text-secondary);
}

.role-unsupported {
  font-size: 11px;
  color: #b7791f;
  background: linear-gradient(135deg, #fff7e6 0%, #ffefcc 100%);
  padding: 2px 8px;
  border-radius: 999px;
  box-shadow: inset 0 0 0 1px rgba(221, 107, 32, 0.18);
  white-space: nowrap;
}

.card-actions {
  display: flex;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
}
</style>
