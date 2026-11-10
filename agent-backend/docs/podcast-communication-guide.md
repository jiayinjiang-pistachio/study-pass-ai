# AI 播客通信原理详解（WebSocket 二进制协议）

面向需要维护 / 排查知识卡播客链路的开发同学，解释「知识卡文本如何变成可播放的 MP3」：

1. 前后端、业务后端与火山语音播客服务之间的**通信方式**；
2. WebSocket 握手机制与**自定义二进制帧**的逐字节含义；
3. 事件驱动的会话流程、音频切片拼接、存储与前端回放；
4. 常见故障的定位方法；
5. 全链路专有名词速查。

> 相关代码：
> - WebSocket 客户端：[`app/services/podcast_service.py`](../app/services/podcast_service.py)
> - 并行编排：[`app/services/difficulty_card_workflow.py`](../app/services/difficulty_card_workflow.py)
> - 配置入口：[`app/core/config.py`](../app/core/config.py)
> - 前端知识卡：[`../../agent-frontend/src/components/chat/KnowledgeCard.vue`](../../agent-frontend/src/components/chat/KnowledgeCard.vue)
> - 配置与联调：[`difficulty-card-guide.md`](./difficulty-card-guide.md)

---

## 1. 一句话总览

后端把知识卡文本通过 **WebSocket（全双工长连接）** 发给火山「语音播客」服务，服务端一边生成对话一边把 **MP3 音频切片**流式推回来；后端把切片拼成一个完整 MP3，存进 MinIO，再把 `resource_id` 写进聊天消息，前端用 `<audio>` 播放。

```
前端                后端                       火山语音播客
 │  POST JSON        │                              │
 │──────────────────▶│ 1. prepare_card（LLM 整理卡片）│
 │                   │ 2. 出图 ∥ 生成播客（并行）      │
 │                   │──── wss 建连（HTTP Upgrade）──▶│
 │                   │──── StartSession(100) ───────▶│
 │                   │◀─── SessionStarted(150) ──────│
 │                   │◀─── RoundStart(360) ──────────│
 │                   │◀─── RoundResponse(361) 音频 ───│  × N 帧
 │                   │◀─── RoundEnd(362) ────────────│
 │                   │◀─── PodcastEnd(363) ──────────│
 │                   │──── FinishSession(102) ──────▶│
 │                   │◀─── SessionFinished(152) ─────│
 │                   │──── FinishConnection(2) ─────▶│
 │                   │ 3. MP3 拼接 → MinIO          │
 │◀── JSON 响应 ──────│ 4. 写 chat_messages           │
 │  先渲染，再拉历史    │                              │
```

---

## 2. 为什么用 WebSocket，而不是普通 HTTP

| 方式 | 特点 | 是否适合播客 |
| --- | --- | --- |
| 普通 HTTP | 一问一答，响应结束连接就结束 | 不适合：生成要几十秒，无法边生成边收 |
| HTTP 轮询 | 客户端反复问“好了吗” | 不适合：延迟高、请求多 |
| SSE（Server-Sent Events，服务器推送事件） | 服务器单向推送文本流 | 部分适合，但只能下行、不能双向交互 |
| **WebSocket** | 一次握手后**全双工**（上下行都能随时发），长连接 | **适合**：服务端持续推音频，客户端还能发“结束会话”指令 |

**关键概念**

- **WS / WSS**：WebSocket / WebSocket Secure。`wss` 相当于“WebSocket over TLS（加密传输）”，类比 `http` 与 `https`。
- **握手（Handshake）**：WebSocket 建连复用了 HTTP。客户端先发一个带 `Upgrade: websocket` 的 HTTP 请求，服务端返回 **101 Switching Protocols**，之后同一条 TCP 连接就切换成 WebSocket 协议。
- **鉴权只在握手时做一次**：把 `X-Api-*` 头放在握手请求里，连接建立后发消息不再带凭证。
- 代码用的是 `websockets.sync.client.connect(...)`：**同步客户端**，运行在知识卡工作流的线程池线程里，不需要把整个后端改成异步。

