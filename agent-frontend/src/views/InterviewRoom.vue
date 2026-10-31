<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ChatInputBar from '@/components/chat/ChatInputBar.vue'
import { confirmInterview } from '@/api/interview'
import type { AgentTaskResult } from '@/api/conversation'
import { useChatStore } from '@/stores/chat'
import { useConversationStore } from '@/stores/conversation'
import type { InterviewBackground } from '@/types/chat'

function emptyBackground(): InterviewBackground {
  return {
    targetJob: '',
    targetLevel: '',
    yearsExperience: '',
    targetSkills: '',
    projectExperience: '',
    weakTopics: '',
    openingQuestion: '',
  }
}

const chatStore = useChatStore()
const conversationStore = useConversationStore()

const dialogVisible = ref(false)
const confirming = ref(false)
const currentRunId = ref('')
const resumeName = ref('')
const background = reactive<InterviewBackground>(emptyBackground())

/** 接管面试主考官的第一阶段结果：回填背景并弹出确认框，跳过默认会话刷新 */
function handleTaskResult(result: AgentTaskResult): boolean {
  if (result.kind !== 'interview_prepare') return false

  Object.assign(background, emptyBackground(), result.data.background)
  currentRunId.value = result.data.runId
  resumeName.value = result.data.resumeFileName
  dialogVisible.value = true
  return true
}

async function handleConfirm(): Promise<void> {
  if (!currentRunId.value || confirming.value) return

  const runId = currentRunId.value
  confirming.value = true
  try {
    const result = await confirmInterview({
      runId,
      background: { ...background },
    })
    ElMessage.success('面试已创建，请开始作答')
    dialogVisible.value = false

    const sessionId =
      result.sessionId || conversationStore.activeByModule.interview
    if (sessionId) {
      try {
        await chatStore.refresh(sessionId)
      } catch {
        // 刷新失败不影响面试创建，重新进入会话后可看到入口消息
      }
    }
  } catch {
    // 请求层已统一提示错误（404 / 409 等），保留弹窗供用户重试
  } finally {
    confirming.value = false
  }
}

function handleDialogClosed(): void {
  currentRunId.value = ''
  resumeName.value = ''
  Object.assign(background, emptyBackground())
}

function handleCancel(): void {
  dialogVisible.value = false
}
</script>

<template>
  <div class="interview-room">
    <ChatMessageList />
    <ChatInputBar :on-task-result="handleTaskResult" />

    <el-dialog
      v-model="dialogVisible"
      title="确认面试背景"
      width="min(640px, 92vw)"
      append-to-body
      :close-on-click-modal="false"
      :close-on-press-escape="!confirming"
      :show-close="!confirming"
      @closed="handleDialogClosed"
    >
      <p class="interview-confirm__tip">
        请核对并编辑面试背景，确认后将直接进入模拟面试。
        <span v-if="resumeName">（简历：{{ resumeName }}）</span>
      </p>

      <el-form
        class="interview-confirm__form"
        label-position="top"
        :disabled="confirming"
      >
        <div class="interview-confirm__grid">
          <el-form-item label="目标岗位">
            <el-input v-model="background.targetJob" maxlength="100" />
          </el-form-item>
          <el-form-item label="目标职级">
            <el-input v-model="background.targetLevel" maxlength="100" />
          </el-form-item>
          <el-form-item label="工作年限">
            <el-input
              v-model="background.yearsExperience"
              maxlength="100"
              placeholder="如：5 年"
            />
          </el-form-item>
        </div>

        <el-form-item label="已掌握技能">
          <el-input
            v-model="background.targetSkills"
            type="textarea"
            :rows="2"
            maxlength="1000"
            placeholder="多个技能用「、」分隔"
          />
        </el-form-item>
        <el-form-item label="代表性项目经历">
          <el-input
            v-model="background.projectExperience"
            type="textarea"
            :rows="3"
            maxlength="1000"
          />
        </el-form-item>
        <el-form-item label="薄弱点">
          <el-input
            v-model="background.weakTopics"
            type="textarea"
            :rows="2"
            maxlength="1000"
            placeholder="多个薄弱点用「、」分隔"
          />
        </el-form-item>
        <el-form-item label="面试开场问题">
          <el-input
            v-model="background.openingQuestion"
            type="textarea"
            :rows="2"
            maxlength="1000"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button :disabled="confirming" @click="handleCancel">取消</el-button>
        <el-button type="primary" :loading="confirming" @click="handleConfirm">
          确认并开始面试
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
.interview-room {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.interview-confirm {
  &__tip {
    margin: 0 0 16px;
    font-size: 13px;
    line-height: 1.6;
    color: var(--color-text-muted);
  }

  &__form {
    max-height: 60vh;
    overflow-y: auto;
  }

  &__grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 16px;

    @media (max-width: 480px) {
      grid-template-columns: 1fr;
    }
  }
}
</style>
