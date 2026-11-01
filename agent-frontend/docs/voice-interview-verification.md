# RTC 语音面试 · 前端页面验证指南

> **状态**：已实现并验证通过（2026-11-01，分支 `interview-rtc`）
> **范围**：面试背景确认（两阶段）→ 创建正式面试 → 进入 RTC 语音面试页 → 实时字幕 → 挂断落库
> **前置文档**：面试准备两阶段流程见 [`interview-host-verification-guide.md`](../../agent-backend/docs/interview-host-verification-guide.md)
> **最后更新**：2026-11-01

本文只描述**如何通过前端页面操作**验证语音面试功能，不重复接口细节。

---

## 1. 启动环境

### 1.1 后端（默认 8000）

```bash
cd agent-backend
source .venv/bin/activate
uvicorn app.main:app --reload --reload-exclude 'logs/*' --port 8000
```

`.env.dev` 需配置：

| 变量 | 必需 | 用途 |
| --- | --- | --- |
| `MYSQL_URL` | 是 | 面试记录、会话消息 |
| `JWT_SECRET` | 是 | 登录令牌 |
| `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | 是 | 面试准备与面试官对话（缺失时准备流程失败） |
| `VOLC_RTC_APP_ID` / `VOLC_RTC_APP_KEY` | 是 | RTC 入房参数与 `StartVoiceChat`；缺失时 `voice.started=false` |
| `VOLC_RTC_TTS_SPEAKER` | 否 | AI 音色，缺省使用 RTC 配置的默认音色 |
| `VOLC_RTC_TTS_APP_ID` / `VOLC_RTC_TTS_ACCESS_TOKEN` | 否 | 仅当 TTS 使用独立账号时填写 |
| `VOLC_RTC_ASR_APP_ID` / `VOLC_RTC_ASR_ACCESS_TOKEN` | 否 | 仅当 ASR 使用独立账号时填写；不填时按 `Mode=bigmodel` 走默认 ASR |
| `VOLC_RTC_VAD_SILENCE_TIME_MS` | 否 | 判停静音时长（毫秒，`[500,3000)`），默认 `1500`；值越大 AI 越晚接话 |
| `VOLC_RTC_AIVAD` | 否 | 语义判停，默认 `true`；语义不完整时最多等到静音 2 秒，减少思考停顿被误判 |
| `VOLC_RTC_WELCOME_MESSAGE` | 否 | AI 开场白，默认「你好，我是本场面试的 AI 面试官，我们现在开始。」 |
| `VOLC_RTC_HISTORY_LENGTH` | 否 | 对话上下文轮数，默认 10 |
| `VOLC_RTC_IDLE_TIMEOUT` | 否 | 空闲超时（秒），默认 180 |
| `VOLC_RTC_TOKEN_TTL_SECONDS` | 否 | RTC Token 有效期 |

> RTC 未配置或 `StartVoiceChat` 调用失败**不会阻断**面试确认：接口仍返回 `interview_id`，但 `voice.started=false`，
> 前端提示「面试已创建，但 AI 语音面试未能启动」，用户留在面试间。

### 1.2 前端

```bash
cd agent-frontend
pnpm install
pnpm dev          # 默认 5173，代理 /api → http://127.0.0.1:8000
```

打开 `http://localhost:5173/login` 并登录。

> 麦克风采集要求**安全上下文**：`localhost` / `127.0.0.1` 或 HTTPS 均可；通过局域网 IP + HTTP 访问时浏览器会拒绝 `getUserMedia`。

---

## 2. 验证项清单

### 2.1 面试背景确认与跳转

| # | 操作 | 预期 |
| --- | --- | --- |
| 1 | 面试间进入一个已有简历的会话，发送「帮我准备高级后端开发工程师的模拟面试」 | 总控返回 `interview_prepare`，弹出「确认面试背景」弹窗 |
| 2 | 查看弹窗 | 7 个字段（目标岗位 / 职级 / 年限 / 技能 / 项目 / 薄弱点 / 开场问题）已按简历与用户画像预填，顶部显示简历文件名 |
| 3 | 修改任意字段后点击「确认并开始面试」 | `POST /api/interviews/confirm` 返回 200，页面跳转语音面试页 |
| 4 | 查看地址栏 | `…/interview/voice?interview_id={id}`；**`rtc_token` 不出现在 URL** |
| 5 | DevTools → Network 查看 confirm 响应 | `data.voice` 含 `app_id / room_id / user_id / bot_user_id / task_id / token / expire_at / started=true` |
| 6 | 在语音页刷新浏览器 | 仍能自动入房（`voice` 保存在 `history.state`，刷新后保留） |
| 7 | 直接访问 `/interview/voice?interview_id={id}`（无 state） | 显示「缺少面试参数，请返回面试间重新发起」，不发起 RTC 连接 |
| 8 | 后端未配置 RTC 时重复步骤 3 | 提示「面试已创建，但 AI 语音面试未能启动」，页面停留在面试间 |

