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
  font-size: 11px;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 64px;
  height: 24px;
  padding: 0 10px;
  border: none;
  font-weight: 700;
  font-size: 11px;
}

.status-badge :deep(.el-tag__content) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.status-badge--success {
  background: var(--bg-success-soft);
  color: var(--text-success);
}

.status-badge--failed {
  background: var(--bg-danger-soft);
  color: var(--text-danger);
}

.status-badge--already_signed {
  background: var(--bg-soft);
  color: var(--text-secondary);
}

.status-badge--risk {
  background: var(--bg-warning-soft);
  color: var(--text-warning);
}

.status-badge--unknown {
  background: var(--bg-soft);
  color: var(--text-tertiary);
}
</style>
