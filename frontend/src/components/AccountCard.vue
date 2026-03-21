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
      <div class="status-pill" :class="statusClass">
        <span class="status-dot"></span>
        <span>{{ statusText }}</span>
      </div>
    </div>

    <div class="status-panel" :class="panelClass">
      <div class="status-panel-main">
        <div class="status-panel-title">{{ statusTitle }}</div>
        <div class="status-panel-desc">{{ statusDescription }}</div>
      </div>
      <div class="status-panel-meta">
        <span class="meta-chip">网页登录 Cookie</span>
        <span v-if="lastRefreshText" class="meta-text">{{ lastRefreshText }}</span>
      </div>
      <div v-if="account.last_refresh_message" class="status-panel-note">
        {{ account.last_refresh_message }}
      </div>
    </div>

    <div v-if="account.game_roles?.length" class="roles-section">
      <div class="section-title">绑定角色</div>
      <div class="role-list">
        <div v-for="role in account.game_roles" :key="role.id" class="role-item">
          <span class="role-game">{{ getGameName(role.game_biz) }}</span>
          <span class="role-name">{{ role.nickname || role.game_uid }}</span>
          <span v-if="!isCheckinSupported(role.game_biz)" class="role-unsupported">签到未适配</span>
          <span class="role-level">Lv.{{ role.level || '?' }}</span>
        </div>
      </div>
    </div>
    <div v-else class="roles-section">
      <el-empty description="暂无游戏角色" :image-size="40" />
    </div>

    <div class="card-actions">
      <el-button size="small" plain :icon="RefreshRight" @click="$emit('check')">
        校验登录态
      </el-button>
      <el-button size="small" type="primary" :icon="Refresh" @click="$emit('reauth')">
        {{ account.cookie_status === 'reauth_required' ? '重新扫码登录' : '扫码更新凭据' }}
      </el-button>
      <el-button size="small" type="danger" :icon="Delete" @click="$emit('delete')">
        删除
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Refresh, RefreshRight, Delete } from '@element-plus/icons-vue'
import { getGameName } from '../constants/game'

const props = defineProps<{
  account: any
}>()

defineEmits(['check', 'reauth', 'delete'])

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
    case 'refreshing': return 'status-refreshing'
    case 'expired': return 'status-expired'
    case 'reauth_required': return 'status-reauth'
    default: return 'status-unknown'
  }
})

const statusText = computed(() => {
  switch (props.account.cookie_status) {
    case 'valid': return 'Cookie 有效'
    case 'refreshing': return '正在校验'
    case 'expired': return 'Cookie 已过期'
    case 'reauth_required': return '需要重登'
    default: return '状态未知'
  }
})

const panelClass = computed(() => {
  switch (props.account.cookie_status) {
    case 'valid': return 'panel-valid'
    case 'refreshing': return 'panel-refreshing'
    case 'expired': return 'panel-expired'
    case 'reauth_required': return 'panel-reauth'
    default: return 'panel-unknown'
  }
})

const statusTitle = computed(() => {
  switch (props.account.cookie_status) {
    case 'valid': return '登录态稳定'
    case 'refreshing': return '系统正在校验登录态'
    case 'expired': return '登录态需要重新扫码'
    case 'reauth_required': return '登录态已失效'
    default: return '尚未完成状态确认'
  }
})

const statusDescription = computed(() => {
  switch (props.account.cookie_status) {
    case 'valid':
      return '当前账号可以正常参与签到任务。'
    case 'refreshing':
      return '建议稍后刷新账号列表，查看最新校验结果。'
    case 'expired':
      return '当前网页登录态已不可用，请尽快重新扫码更新凭据。'
    case 'reauth_required':
      return '系统已确认该账号需要重新扫码登录。'
    default:
      return '当前还没有足够信息判断账号网页登录态是否可用。'
  }
})

function formatDateTime(value?: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

const lastRefreshText = computed(() => {
  if (props.account.last_refresh_attempt_at) {
    return `最近校验 ${formatDateTime(props.account.last_refresh_attempt_at)}`
  }
  if (props.account.last_cookie_check) {
    return `最近校验 ${formatDateTime(props.account.last_cookie_check)}`
  }
  return ''
})
</script>

<style scoped>
.account-card {
  background: var(--bg-elevated);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  box-shadow: var(--shadow-soft);
  border: 1px solid var(--border-soft);
  transition: all var(--transition-medium);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.account-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-medium);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.account-info {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.account-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.account-uid {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 1px;
}

.status-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-valid { color: var(--text-success); background: var(--bg-success-soft); }
.status-valid .status-dot { background: var(--color-success); box-shadow: 0 0 6px var(--color-success); }
.status-refreshing { color: var(--text-info); background: var(--bg-info-soft); }
.status-refreshing .status-dot { background: var(--color-info); box-shadow: 0 0 6px var(--color-info); }
.status-expired { color: var(--text-warning); background: var(--bg-warning-soft); }
.status-expired .status-dot { background: var(--color-warning); box-shadow: 0 0 6px var(--color-warning); }
.status-reauth { color: var(--text-danger); background: var(--bg-danger-soft); }
.status-reauth .status-dot { background: var(--color-danger); box-shadow: 0 0 6px var(--color-danger); }
.status-unknown { color: var(--text-tertiary); background: var(--bg-soft); }
.status-unknown .status-dot { background: var(--text-tertiary); }

.status-panel {
  border-radius: var(--radius-md);
  padding: var(--space-3);
  background: var(--bg-soft);
  border: 1px solid var(--border-soft);
}

.status-panel-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.status-panel-desc {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
  margin-top: 4px;
}

.status-panel-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
}

.meta-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  color: var(--text-secondary);
  background: var(--bg-surface);
  border: 1px solid var(--border-soft);
}

.meta-text {
  font-size: 11px;
  color: var(--text-tertiary);
}

.status-panel-note {
  margin-top: 8px;
  padding-top: 8px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-tertiary);
  border-top: 1px dashed var(--border-soft);
}

.roles-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.role-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.role-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--bg-surface-muted);
  border-radius: var(--radius-xs);
  border: 1px solid var(--border-soft);
}

.role-game {
  font-size: 10px;
  color: var(--brand-primary);
  background: var(--bg-info-soft);
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 700;
}

.role-name {
  flex: 1;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-level {
  font-size: 11px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.role-unsupported {
  font-size: 10px;
  color: var(--text-warning);
  background: var(--bg-warning-soft);
  padding: 2px 6px;
  border-radius: 999px;
  white-space: nowrap;
}

.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: auto;
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-soft);
}

.card-actions :deep(.el-button) {
  flex: 1;
  min-width: 0;
  height: 32px;
  font-size: 12px;
  padding: 0 12px;
}

@media (max-width: 640px) {
  .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
}
</style>

