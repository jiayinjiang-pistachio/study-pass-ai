"""业务层：火山 RTC 实时语音面试（AI 面试官）。

对外职责：
- `start_voice_chat`：确认面试后生成前端入房参数与 RTC AccessToken，并调用
  StartVoiceChat 拉起 AI 面试官；
- `stop_voice_chat`：挂断后调用 StopVoiceChat 结束 RTC 任务；
- `finish_interview`：停止 AI，保存最终问答与时长，并把面试置为已结束。

RTC 属于外部依赖：未配置或调用失败只记日志，不阻断面试创建 / 结果落库。
签名与 token 算法均为火山官方示例（SignerV4 + "001" AccessToken）的 Python 移植。
"""

import base64
import hashlib
import hmac
import json
import logging
import random
import struct
import time

from fastapi import status
from volcengine.ApiInfo import ApiInfo
from volcengine.Credentials import Credentials
from volcengine.ServiceInfo import ServiceInfo
from volcengine.base.Service import Service

from ..core import config
from ..core.exceptions import BusinessException
from ..db import interview_repo

logger = logging.getLogger(__name__)

# RTC OpenAPI：新版接口固定 2025-06-01，服务名 / 区域与签名版本见官方文档
RTC_HOST = "rtc.volcengineapi.com"
RTC_SERVICE = "rtc"
RTC_VERSION = "2025-06-01"
RTC_TIMEOUT_SECONDS = 10

# 语音面试与面试记录一对一绑定：同一 interview_id 复用同一房间 / 任务 / Bot
TASK_ID_PREFIX = "voiceinterview"
BOT_USER_ID_PREFIX = "aiinterviewer"

# AccessToken 权限位（与官方 Go 示例一致）：0=发布流，4=订阅流
_PRIV_PUBLISH_STREAM = 0
_PRIV_PUBLISH_AUDIO_STREAM = 1
_PRIV_PUBLISH_VIDEO_STREAM = 2
_PRIV_PUBLISH_DATA_STREAM = 3
_PRIV_SUBSCRIBE_STREAM = 4

# AccessToken 固定版本前缀
_ACCESS_TOKEN_VERSION = "001"

# 未配置主考官提示词时的保底人设，避免 LLM 无系统消息
_DEFAULT_SYSTEM_PROMPT = "你是一名专业的 AI 面试官，请用中文与候选人进行模拟面试。"

_API_INFO = {
    "StartVoiceChat": ApiInfo(
        "POST", "/", {"Action": "StartVoiceChat", "Version": RTC_VERSION}, {}, {}
    ),
    "StopVoiceChat": ApiInfo(
        "POST", "/", {"Action": "StopVoiceChat", "Version": RTC_VERSION}, {}, {}
    ),
}


def _pack_uint16(value: int) -> bytes:
    return struct.pack("<H", value & 0xFFFF)


