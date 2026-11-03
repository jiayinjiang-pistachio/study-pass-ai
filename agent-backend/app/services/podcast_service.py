"""业务层：火山语音播客大模型（WebSocket 二进制协议）。

只负责「话题文本 → MP3 字节」：连接 wss、下发 StartSession、拼接下行音频帧；
不落本地、不保存对白稿，落库与消息回显由知识卡工作流编排。

协议（/api/v3/sami/podcasttts）：4 字节头 + 可选 event + session_id + payload，
整数一律大端；鉴权走 X-Api-App-Id / X-Api-Access-Key / X-Api-Resource-Id。
"""

import gzip
import json
import logging
import struct
import time
import uuid
from typing import NamedTuple

from websockets.exceptions import InvalidStatus, WebSocketException
from websockets.sync.client import connect

from ..core.config import PodcastTtsConfig, get_podcast_tts_config
from ..core.exceptions import SystemException

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 30 * 1024 * 1024
ERROR_BODY_MAX_CHARS = 500
CONNECT_TIMEOUT = 15

PROTOCOL_VERSION = 0b0001
HEADER_SIZE = 0b0001
# 上行帧 message type 固定为 0b0001；文档示例表里的 1001 与错误帧实测不符
MSG_FULL_CLIENT_REQUEST = 0b0001
MSG_ERROR = 0b1111
FLAG_WITH_EVENT = 0b0100
SERIALIZATION_JSON = 0b0001
COMPRESSION_GZIP = 0b0001

EVENT_START_SESSION = 100
EVENT_FINISH_SESSION = 102
EVENT_FINISH_CONNECTION = 2
EVENT_CONNECTION_FINISHED = 52
EVENT_SESSION_STARTED = 150
EVENT_SESSION_FINISHED = 152
EVENT_USAGE = 154
EVENT_ROUND_START = 360
EVENT_ROUND_RESPONSE = 361
EVENT_ROUND_END = 362
EVENT_PODCAST_END = 363

DEFAULT_SPEAKERS = [
    "zh_male_dayixiansheng_v2_saturn_bigtts",
    "zh_female_mizaitongxue_v2_saturn_bigtts",
]


class PodcastFrame(NamedTuple):
    """解包后的一帧：event 为 None 时表示错误帧或事件缺失。"""

    event: int | None
    payload: bytes
    error_code: int | None = None


def _header(serialization: int = SERIALIZATION_JSON) -> bytes:
    """4 字节头：v1 / 4 字节头 / 事件帧 / 序列化 / 不压缩。"""
    return bytes(
        [
            (PROTOCOL_VERSION << 4) | HEADER_SIZE,
            (MSG_FULL_CLIENT_REQUEST << 4) | FLAG_WITH_EVENT,
            (serialization << 4) | 0b0000,
            0b0000,
        ]
    )


def _encode_frame(
    event: int, payload: bytes, session_id: str | None = None
) -> bytes:
    """构造上行帧；FinishConnection 不带 session_id。"""
    body = struct.pack(">i", event)
    if session_id is not None:
        encoded_session = session_id.encode("utf-8")
        body += struct.pack(">I", len(encoded_session)) + encoded_session
    body += struct.pack(">I", len(payload)) + payload
    return _header() + body


def _decompress(payload: bytes, compression: int) -> bytes:
    if compression != COMPRESSION_GZIP:
        return payload
    try:
        return gzip.decompress(payload)
    except OSError as exc:
        raise SystemException(
            "知识卡音频生成失败",
            http_status=502,
            detail=f"podcast gzip: {exc}",
        ) from exc


