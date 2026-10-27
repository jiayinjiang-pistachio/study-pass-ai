"""长期记忆测试：画像格式化、意图判断、结构化抽取与后台写入。"""

import json

from app.db import user_profile_repo
from app.services import long_term_memory
from app.services.long_term_memory import (
    LongTermMemory,
    _clean_years,
    _extract_fields,
)

# 模块导入时保存真实实现：conftest 的 autouse 夹具会替换成测试替身，
# 涉及真实逻辑的用例需要显式换回来。
_REAL_SHOULD_WRITE = LongTermMemory.should_write
_REAL_MISSING = LongTermMemory.missing_required_fields
_REAL_SUBMIT = LongTermMemory.submit_profile_update_async


def test_load_memory_context_formats_profile(auth_user: dict) -> None:
    """画像字段按中文标签拼接；长期摘要排在最前。"""
    user_profile_repo.insert(
        auth_user["id"],
        {
            "target_job": "后端开发工程师",
            "years_experience": 3,
            "target_level": "P6",
            "target_skills": ["Python", "MySQL"],
            "weak_topics": ["分布式"],
            "learning_goal": "半年内完成转行",
            "learning_style": "项目驱动",
            "interview_focus": ["高并发", "数据库"],
            "long_term_summary": "关注后端成长，偏好实战。",
        },
    )

    text = LongTermMemory().load_memory_context(auth_user["id"])

    assert text.startswith("【用户画像】")
    assert "- 长期画像：关注后端成长，偏好实战。" in text
    assert "- 目标岗位：后端开发工程师" in text
    assert "- 工作年限：3 年" in text
    assert "- 已掌握技能：Python、MySQL" in text
    assert "- 学习目标：半年内完成转行" in text
    assert "- 学习偏好：项目驱动" in text
    assert "- 面试重点：高并发、数据库" in text


def test_load_memory_context_returns_empty_without_profile(auth_user: dict) -> None:
    """没有画像时返回空串，不注入 SystemMessage。"""
    assert LongTermMemory().load_memory_context(auth_user["id"]) == ""


def test_should_write_uses_semantic_similarity(monkeypatch) -> None:
    """与意图示例相似度达到阈值才命中；过短消息直接跳过。"""
    monkeypatch.setattr(LongTermMemory, "should_write", _REAL_SHOULD_WRITE)
    monkeypatch.setattr(
        long_term_memory,
        "_embed_texts",
        lambda texts: [[1.0, 0.0]] if texts[0].startswith("我") else [[0.0, 1.0]],
    )
    monkeypatch.setattr(
        long_term_memory, "_example_vectors", lambda: ((1.0, 0.0),)
    )

    memory = LongTermMemory()
    assert memory.should_write("我想学习后端开发", 1) is True
    assert memory.should_write("今天天气怎么样", 1) is False
    assert memory.should_write("好的", 1) is False


def test_should_write_degrades_when_model_fails(monkeypatch) -> None:
    """模型异常时返回 False，不阻断对话。"""
    monkeypatch.setattr(LongTermMemory, "should_write", _REAL_SHOULD_WRITE)

    def _boom(texts):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(long_term_memory, "_embed_texts", _boom)

    assert LongTermMemory().should_write("我想转行做后端开发", 1) is False


def test_extract_fields_parses_json_and_cleans_values() -> None:
    """支持代码块包裹的 JSON；空字段忽略、数组去重限长。"""
    raw = """```json
    {
      "target_job": " 后端开发工程师 ",
      "years_experience": "3 年",
      "target_level": "P6",
      "target_skills": ["Python", "Python", "MySQL"],
      "weak_topics": ["分布式"],
      "learning_goal": "转行后端",
      "learning_style": "   ",
      "interview_focus": ["高并发", "高并发", "数据库"],
      "long_term_summary": " 关注后端与数据库 "
    }
    ```"""

    fields = _extract_fields(raw)

    assert fields == {
        "target_job": "后端开发工程师",
        "years_experience": 3,
        "target_level": "P6",
        "target_skills": ["Python", "MySQL"],
        "weak_topics": ["分布式"],
        "learning_goal": "转行后端",
        "interview_focus": ["高并发", "数据库"],
        "long_term_summary": "关注后端与数据库",
    }


def test_clean_years_accepts_valid_and_rejects_invalid() -> None:
    """年限兼容字符串单位；越界、小数、布尔与无法识别的内容一律丢弃。"""
    assert _clean_years(3) == 3
    assert _clean_years(3.0) == 3
    assert _clean_years("3 年") == 3
    assert _clean_years(0) == 0
    assert _clean_years(60) == 60
    assert _clean_years(3.5) is None
    assert _clean_years("无经验") is None
    assert _clean_years(61) is None
    assert _clean_years(-1) is None
    assert _clean_years(True) is None
    assert _clean_years(None) is None


def test_extract_fields_keeps_zero_years() -> None:
    """0 年（应届 / 无经验）是有效画像值，不能被当成空字段丢掉。"""
    assert _extract_fields('{"years_experience": 0}') == {"years_experience": 0}