---

## 3. 建连与鉴权

### 3.1 连接地址

```
wss://openspeech.bytedance.com/api/v3/sami/podcasttts
```

| 片段 | 含义 |
| --- | --- |
| `wss://` | 加密 WebSocket |
| `/api/v3/` | 接口大版本 |
| `sami` | 火山语音大模型接口的路由分组名 |
| `podcasttts` | 播客 TTS（Text-To-Speech，文本转语音） |

### 3.2 握手请求头

| Header | 作用 | 示例 |
| --- | --- | --- |
| `X-Api-App-Id` | 控制台应用的 App ID | 数字 ID |
| `X-Api-Access-Key` | 应用的 Access Token / Access Key | 密钥 |
| `X-Api-Resource-Id` | 声明调用哪个服务、计入哪个资源池 | `volc.service_type.10050` |
| `X-Api-Request-Id` | 客户端生成的请求 ID（UUID），方便查日志 | 随机串 |

> **踩坑记录**：官方文档写的是 `X-Api-Key`，但那是控制台新版 **API Key** 体系；我们用的是 **App ID + Access Token**，用 `X-Api-Key` 会返回 `Invalid X-Api-Key`，必须用 `X-Api-App-Id` + `X-Api-Access-Key`。

- **App ID**：应用标识，不是 RTC 的 App ID。
- **Access Token / Access Key**：调用凭证，等同密码，只能放后端环境变量。
- **Resource ID**：告诉服务端“我要用语音播客这个能力”，同时决定计费归属。

---

## 4. WebSocket 之上还有一层“自定义二进制协议”

WebSocket 本身只保证“一条消息的边界”，但火山在这个通道里又定义了自己的**二进制帧格式**。可以理解为：WebSocket 是信封，里面还要按对方规定的格式写正文。

### 4.1 一帧的组成

```
┌────────┬────────────┬──────────────┬──────────────┬─────────┐
│ 4 字节  │ 4 字节      │ 4 字节        │ session_id    │ payload │
│ 头部    │ event 编号  │ session_id 长度│ (UTF-8 字符串) │ 正文    │
└────────┴────────────┴──────────────┴──────────────┴─────────┘
                                       │ 4 字节长度 + 正文 │
```

四字节头部逐位解释：

| 字节 | 高 4 位（Left 4-bit） | 低 4 位（Right 4-bit） | 我们发送时 |
| --- | --- | --- | --- |
| 0 | 协议版本，固定 `0001` | 头部长度，`0001` 表示 4 字节 | `0x11` |
| 1 | 消息类型 | 标志位（是否有 event） | `0x14`：类型 1 + 有 event |
| 2 | 序列化方式：`0001` = JSON | 压缩方式：`0000` = 不压缩 | `0x10` |
| 3 | 保留 | 保留 | `0x00` |

所以上行帧开头固定是 `11 14 10 00`。

对应代码：

```python
def _header() -> bytes:
    return bytes([
        (0b0001 << 4) | 0b0001,              # v1, 4 字节头
        (0b0001 << 4) | 0b0100,              # 消息类型 1, 带 event
        (0b0001 << 4) | 0b0000,              # JSON, 不压缩
        0b0000,
    ])
```

### 4.2 容易蒙的术语

- **位（bit）/ 字节（byte）**：1 字节 = 8 位。头部用“左 4 位 / 右 4 位”把一个字节拆成两个半字节存两种信息，省空间。
- **大端（Big-Endian）**：多字节整数**高位在前**。例如 `0x00000064` 表示 100。Python 用 `struct.pack(">i", ...)`，`>` 就是大端。
- **`int32` / `uint32`**：32 位有符号 / 无符号整数，占 4 字节。event 编号用 `int32`，长度用 `uint32`。
- **序列化（Serialization）**：把 Python 字典变成可传输的字节。这里是 JSON。
- **压缩（Compression）**：这里可选 gzip；我们发送不压缩，解析时兼容 gzip。
- **payload（负载 / 正文）**：帧里真正有用的数据，可能是 JSON，也可能是音频字节。