def _parse_frame(message: bytes) -> PodcastFrame:
    """解析下行二进制帧；结构异常统一按生成失败处理。"""
    if len(message) < 4:
        raise SystemException(
            "知识卡音频生成失败", http_status=502, detail="podcast frame too short"
        )

    header_size = (message[0] & 0b1111) * 4
    message_type = message[1] >> 4
    flags = message[1] & 0b1111
    compression = message[2] & 0b1111

    if message_type == MSG_ERROR:
        if len(message) < 8:
            raise SystemException(
                "知识卡音频生成失败",
                http_status=502,
                detail="podcast error frame too short",
            )
        error_code = struct.unpack_from(">i", message, 4)[0]
        return PodcastFrame(
            event=None,
            payload=_decompress(message[8:], compression),
            error_code=error_code,
        )

    offset = header_size
    event: int | None = None
    if flags & FLAG_WITH_EVENT:
        if len(message) < offset + 4:
            raise SystemException(
                "知识卡音频生成失败",
                http_status=502,
                detail="podcast frame missing event",
            )
        event = struct.unpack_from(">i", message, offset)[0]
        offset += 4

    # 事件帧结构：session_id(len+bytes) + payload(len+bytes)
    if len(message) < offset + 8:
        raise SystemException(
            "知识卡音频生成失败", http_status=502, detail="podcast frame truncated"
        )
    session_len = struct.unpack_from(">I", message, offset)[0]
    offset += 4 + session_len
    if len(message) < offset + 4:
        raise SystemException(
            "知识卡音频生成失败", http_status=502, detail="podcast frame truncated"
        )
    payload_len = struct.unpack_from(">I", message, offset)[0]
    offset += 4
    payload = message[offset : offset + payload_len]
    return PodcastFrame(event=event, payload=_decompress(payload, compression))


def _json_payload(payload: bytes) -> dict:
    """解析文本类事件的 JSON payload；空内容按空对象处理。"""
    if not payload.strip():
        return {}
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemException(
            "知识卡音频生成失败",
            http_status=502,
            detail=f"podcast invalid json: {exc}",
        ) from exc
    return parsed if isinstance(parsed, dict) else {}


def _request_body(topic: str) -> dict:
    """action=0：把输入文本总结成双人播客；MP3 24k，开头结尾不加音乐。"""
    return {
        "action": 0,
        "input_text": topic,
        "use_head_music": False,
        "use_tail_music": False,
        "aigc_watermark": False,
        "audio_config": {
            "format": "mp3",
            "sample_rate": 24000,
            "speech_rate": 0,
        },
        "speaker_info": {
            "random_order": False,
            "speakers": DEFAULT_SPEAKERS,
        },
    }


def _build_headers(config: PodcastTtsConfig) -> dict[str, str]:
    return {
        "X-Api-App-Id": config.app_id,
        "X-Api-Access-Key": config.access_key,
        "X-Api-Resource-Id": config.resource_id,
        "X-Api-Request-Id": str(uuid.uuid4()),
    }


def _check_audio(data: bytes) -> bytes:
    """校验非空与体积上限，避免异常响应拖垮进程或撑爆存储。"""
    if not data:
        raise SystemException(
            "知识卡音频生成失败",
            http_status=502,
            detail="podcast empty audio",
        )
    if len(data) > MAX_AUDIO_BYTES:
        raise SystemException(
            "知识卡音频过大，已取消保存",
            http_status=502,
            detail=f"podcast audio > {MAX_AUDIO_BYTES} bytes",
        )
    return data


def _raise_for_frame(frame: PodcastFrame) -> None:
    if frame.error_code is None:
        return
    detail = frame.payload[:ERROR_BODY_MAX_CHARS].decode("utf-8", errors="replace")
    raise SystemException(
        "知识卡音频生成失败",
        http_status=502,
        detail=f"podcast error code={frame.error_code}: {detail}",
    )