> `voice` 入参同时兼容后端 `bot_user_id / token` 与前端 `botId / rtcToken` 命名；核心字段缺失时 `normalizeVoiceRoom` 返回 `null`，按缺少参数处理。

### 2.2 入房与音频

| # | 操作 | 预期 |
| --- | --- | --- |
| 9 | 进入语音页 | 状态依次为「正在准备语音环境…」→「正在连接 AI 面试官…」→「通话中，麦克风已开启」 |
| 10 | 首次进入时浏览器弹出麦克风授权 | 允许后正常入房；拒绝则显示「未获得麦克风权限，请允许录音后重试」 |
| 11 | 观察 Console | 依次出现「AI 面试官已进房」「已订阅 AI 音频 {botId}」「已进入语音面试房间」 |
| 12 | 对麦克风说话 | 能听到 AI 面试官语音；左下角显示麦克风图标与通话状态 |
| 13 | 若浏览器拦截自动播放 | 显示「开启声音」按钮，点击后 AI 音频恢复播放 |
| 14 | 观察计时器 | 入房后从 `00:00` 开始递增 |

> 页面采用手动发布：`joinRoom` 后先 `startAudioCapture` 再 `publishStream(AUDIO)`；
> 同时开启 `isAutoSubscribeAudio`，并额外在 `onUserJoined` / `onUserPublishStream` 中订阅 bot 音频兜底。

### 2.3 实时字幕

| # | 操作 | 预期 |
| --- | --- | --- |
| 15 | AI 开始说话 | 左侧出现「AI」字幕，按句增量刷新，句子完成后固定为一行 |
| 16 | 对麦克风说话 | 右侧出现「我」字幕，段落完成后固定为一行 |
| 17 | 连续多轮问答 | 字幕区自动滚动到底部，AI / 我 左右分列 |
| 18 | 观察说话人识别 | 「AI」「我」由 `voice.bot_id` / `voice.user_id` 判定，无硬编码 bot_id；未知 userId 的消息被忽略 |

> 字幕来自 RTC 房间二进制消息：4 字节 ASCII 类型 `subv` + 4 字节大端长度 + UTF-8 JSON。
> AI 以 `definite`、用户以 `paragraph` 判断完成；未完成半句覆盖显示，已完成句子追加，避免文本回退与重复。

### 2.4 挂断与落库

| # | 操作 | 预期 |
| --- | --- | --- |
| 19 | 点击「挂断面试」 | 按钮进入加载态，状态变为「正在保存面试结果…」，计时停止 |
| 20 | DevTools → Network | 先释放本地 RTC，再 `POST /api/interviews/{id}/voice/finish`，body 含 `qa_object` 与 `interview_duration` |
| 21 | 请求成功 | 提示「面试已结束」，自动返回 `/interview` |
| 22 | `GET /api/interviews/{id}` | `status=1`、`interview_duration>0`、`qa_object` 非空 |
| 23 | 检查 `qa_object` | 连续 AI 字幕合并为 `question`，连续用户字幕合并为 `answer`，未说完的半句也会纳入 |
| 24 | 模拟保存接口失败（如断网） | 提示「通话已结束，但面试结果保存失败」；RTC 资源已释放，仍返回面试间 |

### 2.5 异常与资源释放

| # | 操作 | 预期 |
| --- | --- | --- |
| 25 | 通话中点击浏览器返回 / 路由离开 | `onBeforeUnmount` 停止计时并释放 RTC（停采集 / 取消发布 / 退房 / 销毁引擎） |
| 26 | 模拟 RTC 错误回调 | 页面进入错误态，显示「语音连接异常，请返回后重新发起面试」，同时释放 RTC |
| 27 | 通话中关闭标签页 | 本地资源随页面销毁；后端记录保持 `status=0`，RTC 任务在 `VOLC_RTC_IDLE_TIMEOUT` 后自动停止（见 §5） |

---

## 3. 自动化验证结果（2026-11-01）

**方法**：Chrome 156 无头模式 + CDP 驱动真实前端页面；通过 `--use-file-for-fake-audio-capture` 注入 48 kHz 16-bit WAV 模拟麦克风（实测 `getUserMedia` RMS 0.28，音轨正常），全程未调用接口绕过页面。

