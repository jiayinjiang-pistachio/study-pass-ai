<script setup lang="ts">
/**
 * RTC 语音面试页：负责入房、麦克风采集 / 音频发布、AI 音频订阅、字幕接收与挂断收尾。
 *
 * RTC 参数由确认接口返回，经路由 history state 传入（token 不进入 URL）：
 *   /interview/voice?interview_id=123  +  history.state.voice
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Loading,
  Microphone,
  PhoneFilled,
  WarningFilled,
} from '@element-plus/icons-vue'
import VERTC, { MediaType, RoomProfileType } from '@volcengine/rtc'
import type { IRTCEngine } from '@volcengine/rtc'
import { finishVoiceInterview } from '@/api/interview'
import type { VoiceRoom } from '@/types/chat'
import { ModuleKey } from '@/types/conversation'
import { useAutoScroll } from '@/composables/useAutoScroll'
import {
  applySubtitleItems,
  buildQaObject,
  createSubtitleState,
  formatDuration,
  normalizeVoiceRoom,
  parseSubtitleMessage,
} from '@/utils/voiceInterview'
import type {
  VoiceSubtitleLine,
  VoiceSubtitleState,
} from '@/utils/voiceInterview'

type VoicePageStatus = 'preparing' | 'joining' | 'connected' | 'finished' | 'error'

const route = useRoute()
const router = useRouter()

const interviewId = computed(() => {
  const raw = route.query.interview_id
  const value = Array.isArray(raw) ? raw[0] : raw
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0
})

/** voice 通过 history state 传入，刷新页面后仍可读取；不落在 URL 上 */
const voice = ref<VoiceRoom | null>(readVoiceFromHistory())
const status = ref<VoicePageStatus>('preparing')
const errorMessage = ref('')
const elapsed = ref(0)
const hangingUp = ref(false)
const audioBlocked = ref(false)
const subtitleState = ref<VoiceSubtitleState>(createSubtitleState())

const containerRef = ref<HTMLElement | null>(null)
const { scrollToBottom } = useAutoScroll(containerRef, () => subtitleState.value)

let engine: IRTCEngine | null = null
let durationTimer: number | null = null
let startedAt = 0

const displayLines = computed<VoiceSubtitleLine[]>(() => {
  const lines = subtitleState.value.lines.slice()
  const { ai, me } = subtitleState.value.partial
  if (ai) lines.push({ id: -1, speaker: 'ai', text: ai })
  if (me) lines.push({ id: -2, speaker: 'me', text: me })
  return lines
})

const statusText = computed(() => {
  switch (status.value) {
    case 'preparing':
      return '正在准备语音环境…'
    case 'joining':
      return '正在连接 AI 面试官…'
    case 'connected':
      return '通话中，麦克风已开启'
    case 'finished':
      return '正在保存面试结果…'
    default:
      return '连接失败'
  }
})

function readVoiceFromHistory(): VoiceRoom | null {
  const state = window.history.state as { voice?: unknown } | null
  return normalizeVoiceRoom(state?.voice)
}

function setError(message: string): void {
  errorMessage.value = message
  status.value = 'error'
}

function startTimer(): void {
  stopTimer()
  elapsed.value = 0
  durationTimer = window.setInterval(() => {
    elapsed.value = Math.floor((Date.now() - startedAt) / 1000)
  }, 1000)
}

function stopTimer(): void {
  if (durationTimer !== null) {
    window.clearInterval(durationTimer)
    durationTimer = null
  }
}

async function subscribeBotAudio(): Promise<void> {
  const current = engine
  const botId = voice.value?.botId
  if (!current || !botId) return
  try {
    await current.subscribeStream(botId, MediaType.AUDIO)
    console.info('[voice] 已订阅 AI 音频', botId)
  } catch (error) {
    // 进房时已开启自动订阅，这里失败不阻断通话
    console.warn('[voice] 订阅 AI 音频失败（自动订阅可能已生效）', error)
  }
}

function handleBinaryMessage(event: { userId: string; message: ArrayBuffer }): void {
  const currentVoice = voice.value
  if (!currentVoice) return

  const items = parseSubtitleMessage(event.message)
  if (!items.length) return

  subtitleState.value = applySubtitleItems(
    subtitleState.value,
    items,
    currentVoice.userId,
    currentVoice.botId,
  )
}

function handleUserJoined(event: { userInfo: { userId: string } }): void {
  if (event.userInfo.userId !== voice.value?.botId) return
  console.info('[voice] AI 面试官已进房')
  void subscribeBotAudio()
}

function handleUserPublishStream(event: {
  userId: string
  mediaType: MediaType
}): void {
  if (event.userId !== voice.value?.botId) return
  if (
    event.mediaType !== MediaType.AUDIO &&
    event.mediaType !== MediaType.AUDIO_AND_VIDEO
  ) {
    return
  }
  void subscribeBotAudio()
}