def test_extract_fields_limits_list_items() -> None:
    """技能 / 薄弱点最多 20 项，单项超长截断到 50 字。"""
    raw = json.dumps(
        {
            "target_skills": [f"技能{i}" for i in range(25)],
            "weak_topics": ["薄" * 60],
        },
        ensure_ascii=False,
    )

    fields = _extract_fields(raw)

    assert len(fields["target_skills"]) == 20
    assert fields["weak_topics"] == ["薄" * 50]


def test_missing_required_fields(auth_user: dict, monkeypatch) -> None:
    """必填项按缺失返回；0 年经验算已填写；资料齐全返回空列表。"""
    monkeypatch.setattr(
        LongTermMemory, "missing_required_fields", _REAL_MISSING
    )
    memory = LongTermMemory()
    user_id = auth_user["id"]

    assert memory.missing_required_fields(user_id) == [
        "target_job",
        "years_experience",
        "target_level",
    ]

    user_profile_repo.insert(
        user_id, {"target_job": "后端开发", "years_experience": 0}
    )
    assert memory.missing_required_fields(user_id) == ["target_level"]

    user_profile_repo.update(user_id, {"target_level": "P6"})
    assert memory.missing_required_fields(user_id) == []


def test_update_profile_from_conversation_writes_fields(
    auth_user: dict, monkeypatch
) -> None:
    """抽取结果写回画像，已有画像作为上下文传给模型。"""
    user_profile_repo.insert(
        auth_user["id"],
        {
            "target_job": "旧岗位",
            "target_skills": ["旧技能"],
            "learning_goal": "旧目标",
            "interview_focus": ["旧重点"],
        },
    )
    captured: dict = {}

    def _fake_extract(self, existing: str, request_text: str, context):
        captured["existing"] = existing
        captured["request_text"] = request_text
        captured["context"] = context
        return (
            '{"target_job": "新岗位", "years_experience": 3, '
            '"target_level": "P6", "target_skills": ["Go", "Kafka"], '
            '"weak_topics": ["分布式"], "learning_goal": "新目标", '
            '"interview_focus": ["新重点"], "long_term_summary": "新摘要"}'
        )

    monkeypatch.setattr(LongTermMemory, "_extract_profile_fields", _fake_extract)

    updated = LongTermMemory().update_profile_from_conversation(
        auth_user["id"],
        "我准备转做后端开发",
        [{"role": "assistant", "content": "好的，我们按计划来"}],
    )

    assert "旧岗位" in captured["existing"]
    assert "旧技能" in captured["existing"]
    assert captured["request_text"] == "我准备转做后端开发"
    assert updated["target_job"] == "新岗位"
    assert updated["years_experience"] == 3
    assert updated["target_level"] == "P6"
    assert updated["target_skills"] == ["Go", "Kafka"]
    assert updated["weak_topics"] == ["分布式"]
    assert updated["learning_goal"] == "新目标"
    assert updated["interview_focus"] == ["新重点"]
    assert updated["long_term_summary"] == "新摘要"


def test_update_profile_creates_when_missing(auth_user: dict, monkeypatch) -> None:
    """用户还没有画像时，后台更新直接创建一行。"""
    monkeypatch.setattr(
        LongTermMemory,
        "_extract_profile_fields",
        lambda self, existing, request_text, context: '{"learning_style": "视频学习"}',
    )

    updated = LongTermMemory().update_profile_from_conversation(
        auth_user["id"], "我更喜欢看视频学习", "（无）"
    )

    assert updated["user_id"] == auth_user["id"]
    assert updated["learning_style"] == "视频学习"


def test_update_skips_empty_extraction(auth_user: dict, monkeypatch) -> None:
    """模型没有抽取到有效字段时不写库。"""
    monkeypatch.setattr(
        LongTermMemory,
        "_extract_profile_fields",
        lambda self, existing, request_text, context: "{}",
    )

    assert (
        LongTermMemory().update_profile_from_conversation(
            auth_user["id"], "随便聊聊", "（无）"
        )
        is None
    )
    assert user_profile_repo.get_by_user_id(auth_user["id"]) is None


def test_submit_runs_inline_thread_and_swallows_errors(monkeypatch) -> None:
    """submit 只负责拉起线程；_safe_update 吞掉线程内异常。"""
    monkeypatch.setattr(LongTermMemory, "submit_profile_update_async", _REAL_SUBMIT)
    captured: list[dict] = []
    monkeypatch.setattr(
        LongTermMemory,
        "update_profile_from_conversation",
        lambda self, user_id, request_text, context: captured.append(
            {"user_id": user_id, "request_text": request_text}
        ),
    )

    class _InlineThread:
        def __init__(self, target, args, name, daemon):
            self._target = target
            self._args = args
            assert name.startswith("profile-update-")
            assert daemon is True

        def start(self) -> None:
            self._target(*self._args)

    monkeypatch.setattr(long_term_memory.threading, "Thread", _InlineThread)

    memory = LongTermMemory()
    memory.submit_profile_update_async(7, "我想转行", "（无）")
    assert captured == [{"user_id": 7, "request_text": "我想转行"}]

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(LongTermMemory, "update_profile_from_conversation", _boom)
    memory.submit_profile_update_async(7, "我想转行", "（无）")  # 不应抛出
