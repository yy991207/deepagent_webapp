from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillsSyncResult:
    """skills 同步结果。

    说明：
    - events 用于让上层（ChatStreamService）按需推送 SSE 事件
    - 这里只做同步与自检，不做任何对话链路的编排
    """

    events: list[dict[str, Any]]
    uploaded_files: int
    uploaded_failed: int


class SkillsSyncService:
    """skills 同步服务（很薄的一层）。

    只负责：
    - 扫描本地 skills/skills/*/SKILL.md
    - 在沙箱里 mkdir 目录
    - aupload_files 上传
    - 自检（ls/head）

    注意：
    - 这里不创建 sandbox，只接收 sandbox_backend
    - 这里不负责分布式锁（创建沙箱那层已经做过锁）
    """

    def __init__(self, *, base_dir: Path) -> None:
        self._base_dir = base_dir

    async def sync_skills_to_sandbox(
        self,
        *,
        sandbox_backend: Any,
        session_id: str,
        remote_root: str = "/workspace/skills/skills",
    ) -> SkillsSyncResult:
        events: list[dict[str, Any]] = []

        try:
            local_skills_root = self._base_dir / "skills" / "skills"
            logger.info(
                "skills sync start | session_id=%s | local_skills_root=%s | exists=%s",
                session_id,
                str(local_skills_root),
                str(local_skills_root.exists()),
            )

            if not local_skills_root.exists():
                return SkillsSyncResult(events=events, uploaded_files=0, uploaded_failed=0)

            files_to_upload: list[tuple[str, bytes]] = []
            skill_dirs_to_create: list[str] = []

            # 扫描本地 skills 目录，收集所有 SKILL.md 文件
            for skill_dir in local_skills_root.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue
                skill_dirs_to_create.append(skill_dir.name)
                remote_path = f"{remote_root}/{skill_dir.name}/SKILL.md"
                files_to_upload.append((remote_path, skill_md.read_bytes()))

            logger.info(
                "skills files prepared | session_id=%s | files_count=%s | dirs_count=%s",
                session_id,
                len(files_to_upload),
                len(skill_dirs_to_create),
            )

            if not files_to_upload:
                return SkillsSyncResult(events=events, uploaded_files=0, uploaded_failed=0)

            # 关键逻辑：确保 skills 根目录和所有子目录存在（一次性执行）
            mkdir_cmds = [f"mkdir -p {remote_root}"]
            mkdir_cmds.extend([f"mkdir -p {remote_root}/{name}" for name in skill_dirs_to_create])
            mkdir_all_cmd = " && ".join(mkdir_cmds)

            try:
                mkdir_result = await sandbox_backend.aexecute(mkdir_all_cmd)
                logger.info(
                    "mkdir skills dirs | session_id=%s | exit_code=%s | dirs_count=%s",
                    session_id,
                    getattr(mkdir_result, "exit_code", ""),
                    len(skill_dirs_to_create),
                )
                if getattr(mkdir_result, "exit_code", 0) != 0:
                    logger.warning("mkdir skills dirs non-zero | output=%s", getattr(mkdir_result, "output", ""))
            except Exception as exc:
                logger.warning("mkdir skills dirs failed: %s: %s", type(exc).__name__, str(exc))

            # 关键逻辑：上传文件并检查每个文件的上传结果（使用异步方法）
            upload_responses = await sandbox_backend.aupload_files(files_to_upload)

            success_count = 0
            error_count = 0
            for resp in upload_responses or []:
                if getattr(resp, "error", None):
                    error_count += 1
                    logger.error(
                        "skill upload FAILED | session_id=%s | path=%s | error=%s",
                        session_id,
                        getattr(resp, "path", ""),
                        getattr(resp, "error", ""),
                    )
                else:
                    success_count += 1
                    logger.debug(
                        "skill upload OK | session_id=%s | path=%s",
                        session_id,
                        getattr(resp, "path", ""),
                    )

            logger.info(
                "skills upload summary | session_id=%s | success=%s | failed=%s | total=%s",
                session_id,
                success_count,
                error_count,
                len(upload_responses or []),
            )

            # 关键逻辑：同步后做一次目录自检（不影响主链路，只做日志）
            try:
                check = await sandbox_backend.aexecute(f"ls -la {remote_root} || true")
                logger.info("sandbox skills dir check | session_id=%s | %s", session_id, getattr(check, "output", ""))

                # 抽一个文件做 head 检查
                if files_to_upload:
                    sample_path = files_to_upload[0][0]
                    head_check = await sandbox_backend.aexecute(
                        f"head -n 5 {sample_path} 2>&1 || echo 'FILE_NOT_FOUND'"
                    )
                    logger.info(
                        "skill file sample check | session_id=%s | path=%s | output=%s",
                        session_id,
                        sample_path,
                        str(getattr(head_check, "output", ""))[:200],
                    )
            except Exception as exc:
                logger.warning("sandbox skills dir check failed: %s: %s", type(exc).__name__, str(exc))

            return SkillsSyncResult(events=events, uploaded_files=success_count, uploaded_failed=error_count)
        except Exception as exc:
            logger.warning("sync skills to sandbox failed: %s: %s", type(exc).__name__, str(exc))
            return SkillsSyncResult(events=events, uploaded_files=0, uploaded_failed=0)
