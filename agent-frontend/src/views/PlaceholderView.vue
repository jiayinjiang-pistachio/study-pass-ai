<script setup lang="ts">
import { computed } from 'vue'
import type { ModuleKey } from '@/types/conversation'
import { MODULE_LABELS } from '@/types/conversation'

const props = defineProps<{ module: ModuleKey }>()

const label = computed(() => MODULE_LABELS[props.module])
</script>

<template>
  <div class="placeholder">
    <el-empty :description="`${label}功能开发中`" />
  </div>
</template>

<style lang="scss" scoped>
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-height: 0;
}
</style>
