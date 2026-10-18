<script setup lang="ts">
withDefaults(defineProps<{ description?: string }>(), {
  description: '暂无数据',
})
</script>

<template>
  <div class="empty-state">
    <el-empty :description="description" :image-size="90" />
  </div>
</template>

<style lang="scss" scoped>
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  min-height: 0;
}
</style>