| 验证项 | 结果 |
| --- | --- |
| 面试间发送准备要求 | `POST /api/agent/tasks/start` 返回 200，自动弹出「确认面试背景」 |
| 确认弹窗预填 | 7 个字段全部按简历回填，显示简历 `resume.txt` |
| 确认并跳转 | `POST /api/interviews/confirm` 200；`interview_id=186`；URL `/interview/voice?interview_id=186` |
| token 位置 | URL 中无 token，`history.state.voice` 保存 RTC 参数 |
| 自动入房 | 约 1 秒内状态变为「通话中，麦克风已开启」，计时器启动 |
| bot 音频订阅 | Console：`AI 面试官已进房`、`已订阅 AI 音频 aiinterviewer186` |
| AI 字幕 | 完整显示「你好，我是本场面试的 AI 面试官，我们现在开始。」 |
| 用户字幕（ASR） | 10 秒内显示「高级后端开发工程师，我有5年的 Java 后端开发经验，主要做过高并发订单系统」 |
| 挂断接口 | `POST /api/interviews/186/voice/finish` 返回 200，随后返回 `/interview` |
| 落库结果 | `status=1`、`interview_duration=11`、`qa_object` 含 1 组问答（question 为 AI 开场，answer 为上述用户回答） |
| RTC 停止 | 后端日志出现 `AI 面试官已停止`（`interview_id=186`） |
| 类型检查 / 构建 | `pnpm build`（`vue-tsc -b && vite build`）通过；语音页为独立异步 chunk（约 2.05 MB / gzip 627 KB） |

另做一轮直接注入 `history.state` 的页面验证（`interview_id=184`）：自动入房、AI 字幕、32 秒挂断、`status=1 / duration=32 / qa_object` 非空，证明刷新与直接进入语音页的路径可用。

截图保存在本地 `/tmp/voice-ui2-*.png`（未提交仓库）：确认弹窗、通话中、双人字幕、返回面试间。

---

## 4. 请求链路速查

| 场景 | 请求 | 关键响应 |
| --- | --- | --- |
| 第一阶段：面试准备 | `POST /api/agent/tasks/start`，body `{agent_name:"interview_host", session_id, request_text}` | JSON：`run_id / status=pending_confirmation / background / resume` |
| 第二阶段：确认背景 | `POST /api/interviews/confirm`，body `{run_id, background:{target_job, …}}` | `interview_id / session_id / message_id / voice{app_id, room_id, user_id, bot_user_id, task_id, token, expire_at, started}` |
| 挂断保存 | `POST /api/interviews/{id}/voice/finish`，body `{qa_object:[{id, question, answer, created_at}], interview_duration}` | `interview_id / status / interview_duration / qa_count` |
| 查看结果 | `GET /api/interviews/{id}` | `status=1 / interview_duration / qa_object` |

前端落点：

- `InterviewRoom.vue`：接管 `interview_prepare` 结果 → 弹窗确认 → `router.push({name:'interview-voice', query, state:{voice}})`。
- `VoiceInterviewPage.vue`：RTC 生命周期、字幕订阅、挂断收尾。
- `utils/voiceInterview.ts`：TLV 解析、字幕合并、`qa_object` 构建、`voice` 参数归一化。
- 路由：`/interview/voice` 为全屏页，不套 `AppShell`。

---

## 5. 已知限制与排查

| 现象 | 原因 / 处理 |
| --- | --- |
| 确认后未跳转，提示「AI 语音面试未能启动」 | `.env.dev` 缺少 `VOLC_RTC_APP_ID / APP_KEY`，或 `StartVoiceChat` 调用失败；查看后端日志 `AI 面试官已启动 / 启动 RTC AI 面试官失败` |
| 没有「我」的字幕 | 麦克风未授权 / 浏览器未使用安全上下文；或 RTC 控制台账号需要独立 ASR 凭证（填 `VOLC_RTC_ASR_*`） |
| 听不到 AI 声音 | 浏览器自动播放策略；点击页面上的「开启声音」，或使用支持自动播放的浏览器设置 |
| AI 在用户思考停顿时就接话 | 调大 `VOLC_RTC_VAD_SILENCE_TIME_MS`（如 2000）并保持 `VOLC_RTC_AIVAD=true`；修改后重启后端 |
| 通话一段时间后 AI 自动退出 | RTC 空闲超时（`VOLC_RTC_IDLE_TIMEOUT`，默认 180 秒）；需重新确认发起面试 |
| 刷新页面后无法入房 | 仅当 `history.state.voice` 丢失（如直接从书签打开）时发生；从面试间重新确认即可 |
| 关闭标签页后面试记录一直为 `status=0` | 当前仅「挂断面试」会调用 finish；关闭页面只释放本地 RTC。后端靠 RTC 空闲超时停止 bot，记录需后续补充自动收尾（已知缺口） |
| `qa_object` 的 `answer` 为空 | 用户在 AI 说话期间未发声，或触发挂断过早；属正常数据，不视为功能错误 |

---

## 6. 结论

- 主链路闭环已通过真实页面验证：确认背景 → 创建面试 → 入房 → AI 音频 / 双向字幕 → 挂断 → 落库（`status=1`、时长、`qa_object`）。
- 前端类型检查与生产构建通过。
- 已知缺口：**未挂断直接关闭页面不会调用 finish**，面试记录会停留在 `status=0`，需要后续补「离开页面自动收尾 / 后端超时收尾」策略。
