<script setup lang="ts">
import { computed, ref } from 'vue'
import { Paperclip, Promotion, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { UploadFile, UploadInstance } from 'element-plus'
import type { AgentTaskResult } from '@/api/conversation'
import { DocCategory, uploadFile } from '@/api/file'
import { useCurrentChatModule } from '@/composables/useCurrentModule'
import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { useConversationStore } from '@/stores/conversation'
import { AGENTS_BY_MODULE } from '@/types/agent'
import type { AgentName } from '@/types/agent'

const props = defineProps<{
  /** 工作流 JSON 结果回调；返回 true 表示页面已接管，跳过默认会话刷新 */
  onTaskResult?: (result: AgentTaskResult) => boolean
}>()

const MAX_HEIGHT = 120
const MAX_DOC_SIZE = 10 * 1024 * 1024
const DOC_EXTENSIONS = ['.pdf', '.doc', '.docx', '.txt']
const DOC_CATEGORY_OPTIONS: Array<{ label: string; value: DocCategory }> = [
  { label: '简历', value: DocCategory.Resume },
  { label: '学习资料', value: DocCategory.StudyMaterial },
  { label: '通用文档', value: DocCategory.General },
]

const chatStore = useChatStore()
const conversationStore = useConversationStore()
const agentStore = useAgentStore()
const module = useCurrentChatModule()

const draft = ref('')
const fieldRef = ref<HTMLTextAreaElement | null>(null)

const dialogVisible = ref(false)
const uploadRef = ref<UploadInstance>()
const selectedFile = ref<File | null>(null)
const docCategory = ref<DocCategory | ''>('')
const submitting = ref(false)

const sessionId = computed(() =>
  module.value ? conversationStore.activeByModule[module.value] : null,
)
const sending = computed(
  () => sessionId.value !== null && chatStore.isSending(sessionId.value),
)
const agentOptions = computed(() =>
  module.value ? AGENTS_BY_MODULE[module.value] : [],
)
const selectedAgent = computed(() =>
  module.value ? agentStore.selectedByModule[module.value] : null,
)
const canSend = computed(
  () => draft.value.trim().length > 0 && !sending.value,
)
const canSubmit = computed(
  () => selectedFile.value !== null && docCategory.value !== '' && !submitting.value,
)

function resize(): void {
  const el = fieldRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
}

function resetUpload(): void {
  uploadRef.value?.clearFiles()
  selectedFile.value = null
  docCategory.value = ''
  submitting.value = false
}

function handleAttach(): void {
  dialogVisible.value = true
}

function validateFile(file: File): boolean {
  const name = file.name.toLowerCase()
  if (!DOC_EXTENSIONS.some((suffix) => name.endsWith(suffix))) {
    ElMessage.error('仅支持 PDF / DOC / DOCX / TXT 文档')
    return false
  }
  if (file.size > MAX_DOC_SIZE) {
    ElMessage.error('文档不能超过 10MB')
    return false
  }
  return true
}

function handleFileChange(file: UploadFile): void {
  const raw = file.raw
  if (!raw) {
    selectedFile.value = null
    return
  }
  if (!validateFile(raw)) {
    uploadRef.value?.clearFiles()
    selectedFile.value = null
    return
  }
  selectedFile.value = raw
}

function handleFileRemove(): void {
  selectedFile.value = null
}

function handleExceed(): void {
  ElMessage.warning('一次只能上传一个文档，请先移除已选文件')
}

async function handleSubmit(): Promise<void> {
  const file = selectedFile.value
  const category = docCategory.value
  if (!file || category === '' || submitting.value) return

  submitting.value = true
  try {
    const result = await uploadFile(file, { docCategory: category })
    ElMessage.success(result.reused ? '文件已存在，已复用' : '文档上传成功')
    dialogVisible.value = false
  } catch {
    // 请求层已统一提示错误，这里不重复弹出
  } finally {
    submitting.value = false
  }
}

function handleToggleAgent(name: AgentName): void {
  if (!module.value) return
  agentStore.toggle(module.value, name)
}

async function handleSend(): Promise<void> {
  if (!canSend.value || !module.value) return

  const currentModule = module.value
  const id = conversationStore.activeByModule[currentModule]
  if (id === null) {
    ElMessage.warning('请先在左侧新建会话')
    return
  }

  const text = draft.value.trim()
  draft.value = ''
  resize()

  try {
    await chatStore.sendMessage(id, text, agentStore.effective(currentModule), {
      onTaskResult: props.onTaskResult,
    })
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
        :placeholder="sending ? '正在处理，请稍候…' : '输入你的回答...'"
        @input="resize"
        @keydown.enter.exact.prevent="handleSend"
      ></textarea>

      <div v-if="agentOptions.length" class="chat-input__agents">
        <button
          v-for="option in agentOptions"
          :key="option.name"
          type="button"
          class="chat-input__agent"
          :class="{ 'is-active': selectedAgent === option.name }"
          :aria-pressed="selectedAgent === option.name"
          :disabled="sending"
          @click="handleToggleAgent(option.name)"
        >
          {{ option.label }}
        </button>
      </div>

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

  <el-dialog
    v-model="dialogVisible"
    title="上传文档"
    width="min(520px, 92vw)"
    append-to-body
    :close-on-click-modal="false"
    @closed="resetUpload"
  >
    <div class="doc-upload">
      <el-upload
        ref="uploadRef"
        class="doc-upload__drop"
        drag
        :auto-upload="false"
        :limit="1"
        :multiple="false"
        accept=".pdf,.doc,.docx,.txt"
        :on-change="handleFileChange"
        :on-remove="handleFileRemove"
        :on-exceed="handleExceed"
      >
        <el-icon class="doc-upload__icon"><UploadFilled /></el-icon>
        <div class="doc-upload__text">
          将文档拖到此处，或 <em>点击选择</em>
        </div>
        <template #tip>
          <div class="doc-upload__tip">
            支持 PDF / DOC / DOCX / TXT，单个文件不超过 10MB
          </div>
        </template>
      </el-upload>

      <div class="doc-upload__field">
        <span class="doc-upload__label">文档类型</span>
        <el-select
          v-model="docCategory"
          class="doc-upload__select"
          placeholder="请选择文档类型"
        >
          <el-option
            v-for="option in DOC_CATEGORY_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </div>
    </div>

    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button
        type="primary"
        :disabled="!canSubmit"
        :loading="submitting"
        @click="handleSubmit"
      >
        提交
      </el-button>
    </template>
  </el-dialog>
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

  &__agents {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 10px;
  }

  &__agent {
    padding: 4px 12px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-pill);
    background: var(--color-surface);
    font-size: 12px;
    line-height: 1.6;
    color: var(--color-text-secondary);
    cursor: pointer;
    transition:
      color 0.2s,
      border-color 0.2s,
      background-color 0.2s;

    &:hover:not(:disabled) {
      border-color: var(--color-brand);
      color: var(--color-text);
    }

    &.is-active {
      border-color: var(--color-brand);
      background: var(--color-brand-soft);
      color: var(--color-text);
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
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

.doc-upload {
  &__drop {
    :deep(.el-upload-dragger) {
      padding: 26px 16px;
    }
  }

  &__icon {
    font-size: 42px;
    color: var(--color-text-muted);
  }

  &__text {
    margin-top: 8px;
    font-size: 14px;
    color: var(--color-text-secondary);

    em {
      font-style: normal;
      color: var(--color-brand);
    }
  }

  &__tip {
    margin-top: 8px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--color-text-muted);
    text-align: center;
  }

  &__field {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 18px;
  }

  &__label {
    flex: none;
    font-size: 14px;
    color: var(--color-text);
  }

  &__select {
    flex: 1;
  }
}
</style>