function handleEngineError(event: { errorCode: string }): void {
  console.error('[voice] RTC 回调错误', event.errorCode)
  setError('语音连接异常，请返回后重新发起面试')
  void releaseRtc()
}

/** 浏览器自动播放策略可能拦截 AI 音频，需用户点击后恢复播放 */
function handleAutoplayFailed(event: { userId: string; kind: 'audio' | 'video' }): void {
  if (event.kind !== 'audio') return
  console.warn('[voice] 浏览器拦截了 AI 音频自动播放', event.userId)
  audioBlocked.value = true
}

async function resumeAudio(): Promise<void> {
  const current = engine
  const botId = voice.value?.botId
  if (!current || !botId) return
  try {
    await current.play(botId, MediaType.AUDIO)
    audioBlocked.value = false
  } catch (error) {
    console.warn('[voice] 开启 AI 音频失败', error)
    ElMessage.warning('开启声音失败，请检查浏览器播放权限')
  }
}

function bindEvents(rtcEngine: IRTCEngine): void {
  rtcEngine.on(VERTC.events.onRoomBinaryMessageReceived, handleBinaryMessage)
  rtcEngine.on(VERTC.events.onUserJoined, handleUserJoined)
  rtcEngine.on(VERTC.events.onUserPublishStream, handleUserPublishStream)
  rtcEngine.on(VERTC.events.onAutoplayFailed, handleAutoplayFailed)
  rtcEngine.on(VERTC.events.onError, handleEngineError)
}

function unbindEvents(rtcEngine: IRTCEngine): void {
  rtcEngine.off(VERTC.events.onRoomBinaryMessageReceived, handleBinaryMessage)
  rtcEngine.off(VERTC.events.onUserJoined, handleUserJoined)
  rtcEngine.off(VERTC.events.onUserPublishStream, handleUserPublishStream)
  rtcEngine.off(VERTC.events.onAutoplayFailed, handleAutoplayFailed)
  rtcEngine.off(VERTC.events.onError, handleEngineError)
}

/** 释放 RTC 资源：停采集 → 取消发布 → 退房 → 解绑事件 → 销毁引擎 */
async function releaseRtc(): Promise<void> {
  const current = engine
  if (!current) return
  engine = null

  try {
    await current.stopAudioCapture()
  } catch (error) {
    console.warn('[voice] 停止麦克风采集失败', error)
  }
  try {
    await current.unpublishStream(MediaType.AUDIO)
  } catch (error) {
    console.warn('[voice] 取消发布音频失败', error)
  }
  try {
    await current.leaveRoom()
  } catch (error) {
    console.warn('[voice] 退出房间失败', error)
  }

  unbindEvents(current)
  try {
    VERTC.destroyEngine(current)
  } catch (error) {
    console.warn('[voice] 销毁 RTC 引擎失败', error)
  }
}

async function joinRoom(): Promise<void> {
  const currentVoice = voice.value
  const currentInterviewId = interviewId.value
  if (!currentInterviewId || !currentVoice) {
    setError('缺少面试参数，请返回面试间重新发起')
    return
  }
  if (!currentVoice.started) {
    setError('AI 面试官未能启动，请返回后重新发起面试')
    return
  }

  status.value = 'joining'
  try {
    const devices = await VERTC.enableDevices({ video: false, audio: true })
    if (!devices.audio) {
      setError('未获得麦克风权限，请允许录音后重试')
      return
    }

    const rtcEngine = VERTC.createEngine(currentVoice.appId)
    engine = rtcEngine
    bindEvents(rtcEngine)

    await rtcEngine.joinRoom(
      currentVoice.rtcToken,
      currentVoice.roomId,
      { userId: currentVoice.userId },
      {
        // 手动发布音频，确保采集成功后再发流；AI 音频自动订阅兜底
        isAutoPublish: false,
        isAutoSubscribeAudio: true,
        isAutoSubscribeVideo: false,
        roomProfileType: RoomProfileType.chat,
      },
    )
    await rtcEngine.startAudioCapture()
    await rtcEngine.publishStream(MediaType.AUDIO)

    startedAt = Date.now()
    status.value = 'connected'
    startTimer()
    scrollToBottom('auto')
    console.info('[voice] 已进入语音面试房间', {
      interviewId: currentInterviewId,
      roomId: currentVoice.roomId,
    })
  } catch (error) {
    console.error('[voice] 进入语音面试失败', error)
    setError(
      error instanceof Error ? error.message : '进入语音面试失败，请稍后重试',
    )
    await releaseRtc()
  }
}

