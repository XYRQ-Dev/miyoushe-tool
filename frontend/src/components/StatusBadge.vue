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
  background: linear-gradient(135deg, #ecfdf3 0%, #dcfce7 100%);
  color: #167c45;
  box-shadow: inset 0 0 0 1px rgba(34, 197, 94, 0.18);
}

.status-badge--failed {
  background: linear-gradient(135deg, #fff1f2 0%, #ffe4e6 100%);
  color: #d53f5a;
  box-shadow: inset 0 0 0 1px rgba(244, 63, 94, 0.2);
}

.status-badge--already_signed {
  background: linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
  color: #526075;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.22);
}

.status-badge--risk {
  background: linear-gradient(135deg, #fff7ed 0%, #ffedd5 100%);
  color: #c26a18;
  box-shadow: inset 0 0 0 1px rgba(249, 115, 22, 0.2);
}

.status-badge--unknown {
  background: linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
  color: #526075;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.22);
}
</style>
