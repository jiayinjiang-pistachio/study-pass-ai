<script setup lang="ts">
import { computed, ref } from 'vue'
import { Paperclip, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useCurrentChatModule } from '@/composables/useCurrentModule'
import { useChatStore } from '@/stores/chat'
import { useConversationStore } from '@/stores/conversation'

const MAX_HEIGHT = 120

const chatStore = useChatStore()
const conversationStore = useConversationStore()
const module = useCurrentChatModule()

const draft = ref('')
const fieldRef = ref<HTMLTextAreaElement | null>(null)

const sessionId = computed(() =>
  module.value ? conversationStore.activeByModule[module.value] : null,
)
const sending = computed(
  () => sessionId.value !== null && chatStore.isSending(sessionId.value),
)
const canSend = computed(
  () => draft.value.trim().length > 0 && !sending.value,
)

function resize(): void {
  const el = fieldRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
}

function handleAttach(): void {
  ElMessage.info('附件上传功能开发中')
}

async function handleSend(): Promise<void> {
  if (!canSend.value || !module.value) return

  const id = conversationStore.activeByModule[module.value]
  if (id === null) {
    ElMessage.warning('请先在左侧新建会话')
    return
  }

  const text = draft.value.trim()
  draft.value = ''
  resize()

  try {
    await chatStore.sendMessage(id, text)
  } catch (error) {
    ElMessage.error(
      error instanceof Error ? error.message : '发送失败，请稍后重试',
    )
  }
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
        :placeholder="sending ? 'AI 正在回复…' : '输入你的回答...'"
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