async function handleHangUp(): Promise<void> {
  if (hangingUp.value || status.value === 'finished') return

  hangingUp.value = true
  status.value = 'finished'
  stopTimer()

  const currentInterviewId = interviewId.value
  const duration = startedAt
    ? Math.max(1, Math.round((Date.now() - startedAt) / 1000))
    : 1
  const qaObject = buildQaObject(subtitleState.value)

  // 先释放本地资源，避免保存接口等待期间继续占用麦克风
  await releaseRtc()

  try {
    if (currentInterviewId) {
      await finishVoiceInterview(currentInterviewId, {
        qaObject,
        interviewDuration: duration,
      })
      console.info('[voice] 语音面试已结束', {
        interviewId: currentInterviewId,
        qaCount: qaObject.length,
        duration,
      })
      ElMessage.success('面试已结束')
    }
  } catch (error) {
    // 请求层已统一提示错误；本地资源已释放，这里只补充说明
    console.error('[voice] 保存面试结果失败', error)
    ElMessage.warning('通话已结束，但面试结果保存失败')
  } finally {
    hangingUp.value = false
    await router.replace({ name: ModuleKey.Interview })
  }
}

function backToInterview(): void {
  void router.replace({ name: ModuleKey.Interview })
}

onMounted(() => {
  void joinRoom()
})

onBeforeUnmount(() => {
  stopTimer()
  void releaseRtc()
})
</script>

<template>
  <div class="voice-page">
    <header class="voice-page__header">
      <div class="voice-page__heading">
        <h1 class="voice-page__title">AI 模拟面试</h1>
        <p class="voice-page__subtitle">
          <template v-if="interviewId">面试编号 #{{ interviewId }}</template>
          <template v-else>语音面试</template>
        </p>
      </div>
      <div class="voice-page__timer">{{ formatDuration(elapsed) }}</div>
    </header>

    <main ref="containerRef" class="voice-page__subtitles">
      <div v-if="status === 'error'" class="voice-page__state">
        <el-icon class="voice-page__state-icon"><WarningFilled /></el-icon>
        <p>{{ errorMessage }}</p>
        <el-button type="primary" @click="backToInterview">返回面试间</el-button>
      </div>

      <template v-else>
        <div
          v-if="!displayLines.length && status !== 'connected'"
          class="voice-page__state"
        >
          <el-icon class="is-loading voice-page__state-icon"><Loading /></el-icon>
          <p>{{ statusText }}</p>
        </div>

        <div
          v-for="line in displayLines"
          :key="line.id"
          class="voice-line"
          :class="`voice-line--${line.speaker}`"
        >
          <span class="voice-line__speaker">
            {{ line.speaker === 'ai' ? 'AI' : '我' }}
          </span>
          <p class="voice-line__text">{{ line.text }}</p>
        </div>
      </template>
    </main>

    <footer class="voice-page__footer">
      <div class="voice-page__status">
        <el-icon v-if="status === 'connected'" class="voice-page__mic">
          <Microphone />
        </el-icon>
        <span>{{ statusText }}</span>
      </div>

      <div class="voice-page__actions">
        <el-button
          v-if="audioBlocked && status === 'connected'"
          type="primary"
          size="large"
          round
          @click="resumeAudio"
        >
          <el-icon><Microphone /></el-icon>
          开启声音
        </el-button>

        <el-button
          v-if="status === 'connected'"
          type="danger"
          size="large"
          round
          :loading="hangingUp"
          @click="handleHangUp"
        >
          <el-icon v-if="!hangingUp"><PhoneFilled /></el-icon>
          挂断面试
        </el-button>
      </div>
    </footer>
  </div>
</template>

<style lang="scss" scoped>
.voice-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  min-height: 0;
  background: var(--color-bg-page);
}

.voice-page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}

.voice-page__title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text);
}

.voice-page__subtitle {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

.voice-page__timer {
  font-variant-numeric: tabular-nums;
  font-size: 20px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.voice-page__subtitles {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
  max-width: var(--content-max-width, 760px);
  margin: 0 auto;
  padding: 24px;
  box-sizing: border-box;
}

.voice-page__state {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 240px;
  font-size: 14px;
  color: var(--color-text-muted);
  text-align: center;

  p {
    margin: 0;
  }
}

.voice-page__state-icon {
  font-size: 28px;
  color: var(--color-brand);
}

.voice-line {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 80%;

  &--ai {
    align-self: flex-start;
    align-items: flex-start;
  }

  &--me {
    align-self: flex-end;
    align-items: flex-end;
  }
}

.voice-line__speaker {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.voice-line__text {
  margin: 0;
  padding: 10px 14px;
  border-radius: var(--radius-bubble, 12px);
  background: var(--color-surface);
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--color-text);

  .voice-line--me & {
    background: var(--color-bubble-user);
  }
}

.voice-page__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 24px calc(16px + env(safe-area-inset-bottom));
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
}

.voice-page__status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--color-text-muted);
}

.voice-page__actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.voice-page__mic {
  font-size: 16px;
  color: var(--color-accent);
}

@media (max-width: 768px) {
  .voice-page__subtitles {
    padding: 16px;
  }

  .voice-page__header,
  .voice-page__footer {
    padding-left: 16px;
    padding-right: 16px;
  }
}
</style>
