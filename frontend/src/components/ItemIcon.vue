<template>
  <div class="item-icon" :class="['rank-' + rankType, { 'is-circle': circle }]">
    <div class="icon-inner" :style="{ background: rankBg }">
      <img v-if="url" :src="url" :alt="name" @error="onError" />
      <span v-else>{{ initial }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { getItemIconUrl, getItemInitial, getRankColor } from '../utils/gachaIcon';

const props = defineProps<{
  name: string;
  game: string;
  rankType: string | number;
  circle?: boolean;
}>();

const failed = ref(false);
const url = computed(() => failed.value ? null : getItemIconUrl(props.name, props.game));
const initial = computed(() => getItemInitial(props.name));

const rankBg = computed(() => {
  const color = getRankColor(props.rankType);
  if (props.rankType == 5) return `linear-gradient(135deg, ${color}, #b38e22)`;
  if (props.rankType == 4) return `linear-gradient(135deg, ${color}, #7a52c7)`;
  return `linear-gradient(135deg, ${color}, #2e69bb)`;
});

function onError() { failed.value = true; }
watch(() => props.name, () => { failed.value = false; });
</script>

<style scoped>
.item-icon { width: 44px; height: 44px; flex-shrink: 0; }
.icon-inner {
  width: 100%; height: 100%; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  overflow: hidden; border: 1.5px solid rgba(255,255,255,0.2);
  color: #fff; font-weight: 800; font-size: 18px;
}
.item-icon.is-circle .icon-inner { border-radius: 50%; }
img { width: 100%; height: 100%; object-fit: cover; }
.rank-5 .icon-inner { border-color: #ffe699; }
.rank-4 .icon-inner { border-color: #d1bfff; }
</style>
