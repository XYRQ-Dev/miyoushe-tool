<template>
  <div class="account-card">
    <div class="card-header">
      <div class="account-info">
        <div class="avatar-wrapper" :style="{ '--avatar-color': avatarColor }">
          <el-avatar :size="48" class="main-avatar">
            {{ (account.nickname || 'U').charAt(0) }}
          </el-avatar>
          <div class="avatar-ring"></div>
        </div>
        <div class="account-meta">
          <div class="account-name">{{ account.nickname || '未知用户' }}</div>
          <div class="account-uid">UID: {{ account.mihoyo_uid || '-' }}</div>
        </div>
      </div>
      <div class="status-pill-outer" :class="statusClass">
        <div class="status-pill">
          <span class="status-dot"></span>
          <span>{{ statusText }}</span>
        </div>
      </div>
    </div>

    <div class="status-panel-card" :class="panelClass">
      <div class="panel-icon">
        <el-icon v-if="account.cookie_status === 'valid'"><CircleCheckFilled /></el-icon>
        <el-icon v-else-if="account.cookie_status === 'refreshing'"><Loading /></el-icon>
        <el-icon v-else><WarningFilled /></el-icon>
      </div>
      <div class="panel-content">
        <div class="panel-title-row">
          <span class="panel-title">{{ statusTitle }}</span>
          <div class="panel-badges">
            <span class="type-badge">WEB COOKIE</span>
          </div>
        </div>
        <div class="panel-desc">{{ statusDescription }}</div>
        
        <div v-if="account.last_refresh_message" class="panel-note">
          <el-icon><ChatLineRound /></el-icon>
          <span>{{ account.last_refresh_message }}</span>
        </div>

        <div class="panel-footer">
          <span v-if="lastRefreshText" class="refresh-time">
            <el-icon><Clock /></el-icon>
            {{ lastRefreshText }}
          </span>
        </div>
      </div>
    </div>

    <div class="roles-section">
      <div class="section-label">
        <span class="label-text">活跃角色 ({{ account.game_roles?.length || 0 }})</span>
      </div>
      
      <div v-if="account.game_roles?.length" class="role-list">
        <div v-for="role in sortedGameRoles" :key="role.id" class="role-item">
          <div class="role-main-info">
            <span class="role-nickname">{{ role.nickname || role.game_uid }}</span>
            <span v-if="!isCheckinSupported(role.game_biz)" class="unsupported-tag">签到未适配</span>
          </div>
          <div class="role-meta-info">
            <span class="role-level">Lv.{{ role.level || '?' }}</span>
            <div class="role-game-badge">{{ getGameName(role.game_biz) }}</div>
          </div>
        </div>
      </div>
      <div v-else class="empty-roles">
        <el-icon><Monitor /></el-icon>
        <span>未同步到有效角色信息</span>
      </div>
    </div>

    <div class="card-actions">
      <el-button plain class="btn-secondary" @click="$emit('check')">
        <template #icon><el-icon><RefreshRight /></el-icon></template>
        校验登录态
      </el-button>
      <el-button type="primary" class="btn-primary" @click="$emit('reauth')">
        <template #icon><el-icon><Refresh /></el-icon></template>
        {{ account.cookie_status === 'reauth_required' ? '重登' : '更新凭证' }}
      </el-button>
      <el-button type="danger" plain class="btn-danger" @click="$emit('delete')">
        <template #icon><el-icon><Delete /></el-icon></template>
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { 
  Refresh, RefreshRight, Delete, CircleCheckFilled, 
  WarningFilled, Loading, Clock, Monitor, ChatLineRound
} from '@element-plus/icons-vue'
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
    case 'refreshing': return '正在同步'
    case 'expired': return '授权过期'
    case 'reauth_required': return '需要更新'
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
    case 'valid': return '登录态状态良好'
    case 'refreshing': return '系统正在刷新背景数据'
    case 'expired': return '需重新进行高权限验证'
    case 'reauth_required': return '账号登录态已完全失效'
    default: return '等待初次校验结果'
  }
})

const statusDescription = computed(() => {
  switch (props.account.cookie_status) {
    case 'valid':
      return '当前凭据可用于所有支持的自动签到任务。'
    case 'refreshing':
      return '正在尝试基于 Passport 凭证刷新 Cookie，请耐心等待。'
    case 'expired':
      return '网页 Cookie 无法自动刷新，请立即通过扫码更新。'
    case 'reauth_required':
      return '米游社已强制下线该设备。请尝试重新登录以恢复。'
    default:
      return '暂未获取到该账号的详细登录有效性信息。'
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
    return `${formatDateTime(props.account.last_refresh_attempt_at)}`
  }
  if (props.account.last_cookie_check) {
    return `${formatDateTime(props.account.last_cookie_check)}`
  }
  return ''
})