### 4.3 消息类型（Message Type）

| 值 | 含义 | 方向 |
| --- | --- | --- |
| `0001` | 客户端完整请求 | 上行 |
| `1001` | 服务端普通响应 / 音频响应（文档示例） | 下行 |
| `1011` | 纯音频响应 | 下行 |
| `1111` | 错误帧 | 下行 |

> **文档与实测冲突**：文档示例表把上行写成 `1001`（类型 9），实测返回 `unsupported message type (9)`。真实可用值是 `0001`（类型 1），代码里已按实测修正并加了注释。

### 4.4 错误帧

错误帧头部是 `11 F0 10 00`，之后 4 字节是错误码，剩余是错误描述：

```
11 F0 10 00 | 00 02 AE E0 | {"error":"..."}
                ↑ 45000000（并发超限示例）
```

---

## 5. 事件驱动的会话流程

协议不是“发一次收一次”，而是**客户端发一个事件，服务端回一串事件**，像一场有编号的对话。

| Event | 名称 | 方向 | 作用 |
| --- | --- | --- | --- |
| 100 | `StartSession` | 上行 | 开始任务，payload 里带输入文本和音频参数 |
| 150 | `SessionStarted` | 下行 | 会话已建立 |
| 360 | `PodcastRoundStart` | 下行 | 新一轮开始，带 `round_id`、`speaker`、文本 |
| 361 | `PodcastRoundResponse` | 下行 | **音频字节**，一轮可能有多帧 |
| 362 | `PodcastRoundEnd` | 下行 | 本轮结束，带起止时间 |
| 363 | `PodcastEnd` | 下行 | 整期播客结束（可能不返回） |
| 154 | `UsageResponse` | 下行 | token 用量统计 |
| 102 | `FinishSession` | 上行 | 通知服务端收尾 |
| 152 | `SessionFinished` | 下行 | 会话彻底结束 |
| 2 | `FinishConnection` | 上行 | 关闭连接 |
| 52 | `ConnectionFinished` | 下行 | 关闭确认 |

我们的实现顺序：

1. 建连 → 发 `StartSession(100)`，`session_id` 用随机 `uuid4().hex`；
2. 循环 `recv()`：
   - 360 / 362 / 154：只读元信息，忽略；
   - **361：把 payload 追加到音频缓冲区**；
   - 362 里如果 `is_error=true`：抛错；
   - 363：发送 `FinishSession(102)`；
   - 152：结束循环；
3. 发 `FinishConnection(2)`，关闭连接；
4. 校验音频非空、不超过 30MB，返回 MP3 字节。

> `round_id = -1` 代表片头音乐，`round_id = 9999` 代表片尾音乐。我们设置
> `use_head_music=false` / `use_tail_music=false`，避免音乐混进讲解。

### 5.1 请求正文（StartSession 的 payload）

```json
{
  "action": 0,
  "input_text": "Python GIL……请做成双人播客对话……",
  "use_head_music": false,
  "use_tail_music": false,
  "audio_config": { "format": "mp3", "sample_rate": 24000, "speech_rate": 0 },
  "speaker_info": {
    "random_order": false,
    "speakers": [
      "zh_male_dayixiansheng_v2_saturn_bigtts",
      "zh_female_mizaitongxue_v2_saturn_bigtts"
    ]
  }
}
```

| 字段 | 解释 |
| --- | --- |
| `action` | 生成模式：`0` 对输入文本做总结生成；`3` 直接按给定对白合成；`4` 按关键词联网生成。我们用 `0` |
| `input_text` | 待总结的文本，最长 32k 字符 |
| `use_head_music` | 是否加片头音乐；关掉避免干扰知识卡讲解 |
| `audio_config.format` | 输出格式；`mp3` 便于浏览器直接播放 |
| `sample_rate` | 采样率 24kHz |
| `speaker_info.speakers` | 两位发音人，都是火山内置大模型音色 |
| `random_order` | 是否随机决定谁先说；固定为 false 保证开场稳定 |