def _read_audio(ws, session_id: str, timeout: float) -> bytes:
    """读取下行帧直到 SessionFinished，期间拼接 PodcastRoundResponse 音频。"""
    deadline = time.monotonic() + timeout
    audio = bytearray()
    finished = False

    while not finished:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemException(
                "知识卡音频生成失败", http_status=502, detail="podcast timeout"
            )
        message = ws.recv(timeout=remaining)
        if isinstance(message, str):
            continue

        frame = _parse_frame(message)
        _raise_for_frame(frame)

        if frame.event == EVENT_ROUND_RESPONSE:
            if len(audio) + len(frame.payload) > MAX_AUDIO_BYTES:
                raise SystemException(
                    "知识卡音频过大，已取消保存",
                    http_status=502,
                    detail=f"podcast audio > {MAX_AUDIO_BYTES} bytes",
                )
            audio.extend(frame.payload)
        elif frame.event == EVENT_ROUND_END:
            meta = _json_payload(frame.payload)
            if meta.get("is_error"):
                raise SystemException(
                    "知识卡音频生成失败",
                    http_status=502,
                    detail=f"podcast round error: {meta.get('error_msg')}",
                )
        elif frame.event == EVENT_PODCAST_END:
            # 生成结束：通知服务端收尾，继续等 SessionFinished
            try:
                ws.send(
                    _encode_frame(
                        EVENT_FINISH_SESSION, b"{}", session_id=session_id
                    )
                )
            except WebSocketException as exc:
                raise SystemException(
                    "知识卡音频生成失败",
                    http_status=502,
                    detail=f"podcast finish: {exc}",
                ) from exc
        elif frame.event == EVENT_SESSION_FINISHED:
            meta = _json_payload(frame.payload)
            status_code = meta.get("status_code")
            if status_code is not None and status_code != 20000000:
                raise SystemException(
                    "知识卡音频生成失败",
                    http_status=502,
                    detail=(
                        f"podcast session status={status_code} "
                        f"message={meta.get('message')}"
                    ),
                )
            finished = True
        elif frame.event in (
            EVENT_SESSION_STARTED,
            EVENT_ROUND_START,
            EVENT_USAGE,
            EVENT_CONNECTION_FINISHED,
        ):
            continue

    return _check_audio(bytes(audio))


def generate_podcast(topic: str) -> bytes:
    """生成播客音频字节。

    配置缺失抛 RuntimeError（工作流据此跳过音频），接口失败抛
    SystemException(502)。音频是加分项，不重试，避免重复扣费。
    """
    config = get_podcast_tts_config()
    session_id = uuid.uuid4().hex
    start_payload = json.dumps(
        _request_body(topic), ensure_ascii=False
    ).encode("utf-8")

    try:
        with connect(
            config.url,
            additional_headers=_build_headers(config),
            open_timeout=CONNECT_TIMEOUT,
            close_timeout=5,
            max_size=None,
            compression=None,
        ) as ws:
            ws.send(
                _encode_frame(
                    EVENT_START_SESSION, start_payload, session_id=session_id
                )
            )
            audio = _read_audio(ws, session_id, config.timeout)
            try:
                ws.send(
                    _encode_frame(EVENT_FINISH_CONNECTION, b"{}")
                )
            except WebSocketException:
                logger.debug("播客连接已结束，跳过 FinishConnection")
            return audio
    except InvalidStatus as exc:
        body = getattr(getattr(exc, "response", None), "body", b"")
        detail = (
            body[:ERROR_BODY_MAX_CHARS].decode("utf-8", errors="replace")
            if isinstance(body, bytes)
            else str(body)[:ERROR_BODY_MAX_CHARS]
        )
        raise SystemException(
            "知识卡音频生成失败",
            http_status=502,
            detail=f"podcast handshake {exc.status_code}: {detail}",
        ) from exc
    except SystemException:
        raise
    except TimeoutError as exc:
        raise SystemException(
            "知识卡音频生成失败", http_status=502, detail="podcast timeout"
        ) from exc
    except (WebSocketException, OSError) as exc:
        raise SystemException(
            "知识卡音频生成失败",
            http_status=502,
            detail=f"podcast request: {exc}",
        ) from exc
