<script setup lang="ts">
import { computed, ref } from 'vue'
import { Paperclip, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const MAX_HEIGHT = 120

const draft = ref('')
const fieldRef = ref<HTMLTextAreaElement | null>(null)

const canSend = computed(() => draft.value.trim().length > 0)

function resize(): void {
  const el = fieldRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
}

function handleAttach(): void {
  ElMessage.info('附件上传功能开发中')
}

function handleSend(): void {
  if (!canSend.value) return
  ElMessage.info('发送功能开发中')
}
</script>

<template>
  <footer class="chat-input">
    <div class="chat-input__box">
      <textarea
        ref="fieldRef"
        v-model="draft"
        class="chat-input__field"
        rows="1"
        placeholder="输入你的回答..."
        @input="resize"
        @keydown.enter.exact.prevent="handleSend"
      ></textarea>

      <div class="chat-input__actions">
        <el-icon class="chat-input__attach" title="上传附件" @click="handleAttach">
          <Paperclip />
        </el-icon>

        <button
          type="button"
          class="chat-input__send"
          :disabled="!canSend"
          title="发送"
          @click="handleSend"
        >
          <el-icon><Promotion /></el-icon>
        </button>
      </div>
    </div>
  </footer>
</template>

<style lang="scss" scoped>
.chat-input {
  flex: none;
  padding: 16px 24px 20px;
  background: var(--color-surface);
  border-top: 1px solid var(--color-divider);

  &__box {
    max-width: var(--content-max-width);
    margin: 0 auto;
    padding: 14px 16px 10px;
    border: 1px solid #e3e3e3;
    border-radius: 14px;
    background: #fff;
    transition: border-color 0.2s;

    &:focus-within {
      border-color: var(--color-brand);
    }
  }

  &__field {
    display: block;
    width: 100%;
    min-height: 24px;
    max-height: 120px;
    border: none;
    outline: none;
    resize: none;
    background: transparent;
    font-family: inherit;
    font-size: 15px;
    line-height: 1.6;
    color: var(--color-text);

    &::placeholder {
      color: var(--color-text-muted);
    }
  }

  &__actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 8px;
  }

  &__attach {
    font-size: 20px;
    color: var(--color-text-muted);
    cursor: pointer;

    &:hover {
      color: var(--color-text);
    }
  }

  &__send {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 50%;
    background: var(--color-brand);
    color: #fff;
    font-size: 18px;
    cursor: pointer;
    transition:
      background-color 0.2s,
      opacity 0.2s;

    &:hover:not(:disabled) {
      background: #eab308;
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }
}
</style>