这些内容由 `build_podcast_topic()` **用代码确定性拼接**，不额外调用大模型——保证播客内容与知识卡图片同源。

---

## 6. 音频是怎么“拼”出来的

### 6.1 为什么要拼接

服务端不是一次性返回整个文件，而是按轮次、按缓冲区大小持续返回 `361` 帧，每帧 payload 是一小段 MP3 字节。后端：

```python
audio = bytearray()
...
if event == EVENT_ROUND_RESPONSE:
    audio.extend(payload)
```

### 6.2 直接拼 MP3 为什么可行

- **MP3** 本质是**一串独立的音频帧**（frame）按顺序排列，帧与帧之间没有全局文件头依赖。
- 同一路编码器连续产出的切片，按序拼接就是合法 MP3。
- 返回的数据开头是 `ID3` 标签（`0x49 0x44 0x33`），实测 733KB 文件头正确。
- 不需要 ffmpeg 之类的工具二次封装。

### 6.3 相关术语

- **TTS**：Text-To-Speech，文本转语音。
- **PCM**：未压缩的原始音频采样，体积大，浏览器不能直接 `<audio>` 播放。
- **MP3**：有损压缩音频格式，浏览器原生支持。
- **ID3**：MP3 文件头部的元数据标签（标题、作者等）。
- **采样率（Sample Rate）**：每秒采样次数，24kHz 即每秒 24000 次。

---

## 7. 后端如何编排（并行 + 容错）

```python
with ThreadPoolExecutor(max_workers=2) as pool:
    image_future = pool.submit(seedream_service.generate_image, image_prompt)
    audio_future = pool.submit(_generate_podcast, card)
    image_bytes = image_future.result()   # 图片失败 → 整体失败
    podcast = audio_future.result()       # 音频失败 → 只记 WARNING
```

| 设计 | 原因 |
| --- | --- |
| 出图与播客**并行** | 两者都是网络等待（I/O），不是 CPU 计算；线程池让总耗时 ≈ 较慢的一路 |
| 图片失败即整体失败 | 知识卡没有图就没有主产物 |
| 音频失败**软降级** | 缺配置、接口 4xx/5xx、超时、落库失败都只记 WARNING，知识卡照常返回 |
| **不重试** | 播客按 token 计费，重试可能重复扣费 |
| 30MB 上限 | 防止异常响应撑爆内存 / 存储 |
| 总超时 300 秒 | `_read_audio` 每次 `recv(timeout=剩余时间)`，避免单帧无限等待 |

**线程池 / ThreadPoolExecutor**：一组可复用的工作线程。这里同时跑两个任务，谁先完成谁先返回结果。虽然 Python 有 GIL（全局解释器锁），但网络等待时 GIL 会释放，所以并行发请求有效。

---

## 8. 从音频字节到前端播放

### 8.1 存储：MinIO + resource_id

- **MinIO**：自建对象存储，类似私有 S3。
- 音频经 `save_generated_audio()` 写入桶，按 `(user_id, MD5)` 去重；**永久保存**（`expire_time=NULL`）。
- **MD5**：文件内容摘要，内容相同则命中同一条资源，避免重复存。
- 数据库 `resources` 表只存元数据，消息里**只存 `resource_id`**，不存临时链接。

### 8.2 消息结构

```json
{
  "response_payload": { "type": "knowledge_card" },
  "response_segments": [
    { "type": "image", "resource_id": 101, "url": "https://minio..." },
    { "type": "audio", "resource_id": 102, "url": "https://minio..." }
  ]
}
```

### 8.3 预签名 URL（Presigned URL）