def _pack_uint32(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def _pack_bytes(value: bytes) -> bytes:
    return _pack_uint16(len(value)) + value


def _pack_string(value: str) -> bytes:
    return _pack_bytes(value.encode("utf-8"))


def _pack_privileges(privileges: dict[int, int]) -> bytes:
    """权限表按 key 升序打包，保证签名结果稳定。"""
    parts = [_pack_uint16(len(privileges))]
    for key in sorted(privileges):
        parts.append(_pack_uint16(key))
        parts.append(_pack_uint32(privileges[key]))
    return b"".join(parts)


def generate_rtc_token(
    app_id: str,
    app_key: str,
    room_id: str,
    user_id: str,
    expire_at: int,
    can_publish: bool = True,
    can_subscribe: bool = True,
) -> str:
    """生成 RTC 入房 AccessToken（供前端加入房间使用）。

    结构：`001 + AppID + base64(packString(msg) + packString(sign))`，
    msg 为小端序 nonce / issued_at / expire_at / room_id / user_id / 权限表，
    sign 为 AppKey 对 msg 的 HMAC-SHA256。
    """
    issued_at = int(time.time())
    nonce = random.randint(1, 99999999)

    privileges: dict[int, int] = {}
    if can_publish:
        for key in (
            _PRIV_PUBLISH_STREAM,
            _PRIV_PUBLISH_AUDIO_STREAM,
            _PRIV_PUBLISH_VIDEO_STREAM,
            _PRIV_PUBLISH_DATA_STREAM,
        ):
            privileges[key] = expire_at
    if can_subscribe:
        privileges[_PRIV_SUBSCRIBE_STREAM] = expire_at

    msg = b"".join(
        (
            _pack_uint32(nonce),
            _pack_uint32(issued_at),
            _pack_uint32(expire_at),
            _pack_string(room_id),
            _pack_string(user_id),
            _pack_privileges(privileges),
        )
    )
    sign = hmac.new(app_key.encode("utf-8"), msg, hashlib.sha256).digest()
    content = _pack_bytes(msg) + _pack_bytes(sign)
    return (
        _ACCESS_TOKEN_VERSION
        + app_id
        + base64.b64encode(content).decode("ascii")
    )


def _build_service() -> Service:
    """按环境变量初始化 RTC OpenAPI 客户端。"""
    if not config.VOLC_ACCESS_KEY or not config.VOLC_SECRET_KEY:
        raise RuntimeError("缺少 VOLC_ACCESS_KEY / VOLC_SECRET_KEY，无法调用 RTC OpenAPI")

    credentials = Credentials(
        config.VOLC_ACCESS_KEY, config.VOLC_SECRET_KEY, RTC_SERVICE, config.VOLC_REGION
    )
    service_info = ServiceInfo(
        RTC_HOST,
        {},
        credentials,
        RTC_TIMEOUT_SECONDS,
        RTC_TIMEOUT_SECONDS,
        scheme="https",
    )
    return Service(service_info, _API_INFO)


def _call(action: str, body: dict) -> dict:
    """调用 RTC OpenAPI；网关级错误抛 RuntimeError，由调用方决定是否降级。"""
    raw = _build_service().json(action, {}, json.dumps(body, ensure_ascii=False))
    data = json.loads(raw)
    error = (data.get("ResponseMetadata") or {}).get("Error") or {}
    if error:
        raise RuntimeError(
            f"action={action} code={error.get('Code')} message={error.get('Message')}"
        )
    return data


def _room_names(interview_id: int) -> tuple[str, str]:
    """返回 (TaskId / RoomId, Bot UserId)；同一面试固定复用。"""
    return (
        f"{TASK_ID_PREFIX}{interview_id}",
        f"{BOT_USER_ID_PREFIX}{interview_id}",
    )


def _build_config(rtc: config.RTCConfig, system_prompt: str) -> dict:
    """组装 RTC 对话配置：火山 ASR / 双向流式 TTS / 业务复用的大模型。"""
    asr_params: dict = {"Mode": "bigmodel", "StreamMode": 0}
    if rtc.asr_app_id and rtc.asr_access_token:
        asr_params["AppId"] = rtc.asr_app_id
        asr_params["AccessToken"] = rtc.asr_access_token

    tts_params: dict = {"audio": {"voice_type": rtc.tts_speaker}}
    if rtc.tts_app_id and rtc.tts_access_token:
        tts_params["app"] = {
            "appid": rtc.tts_app_id,
            "token": rtc.tts_access_token,
        }

    # 复用现有 OpenAI 兼容配置：RTC 以 CustomLLM 方式回调后端所配模型
    llm = config.get_llm_config()
    llm_config = {
        "Mode": "CustomLLM",
        "Url": f"{llm.base_url}/chat/completions",
        "ModelName": llm.model,
        "APIKey": llm.api_key,
        "SystemMessages": [system_prompt],
        "HistoryLength": rtc.history_length,
    }

    return {
        "ASRConfig": {"Provider": "volcano", "ProviderParams": asr_params},
        "TTSConfig": {
            "Provider": "volcano_bidirection",
            "ProviderParams": tts_params,
        },
        "LLMConfig": llm_config,
        "SubtitleConfig": {"SubtitleMode": rtc.subtitle_mode},
    }


class VoiceInterviewService:
    """封装 RTC AI 面试官的启动、停止与结果落库。"""

    def start_voice_chat(self, interview: dict) -> dict:
        """确认面试后调用：返回前端入房参数，并尽力启动 RTC AI 面试官。

        RTC 未配置 / 启动失败都不能影响面试创建，因此异常只记日志，
        通过返回值的 `started` 告知前端 AI 是否真正拉起。
        """
        interview_id = interview["id"]
        task_id, bot_user_id = _room_names(interview_id)
        room_id = task_id
        user_id = str(interview["user_id"])

        voice = {
            "app_id": config.VOLC_RTC_APP_ID,
            "room_id": room_id,
            "user_id": user_id,
            "bot_user_id": bot_user_id,
            "task_id": task_id,
            "token": None,
            "expire_at": None,
            "started": False,
        }

        if not config.has_rtc_config():
            logger.warning(
                "RTC 未配置，跳过启动 AI 面试官 | interview_id=%s", interview_id
            )
            return voice

        rtc = config.get_rtc_config()
        expire_at = int(time.time()) + max(rtc.token_ttl_seconds, 60)
        voice["token"] = generate_rtc_token(
            rtc.app_id, rtc.app_key, room_id, user_id, expire_at
        )
        voice["expire_at"] = expire_at

        system_prompt = interview.get("interview_host_prompt") or _DEFAULT_SYSTEM_PROMPT
        try:
            # 组装配置时可能因 LLM 未配置而失败，同样视为「本次未启动」
            body = {
                "AppId": rtc.app_id,
                "RoomId": room_id,
                "TaskId": task_id,
                "Config": _build_config(rtc, system_prompt),
                "AgentConfig": {
                    "TargetUserId": [user_id],
                    "UserId": bot_user_id,
                    "WelcomeMessage": rtc.welcome_message,
                    "IdleTimeout": rtc.idle_timeout,
                },
            }
            _call("StartVoiceChat", body)
        except Exception:
            logger.error(
                "启动 AI 面试官失败 | interview_id=%s room_id=%s task_id=%s",
                interview_id,
                room_id,
                task_id,
                exc_info=True,
            )
            return voice

        voice["started"] = True
        logger.info(
            "AI 面试官已启动 | interview_id=%s user_id=%s room_id=%s task_id=%s "
            "bot_user_id=%s",
            interview_id,
            user_id,
            room_id,
            task_id,
            bot_user_id,
        )
        return voice

    def stop_voice_chat(self, interview_id: int) -> bool:
        """结束 RTC 任务；失败只记日志，返回是否成功（不影响结果落库）。"""
        if not config.has_rtc_config():
            return False

        rtc = config.get_rtc_config()
        task_id, _ = _room_names(interview_id)
        body = {"AppId": rtc.app_id, "RoomId": task_id, "TaskId": task_id}
        try:
            _call("StopVoiceChat", body)
        except Exception:
            logger.error(
                "停止 AI 面试官失败 | interview_id=%s task_id=%s",
                interview_id,
                task_id,
                exc_info=True,
            )
            return False

        logger.info("AI 面试官已停止 | interview_id=%s task_id=%s", interview_id, task_id)
        return True

    def finish_interview(
        self,
        user_id: int,
        interview_id: int,
        qa_object: list[dict],
        interview_duration: int,
    ) -> dict:
        """挂断后收尾：先停 RTC，再保存问答 / 时长并置 status=1。"""
        interview = interview_repo.get_for_user(interview_id, user_id)
        if interview is None:
            raise BusinessException(
                "面试记录不存在",
                http_status=status.HTTP_404_NOT_FOUND,
                detail=f"interview_id={interview_id} user_id={user_id}",
            )

        # 先停 AI：即使停止失败也继续保存结果，避免丢失用户已完成的内容
        self.stop_voice_chat(interview_id)

        updated = interview_repo.finish(
            interview_id, user_id, qa_object, interview_duration
        )
        if updated is None:
            raise BusinessException(
                "面试记录不存在",
                http_status=status.HTTP_404_NOT_FOUND,
                detail=f"interview_id={interview_id} user_id={user_id}",
            )

        logger.info(
            "语音面试已结束 | interview_id=%s user_id=%s qa_count=%s duration=%s",
            interview_id,
            user_id,
            len(qa_object),
            interview_duration,
        )
        return {
            "interview_id": updated["id"],
            "status": updated["status"],
            "interview_duration": updated["interview_duration"],
            "qa_count": len(qa_object),
        }
