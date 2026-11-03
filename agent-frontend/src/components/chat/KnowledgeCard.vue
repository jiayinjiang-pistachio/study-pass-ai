<script setup lang="ts">
import { computed, ref } from 'vue'
import { Headset, Picture } from '@element-plus/icons-vue'

const props = defineProps<{
  title: string
  imageUrl: string
  /** 语音讲解地址；未生成音频时为 null */
  audioUrl: string | null
}>()

const audioFailed = ref(false)

const hasImage = computed(() => props.imageUrl.length > 0)
const hasAudio = computed(() => Boolean(props.audioUrl))

function handleAudioError(): void {
  audioFailed.value = true
}
</script>

<template>
  <section class="knowledge-card">
    <header class="knowledge-card__header">
      <span class="knowledge-card__badge">知识卡</span>
      <h3 class="knowledge-card__title">{{ title }}</h3>
    </header>

    <el-image
      v-if="hasImage"
      class="knowledge-card__image"
      :src="imageUrl"
      :preview-src-list="[imageUrl]"
      :preview-teleported="true"
      fit="contain"
      alt="知识卡"
    >
      <template #error>
        <div class="knowledge-card__image-fallback">
          <el-icon><Picture /></el-icon>
          <span>知识卡图片加载失败</span>
        </div>
      </template>
    </el-image>
    <div v-else class="knowledge-card__image-fallback">
      <el-icon><Picture /></el-icon>
      <span>图片暂不可用</span>
    </div>

    <div v-if="hasAudio" class="knowledge-card__audio">
      <span class="knowledge-card__audio-label">
        <el-icon><Headset /></el-icon>
        语音讲解
      </span>
      <audio
        v-if="!audioFailed"
        class="knowledge-card__audio-player"
        controls
        preload="metadata"
        :src="audioUrl ?? undefined"
        @error="handleAudioError"
      ></audio>
      <span v-else class="knowledge-card__audio-tip">音频加载失败</span>
    </div>
  </section>
</template>

<style lang="scss" scoped>
.knowledge-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: min(420px, 100%);
  padding: 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-bubble);
  background: var(--color-surface);

  &__header {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }

  &__badge {
    flex: none;
    padding: 2px 8px;
    border-radius: var(--radius-pill);
    background: var(--color-brand-soft);
    font-size: 12px;
    line-height: 1.6;
    color: var(--color-text);
  }

  &__title {
    min-width: 0;
    margin: 0;
    overflow: hidden;
    font-size: 16px;
    font-weight: 600;
    line-height: 1.5;
    color: var(--color-text);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__image {
    display: block;
    width: 100%;
    height: 400px;
    border-radius: 10px;
    background: var(--color-hover);

    :deep(img) {
      object-fit: contain;
    }
  }

  &__image-fallback {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    height: 180px;
    border: 1px dashed var(--color-border);
    border-radius: 10px;
    background: var(--color-hover);
    font-size: 13px;
    color: var(--color-text-muted);

    .el-icon {
      font-size: 28px;
    }
  }

  &__audio {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding-top: 4px;
    border-top: 1px solid var(--color-divider);
  }

  &__audio-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--color-text-secondary);
  }

  &__audio-player {
    width: 100%;
    height: 36px;
  }

  &__audio-tip {
    font-size: 12px;
    color: var(--color-text-muted);
  }
}

@media (max-width: 480px) {
  .knowledge-card {
    &__image {
      height: 320px;
    }
  }
}
</style>