const sortedGameRoles = computed(() => {
  if (!props.account.game_roles) return []
  return [...props.account.game_roles].sort((a, b) => {
    const nameA = getGameName(a.game_biz)
    const nameB = getGameName(b.game_biz)
    return nameA.length - nameB.length
  })
})
</script>

<style scoped>
.account-card {
  padding: 24px 20px 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.account-info {
  display: flex;
  align-items: center;
  gap: 14px;
}

.avatar-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.main-avatar {
  background: var(--avatar-color);
  font-weight: 700;
  font-size: 20px;
  color: #fff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  z-index: 2;
}

.avatar-ring {
  position: absolute;
  width: 58px;
  height: 58px;
  border-radius: 50%;
  border: 2px solid var(--avatar-color);
  opacity: 0.15;
  z-index: 1;
}

.account-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 2px;
}

.account-uid {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono, monospace);
  letter-spacing: 0.5px;
}

.status-pill-outer {
  padding: 2px;
  border-radius: 20px;
  background: rgba(0, 0, 0, 0.04);
}

.status-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 18px;
  font-size: 11px;
  font-weight: 700;
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-valid { color: var(--color-success); }
.status-valid .status-dot { background: var(--color-success); box-shadow: 0 0 8px var(--color-success); }
.status-refreshing { color: var(--color-info); }
.status-refreshing .status-dot { background: var(--color-info); box-shadow: 0 0 8px var(--color-info); }
.status-expired { color: var(--color-warning); }
.status-expired .status-dot { background: var(--color-warning); box-shadow: 0 0 8px var(--color-warning); }
.status-reauth { color: var(--color-danger); }
.status-reauth .status-dot { background: var(--color-danger); box-shadow: 0 0 8px var(--color-danger); }

.status-panel-card {
  display: flex;
  gap: 12px;
  padding: 16px;
  border-radius: var(--radius-lg);
  background: var(--bg-soft);
  border: 1px solid var(--border-soft);
  position: relative;
  overflow: hidden;
}

.status-panel-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; bottom: 0;
  width: 4px;
}

.panel-valid::before { background: var(--color-success); }
.panel-refreshing::before { background: var(--color-info); }
.panel-expired::before { background: var(--color-warning); }
.panel-reauth::before { background: var(--color-danger); }

.panel-icon {
  font-size: 20px;
  margin-top: 2px;
}

.panel-valid .panel-icon { color: var(--color-success); }
.panel-refreshing .panel-icon { color: var(--color-info); animation: rotating 2s linear infinite; }
.panel-expired .panel-icon { color: var(--color-warning); }
.panel-reauth .panel-icon { color: var(--color-danger); }

@keyframes rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.panel-content { flex: 1; }

.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.panel-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.type-badge {
  font-size: 10px;
  font-weight: 800;
  color: var(--text-tertiary);
  background: var(--bg-surface-muted);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-soft);
}

.panel-desc {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.panel-note {
  margin-top: 10px;
  padding: 8px 10px;
  background: var(--bg-surface-muted);
  border-radius: 6px;
  font-size: 11px;
  color: var(--text-tertiary);
  display: flex;
  gap: 6px;
  align-items: flex-start;
  line-height: 1.4;
}

.panel-footer {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.refresh-time {
  font-size: 11px;
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  gap: 4px;
  font-variant-numeric: tabular-nums;
}

.roles-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-label {
  display: flex;
  align-items: center;
  gap: 12px;
}

.label-text {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-tertiary);
  white-space: nowrap;
}

.label-line {
  height: 1px;
  background: var(--border-soft);
  flex: 1;
}

.roles-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-label {
  display: flex;
  align-items: center;
}

.label-text {
  font-size: 12px;
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
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg-surface-muted);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-soft);
  transition: all var(--transition-fast);
}

.role-item:hover {
  border-color: var(--border-medium);
  background: var(--bg-soft);
}

.role-main-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.role-nickname {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.unsupported-tag {
  font-size: 10px;
  background: var(--bg-warning-soft);
  color: var(--color-warning);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 700;
  white-space: nowrap;
}

.role-meta-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.role-level {
  font-size: 13px;
  font-weight: 800;
  color: var(--text-secondary);
  font-family: var(--font-mono, monospace);
}

.role-game-badge {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-tertiary);
  background: var(--bg-surface);
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-soft);
}

.empty-roles {
  padding: 20px;
  text-align: center;
  background: var(--bg-soft);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-tertiary);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.empty-roles .el-icon { font-size: 24px; opacity: 0.3; }

.card-actions {
  display: flex;
  gap: 8px;
  padding-top: 16px;
  border-top: 1px solid var(--border-soft);
}

.btn-secondary { flex: 1.5; font-weight: 600; font-size: 13px; }
.btn-primary { flex: 1.5; font-weight: 600; font-size: 13px; }
.btn-danger { width: 42px; padding: 0; display: flex; justify-content: center; }

@media (max-width: 480px) {
  .card-header { flex-direction: column; align-items: flex-start; gap: 12px; }
  .card-actions { flex-direction: row; }
}
</style>

