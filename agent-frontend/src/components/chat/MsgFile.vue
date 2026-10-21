<script setup lang="ts">
import { computed, ref } from 'vue'
import { Document, Headset, Picture } from '@element-plus/icons-vue'
import { SegmentType, type MessageSegment } from '@/types/chat'

const props = defineProps<{ segment: MessageSegment }>()

const audioFailed = ref(false)

const displayName = computed(() => props.segment.name || '未命名附件')
const hasUrl = computed(() => props.segment.url.length > 0)
const isImage = computed(() => props.segment.type === SegmentType.Image)
const isAudio = computed(() => props.segment.type === SegmentType.Audio)

function openFile(): void {
  if (!hasUrl.value) return
  window.open(props.segment.url, '_blank', 'noopener,noreferrer')
}

function handleAudioError(): void {
  audioFailed.value = true
}
</script>

<template>
  <div class="msg-file">
    <template v-if="isImage">
      <el-image
        v-if="hasUrl"
        class="msg-file__image"
        :src="segment.url"
        :preview-src-list="[segment.url]"
        :preview-teleported="true"
        fit="cover"
        alt=""
      >
        <template #error>
          <div class="msg-file__image-fallback">
            <el-icon><Picture /></el-icon>
            <span class="msg-file__image-name text-ellipsis">{{ displayName }}</span>
            <span class="msg-file__image-tip">图片加载失败</span>
          </div>
        </template>
      </el-image>
      <div v-else class="msg-file__image-fallback">
        <el-icon><Picture /></el-icon>
        <span class="msg-file__image-name text-ellipsis">{{ displayName }}</span>
        <span class="msg-file__image-tip">图片不可用</span>
      </div>
    </template>

    <div v-else-if="isAudio" class="msg-file__row">
      <el-icon class="msg-file__icon"><Headset /></el-icon>
      <span class="msg-file__name text-ellipsis">{{ displayName }}</span>
      <audio
        v-if="hasUrl && !audioFailed"
        class="msg-file__audio"
        controls
        preload="metadata"
        :src="segment.url"
        @error="handleAudioError"
      ></audio>
      <span v-else class="msg-file__audio-tip">
        {{ audioFailed ? '音频加载失败' : '音频不可用' }}
      </span>
    </div>

    <div
      v-else
      class="msg-file__row"
      :class="{ 'is-link': hasUrl }"
      :title="hasUrl ? '点击打开附件' : undefined"
      @click="openFile"
    >
      <el-icon class="msg-file__icon"><Document /></el-icon>
      <span class="msg-file__name text-ellipsis">{{ displayName }}</span>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.msg-file {
  &__image {
    display: block;
    width: 180px;
    height: 180px;
    border: 1px solid var(--color-border);
    border-radius: 10px;
    background: var(--color-surface);
    overflow: hidden;
  }

  &__image-fallback {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    width: 180px;
    height: 180px;
    padding: 12px;
    border: 1px dashed var(--color-border);
    border-radius: 10px;
    background: var(--color-hover);
    color: var(--color-text-muted);
    font-size: 13px;

    .el-icon {
      font-size: 28px;
    }
  }

  &__image-name {
    max-width: 100%;
    font-size: 12px;
  }

  &__image-tip {
    font-size: 12px;
  }

  &__row {
    display: flex;
    align-items: center;
    gap: 10px;
    max-width: 100%;
    padding: 10px 14px;
    border: 1px solid var(--color-border);
    border-radius: 10px;
    background: var(--color-surface);

    &.is-link {
      cursor: pointer;

      &:hover {
        border-color: var(--color-brand);
      }
    }
  }

  &__icon {
    flex: none;
    font-size: 20px;
    color: var(--color-text-secondary);
  }

  &__name {
    min-width: 0;
    font-size: 14px;
    color: var(--color-text);
  }

  &__audio {
    flex: none;
    width: 220px;
    height: 36px;
  }

  &__audio-tip {
    flex: none;
    font-size: 12px;
    color: var(--color-text-muted);
  }
}
</style>