- MinIO 默认桶是私有的，不能直接公开访问。
- **预签名 URL** 是服务端用密钥临时签出的、带过期时间的下载地址。
- 历史消息读取时，`message_service` 按 `resource_id` 回表**重新签一次 URL**，所以链接过期也不影响回放。
- **resource_id** 就是“资源的身份证”，是链接失效后重新续签的锚点。

### 8.4 前端链路

1. 知识卡统一走 `POST /api/agent/chat`（**SSE**）。出图与播客并行，整轮约 1～3 分钟，期间保持连接。
2. 前端先显示 loading 提示：“正在生成知识卡和播客，请稍等…”。
3. 收到 `task(kind=knowledge_card)` 后**立即**用 `payload.image_url` / `payload.audio_url` 渲染 `KnowledgeCard`，再刷新历史消息对账。
4. 会话消息的 `response_payload.type = knowledge_card` 用于历史识别；标题从正文 `「…」` 中提取。
5. 没音频时 `audio_resource_id` / `audio_url` 为 `null`，只展示图片，不出现播放器；失败以 SSE `error` 收尾。

任务分支 `meta.message_id=0`，消息对账以 `task.payload.message_id` 为准。

---

## 9. 排障对照表

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| HTTP 404 `Not Found` | 用 HTTP 调了 WebSocket 路径 | 必须 `wss://`，用 WS 客户端 |
| 握手 401 / `Invalid X-Api-Key` | 凭证类型不匹配 | 改用 `X-Api-App-Id` + `X-Api-Access-Key` |
| 错误码 `45000000` | 并发超限 | 降低并发 / 联系控制台扩容 |
| `unsupported message type (9)` | 上行 message type 写成了 9 | 改为 `0b0001` |
| `40000010 PodcastTTS invalid param` | 参数错误 | 检查 `action` / `input_text` / `audio_config` |
| 音频为空 | 未收到 361 帧 | 看是否命中内容审核或提前断连 |
| 一分钟无响应 | 超时 | 默认 300 秒；检查网络 / 代理 |
| 知识卡正常但没有音频 | 软失败 | 查日志 WARNING 中的 `podcast` detail |

---

## 10. 名词速查表

| 缩写 / 术语 | 全称 / 含义 |
| --- | --- |
| WS / WSS | WebSocket / WebSocket Secure，全双工长连接 / 加密版 |
| HTTP Upgrade | HTTP 协议升级，WebSocket 握手的关键机制 |
| SSE | Server-Sent Events，服务器单向事件推送 |
| TTS | Text-To-Speech，文本转语音 |
| PCM | Pulse Code Modulation，未压缩音频采样 |
| MP3 | MPEG-1 Audio Layer III，有损压缩音频格式 |
| ID3 | MP3 文件元数据标签 |
| JSON | JavaScript Object Notation，文本数据格式 |
| UTF-8 | 一种字符编码，中文按多字节存储 |
| UUID | 通用唯一识别码，这里用作 `session_id` / `request_id` |
| 大端 / Big-Endian | 多字节整数高位字节在前 |
| `int32` / `uint32` | 32 位有符号 / 无符号整数（4 字节） |
| gzip | 一种数据压缩格式，协议里作为可选压缩标志 |
| API Key / Access Token | 调用云服务的凭证 |
| Resource ID | 云服务资源标识，声明用哪个能力 / 计费项 |
| MinIO | 自建对象存储服务，兼容 S3 |
| MD5 | 文件内容摘要算法，用于去重 |
| Presigned URL | 带签名和有效期的临时下载地址 |
| ThreadPoolExecutor | 线程池，用于并行执行多个阻塞任务 |
| GIL | Global Interpreter Lock，CPython 全局解释器锁 |
| RTC | Real-Time Communication，实时音视频通信（语音面试模块使用，与播客无关） |

---

**一句话记住整个通信过程**：WebSocket 长连接负责“边说边传”，四字节头 + event 编号负责“知道每段字节是什么”，361 帧负责“音频切片”，`resource_id` + 预签名 URL 负责“存得住、回放得了”。
