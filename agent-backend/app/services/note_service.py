"""业务层：笔记保存。

只暴露学习测评笔记的保存入口：按 (user_id, source_run_id) 幂等写入 notes，
成功后把 note_id / note_status 回写 workflow_runs.state_json，供前端判断归档状态。
"""

import logging
from typing import Any

from fastapi import status
from sqlalchemy.exc import IntegrityError

from ..core.exceptions import BusinessException
from ..db import note_repo, workflow_run_repo

logger = logging.getLogger(__name__)

NOTE_TYPE_LEARNING_QUIZ = "learning_quiz"
NOTE_STATUS_SAVED = "saved"
NOTE_STATUS_EXISTING = "existing"


class NoteService:
    """笔记保存服务；不负责内容生成，只处理幂等落库与运行状态回写。"""

    def save_learning_quiz_note(
        self,
        user_id: int,
        session_id: int,
        source_run_id: str,
        archive: dict[str, Any],
    ) -> dict[str, Any]:
        """保存测评笔记；同一用户同一运行重复调用返回已有笔记。"""
        title = str(archive.get("title") or "").strip()
        content = str(archive.get("content") or "").strip()
        if not title or not content:
            raise BusinessException(
                "笔记标题或正文为空，无法保存",
                http_status=status.HTTP_400_BAD_REQUEST,
                detail=f"run_id={source_run_id}",
            )

        note = note_repo.get_by_user_and_run(user_id, source_run_id)
        note_status = NOTE_STATUS_EXISTING

        if note is None:
            try:
                note = note_repo.insert(
                    {
                        "user_id": user_id,
                        "session_id": session_id,
                        "source_run_id": source_run_id,
                        "note_type": NOTE_TYPE_LEARNING_QUIZ,
                        "title": title,
                        "content": content,
                        "tags": archive.get("tags") or [],
                        "metadata_json": archive.get("metadata") or {},
                    }
                )
                note_status = NOTE_STATUS_SAVED
            except IntegrityError:
                # 并发保存同一运行时由唯一约束兜底：回查已写入的那一条
                note = note_repo.get_by_user_and_run(user_id, source_run_id)
                if note is None:
                    raise
                note_status = NOTE_STATUS_EXISTING

        self._write_back_run_state(user_id, source_run_id, note["id"], note_status)
        return {"note_id": note["id"], "note_status": note_status}

    def _write_back_run_state(
        self, user_id: int, source_run_id: str, note_id: int, note_status: str
    ) -> None:
        """只往 state_json 补 note_id / note_status，避免把整份笔记塞进运行记录。"""
        row = workflow_run_repo.get_for_user(source_run_id, user_id)
        if row is None:
            logger.warning("笔记已保存但运行记录不存在 | run_id=%s", source_run_id)
            return

        state = dict(row.get("state_json") or {})
        state["note_id"] = note_id
        # 一旦笔记落库就是 saved，重复保存不能把它降级成 existing
        if state.get("note_status") != NOTE_STATUS_SAVED:
            state["note_status"] = note_status
        try:
            workflow_run_repo.update(source_run_id, {"state_json": state})
        except Exception:
            # 笔记已落库，回写失败只告警，避免把成功归档标记成失败
            logger.warning(
                "笔记状态回写失败 | run_id=%s note_id=%s",
                source_run_id,
                note_id,
                exc_info=True,
            )
