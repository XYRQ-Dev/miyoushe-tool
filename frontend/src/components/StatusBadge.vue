<template>
  <el-tag :type="tagType" size="small" :effect="effect" round>
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
  margin-right: 2px;
  vertical-align: middle;
}
</style>
