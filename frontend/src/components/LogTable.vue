<template>
  <el-table :data="logs" stripe style="width: 100%">
    <el-table-column label="时间" width="180">
      <template #default="{ row }">
        {{ new Date(row.executed_at).toLocaleString('zh-CN') }}
      </template>
    </el-table-column>
    <el-table-column label="状态" width="100">
      <template #default="{ row }">
        <StatusBadge :status="row.status" />
      </template>
    </el-table-column>
    <el-table-column label="详情" prop="message" show-overflow-tooltip />
  </el-table>
</template>

<script setup lang="ts">
import StatusBadge from './StatusBadge.vue'

defineProps<{
  logs: any[]
}>()
</script>
