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
        <span class="meta-chip">{{ autoRefreshText }}</span>
        <span v-if="lastRefreshText" class="meta-text">{{ lastRefreshText }}</span>
      </div>
      <div v-if="account.last_refresh_message" class="status-panel-note">
        {{ account.last_refresh_message }}
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
      <el-button size="small" plain :icon="RefreshRight" @click="$emit('maintain')">
        校验并续期
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

const props = defineProps<{
  account: any
}>()

defineEmits(['maintain', 'reauth', 'delete'])

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
    case 'refreshing': return 'status-refreshing'
    case 'expired': return 'status-expired'
    case 'reauth_required': return 'status-reauth'
    default: return 'status-unknown'
  }
})

const statusText = computed(() => {
  switch (props.account.cookie_status) {
    case 'valid': return 'Cookie 有效'
    case 'refreshing': return '正在维护'
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
    case 'refreshing': return '系统正在尝试恢复登录态'
    case 'expired': return '登录态需要尽快维护'
    case 'reauth_required': return '自动续期已失效'
    default: return '尚未完成状态确认'
  }
})

const statusDescription = computed(() => {
  switch (props.account.cookie_status) {
    case 'valid':
      return '当前账号可以正常参与签到任务。'
    case 'refreshing':
      return '建议稍后刷新账号列表，查看最新维护结果。'
    case 'expired':
      return '可以先尝试“校验并续期”；若失败，再重新扫码。'
    case 'reauth_required':
      return '系统已无法自动恢复该账号，请尽快重新扫码登录。'
    default:
      return '当前还没有足够信息判断账号是否可自动续期。'
  }
})

const autoRefreshText = computed(() => {
  return props.account.auto_refresh_available ? '支持自动续期' : '仅支持重新扫码'
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
    return `最近维护 ${formatDateTime(props.account.last_refresh_attempt_at)}`
  }
  if (props.account.last_cookie_check) {
    return `最近校验 ${formatDateTime(props.account.last_cookie_check)}`
  }
  return ''
})
</script>

<style scoped>
.account-card {
  background:
    radial-gradient(circle at top right, rgba(99, 102, 241, 0.12), transparent 34%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(248, 250, 252, 0.96) 100%);
  border-radius: 20px;
  padding: 20px;
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.08);
  border: 1px solid rgba(148, 163, 184, 0.18);
  transition: transform 0.2s, box-shadow 0.2s;
}

.account-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 18px 36px rgba(15, 23, 42, 0.12);
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

.status-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-valid { color: #166534; background: #dcfce7; }
.status-valid .status-dot { background: #10b981; box-shadow: 0 0 6px rgba(16, 185, 129, 0.4); }
.status-refreshing { color: #1d4ed8; background: #dbeafe; }
.status-refreshing .status-dot { background: #3b82f6; box-shadow: 0 0 6px rgba(59, 130, 246, 0.4); }
.status-expired { color: #b45309; background: #fef3c7; }
.status-expired .status-dot { background: #f59e0b; box-shadow: 0 0 6px rgba(245, 158, 11, 0.35); }
.status-reauth { color: #b91c1c; background: #fee2e2; }
.status-reauth .status-dot { background: #ef4444; box-shadow: 0 0 6px rgba(239, 68, 68, 0.4); }
.status-unknown { color: #475569; background: #e2e8f0; }
.status-unknown .status-dot { background: #94a3b8; }

.status-panel {
  border-radius: 16px;
  padding: 14px;
  margin-bottom: 16px;
  border: 1px solid transparent;
}

.panel-valid {
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.95), rgba(220, 252, 231, 0.82));
  border-color: rgba(16, 185, 129, 0.18);
}

.panel-refreshing {
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.96), rgba(219, 234, 254, 0.86));
  border-color: rgba(59, 130, 246, 0.18);
}

.panel-expired {
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.96), rgba(254, 243, 199, 0.86));
  border-color: rgba(245, 158, 11, 0.18);
}

.panel-reauth {
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.96), rgba(254, 226, 226, 0.88));
  border-color: rgba(239, 68, 68, 0.18);
}

.panel-unknown {
  background: linear-gradient(135deg, rgba(248, 250, 252, 0.96), rgba(241, 245, 249, 0.86));
  border-color: rgba(148, 163, 184, 0.2);
}

.status-panel-main {
  margin-bottom: 10px;
}

.status-panel-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.status-panel-desc {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  margin-top: 4px;
}

.status-panel-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  color: #334155;
  background: rgba(255, 255, 255, 0.66);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.15);
}

.meta-text {
  font-size: 12px;
  color: var(--text-secondary);
}

.status-panel-note {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
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
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
}

.card-actions :deep(.el-button) {
  border-radius: 999px;
}

:global(html.dark) .account-card {
  background:
    radial-gradient(circle at top right, rgba(96, 165, 250, 0.18), transparent 34%),
    linear-gradient(180deg, rgba(15, 23, 42, 0.96) 0%, rgba(17, 24, 39, 0.96) 100%);
  border-color: rgba(148, 163, 184, 0.16);
  box-shadow: 0 16px 34px rgba(2, 6, 23, 0.45);
}

:global(html.dark) .meta-chip {
  background: rgba(15, 23, 42, 0.45);
  color: #cbd5e1;
}

:global(html.dark) .status-panel-note {
  color: #cbd5e1;
}

@media (max-width: 640px) {
  .card-header {
    align-items: flex-start;
    gap: 10px;
    flex-direction: column;
  }

  .status-panel-meta {
    align-items: flex-start;
    flex-direction: column;
  }

  .card-actions :deep(.el-button) {
    flex: 1 1 calc(50% - 6px);
    min-width: 0;
  }
}
</style>
