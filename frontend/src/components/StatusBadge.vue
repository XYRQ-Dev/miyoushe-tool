<template>
  <el-tag
    :type="tagType"
    size="small"
    :effect="effect"
    round
    class="status-badge"
    :class="[
      `status-badge--${props.status || 'unknown'}`,
      { 'status-badge--compact': compact },
    ]"
  >
    <el-icon class="badge-icon"><component :is="iconComponent" /></el-icon>
    {{ label }}
  </el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, CircleClose, Warning, Clock } from '@element-plus/icons-vue'

const props = defineProps<{
  status: string
  effect?: 'dark' | 'light' | 'plain'
  compact?: boolean
}>()

const tagType = computed(() => {
  switch (props.status) {
    case 'success': return 'success'
    case 'failed': return 'danger'
    case 'already_signed': return 'info'
    case 'risk': return 'warning'
    default: return 'info'
  }
})

const iconComponent = computed(() => {
  switch (props.status) {
    case 'success': return CircleCheck
    case 'failed': return CircleClose
    case 'already_signed': return Clock
    case 'risk': return Warning
    default: return Clock
  }
})

const label = computed(() => {
  switch (props.status) {
    case 'success': return '成功'
    case 'failed': return '失败'
    case 'already_signed': return '已签到'
    case 'risk': return '风控'
    default: return props.status
  }
})
</script>

<style scoped>
.badge-icon {
  font-size: 12px;
  vertical-align: middle;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  width: fit-content;
  min-width: 68px;
  max-width: 100%;
  height: 28px;
  padding-inline: 10px;
  border: none;
  box-shadow: inset 0 0 0 1px transparent;
}

.status-badge--compact {
  min-width: 64px;
  padding-inline: 8px;
}

.status-badge :deep(.el-tag__content) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  white-space: nowrap;
  word-break: keep-all;
  line-height: 1;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.status-badge--success {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(16, 185, 129, 0.2) 100%);
  color: var(--success-color);
  box-shadow: inset 0 0 0 1px rgba(16, 185, 129, 0.18);
}

.status-badge--failed {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.1) 0%, rgba(239, 68, 68, 0.18) 100%);
  color: var(--danger-color);
  box-shadow: inset 0 0 0 1px rgba(239, 68, 68, 0.18);
}

.status-badge--already_signed {
  background: linear-gradient(135deg, rgba(148, 163, 184, 0.1) 0%, rgba(148, 163, 184, 0.18) 100%);
  color: var(--text-secondary);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.2);
}

.status-badge--risk {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.1) 0%, rgba(245, 158, 11, 0.18) 100%);
  color: var(--warning-color);
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.18);
}

.status-badge--unknown {
  background: linear-gradient(135deg, rgba(148, 163, 184, 0.1) 0%, rgba(148, 163, 184, 0.18) 100%);
  color: var(--text-secondary);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.2);
}
</style>
