from __future__ import annotations

import json
import os
import asyncio
import inspect
import threading
import time
import uuid
import traceback
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bson.objectid import ObjectId
from pymongo import MongoClient


@dataclass(frozen=True)
class PodcastRun:
    """播客生成运行记录的数据类。
    
    Attributes:
        id: 运行唯一标识符
        status: 运行状态（queued/running/done/error）
        created_at: 创建时间（ISO 格式字符串）
    """
    id: str
    status: str
    created_at: str


class PodcastMiddleware:
    """播客生成中间件，提供播客创建、管理和异步生成功能。
    
    功能说明：
    - 管理播客配置文件（说话人配置、节目配置）
    - 创建播客生成任务并异步执行
    - 从 MongoDB 加载源文件内容作为播客素材
    - 支持多种 TTS 提供商（OpenAI、Edge TTS 等）
    - 提供任务状态查询和结果获取接口
    
    使用场景：
    - 基于用户上传的文档生成播客节目
    - 支持多说话人、多节目类型的播客制作
    - 异步生成避免阻塞主线程
    """
    def __init__(
        self,
        *,
        mongo_url: str,
        db_name: str,
        sources_collection: str,
        runs_collection: str,
        results_collection: str,
        speaker_profiles_collection: str,
        episode_profiles_collection: str,
        locks_collection: str,
        data_dir: str,
    ) -> None:
        # MongoDB 连接配置
        self._mongo_url = mongo_url
        self._db_name = db_name
        # 集合名称配置
        self._sources_collection = sources_collection  # 源文件集合
        self._runs_collection = runs_collection  # 运行记录集合
        self._results_collection = results_collection  # 生成结果集合
        self._speaker_profiles_collection = speaker_profiles_collection  # 说话人配置集合
        self._episode_profiles_collection = episode_profiles_collection  # 节目配置集合
        self._locks_collection = locks_collection  # 分布式锁集合
        self._data_dir = data_dir  # 数据输出目录
        self._client: MongoClient | None = None  # MongoDB 客户端实例

    def _get_client(self) -> MongoClient:
        """获取 MongoDB 客户端实例，使用懒加载模式。
        
        Returns:
            MongoDB 客户端实例
        """
        if self._client is None:
            self._client = MongoClient(self._mongo_url)
        return self._client

    def _col(self, name: str):
        """获取指定名称的 MongoDB 集合。
        
        Args:
            name: 集合名称
            
        Returns:
            MongoDB 集合对象
        """
        return self._get_client()[self._db_name][name]

    def _now(self) -> datetime:
        """获取当前 UTC 时间。
        
        Returns:
            当前 UTC 时间
        """
        return datetime.now(timezone.utc)

    def _iso(self, dt: datetime | None) -> str:
        """将日期时间转换为 ISO 格式字符串。
        
        Args:
            dt: 日期时间对象，可以为 None
            
        Returns:
            ISO 格式的时间字符串，空时返回空字符串
        """
        if dt is None:
            return ""
        return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)

    def _new_run_id(self) -> str:
        """生成新的运行 ID。
        
        Returns:
            格式为 "podcast-{12位hex}" 的唯一标识符
        """
        return f"podcast-{uuid.uuid4().hex[:12]}"

    def _acquire_lock(self, *, key: str, ttl_seconds: int = 300) -> bool:
        """获取分布式锁，防止并发执行冲突。
        
        Args:
            key: 锁的唯一标识符
            ttl_seconds: 锁的生存时间（秒）
            
        Returns:
            True 表示获取成功，False 表示获取失败
        """
        now = self._now()
        col = self._col(self._locks_collection)
        # 清理过期的锁
        try:
            col.delete_one({"_id": key, "expires_at": {"$lte": now}})
        except Exception:
            pass

        doc = {
            "_id": key,
            "expires_at": now + timedelta(seconds=max(ttl_seconds, 1)),
            "created_at": now,
        }
        try:
            col.insert_one(doc)
            return True
        except Exception:
            return False

    def _release_lock(self, *, key: str) -> None:
        """释放分布式锁。
        
        Args:
            key: 锁的唯一标识符
        """
        try:
            self._col(self._locks_collection).delete_one({"_id": key})
        except Exception:
            return

    def bootstrap_profiles(self) -> dict[str, Any]:
        """初始化播客配置文件（说话人配置和节目配置）。
        
        功能：
        - 从 podcast_creator 包中读取默认配置
        - 将配置写入 MongoDB 集合
        - 支持环境变量覆盖 TTS/LLM 提供商配置
        - 使用分布式锁防止并发初始化
        
        Returns:
            包含初始化结果的字典：
            - ok: 是否成功
            - skipped: 是否跳过（已存在其他进程在初始化）
            - inserted_speaker_profiles: 新增的说话人配置数量
            - inserted_episode_profiles: 新增的节目配置数量
        """
        if not self._acquire_lock(key="podcast:bootstrap", ttl_seconds=120):
            return {"ok": True, "skipped": True}
        try:
            inserted_speakers = self._bootstrap_speaker_profiles()
            inserted_episodes = self._bootstrap_episode_profiles()
            return {
                "ok": True,
                "inserted_speaker_profiles": inserted_speakers,
                "inserted_episode_profiles": inserted_episodes,
            }
        finally:
            self._release_lock(key="podcast:bootstrap")

    def _read_pkg_resource_json(self, pkg: str, rel_path: str) -> dict[str, Any]:
        """从 Python 包中读取 JSON 资源文件。
        
        Args:
            pkg: 包名
            rel_path: 相对于包的文件路径
            
        Returns:
            解析后的 JSON 数据，失败时返回空字典
        """
        try:
            from importlib.resources import files

            p = files(pkg).joinpath(rel_path)
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _bootstrap_speaker_profiles(self) -> int:
        """初始化说话人配置文件。
        
        处理逻辑：
        - 从 podcast_creator 包中读取说话人配置
        - 支持环境变量覆盖 TTS 提供商和模型
        - 幂等插入：已存在的配置只更新可覆盖字段
        
        Returns:
            新增的说话人配置数量
        """
        data = self._read_pkg_resource_json("podcast_creator", "resources/speakers_config.json")
        profiles = data.get("profiles") if isinstance(data, dict) else None
        if not isinstance(profiles, dict):
            return 0

        # 检查 OpenAI 兼容配置，用于覆盖默认 TTS 提供商
        compatible_base = (os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or "").strip()
        compatible_key = (os.environ.get("OPENAI_COMPATIBLE_API_KEY") or "").strip()

        # 环境变量覆盖 TTS 提供商
        tts_provider_override = (os.environ.get("PODCAST_TTS_PROVIDER") or "").strip()
        if not tts_provider_override and compatible_base and compatible_key:
            tts_provider_override = "openai-compatible"
        tts_model_override = (os.environ.get("PODCAST_TTS_MODEL") or "").strip()

        col = self._col(self._speaker_profiles_collection)
        inserted = 0
        for name, p in profiles.items():
            if not isinstance(p, dict):
                continue
            doc = {
                "name": str(name),
                "description": "",
                "tts_provider": tts_provider_override or str(p.get("tts_provider") or ""),
                "tts_model": tts_model_override or str(p.get("tts_model") or ""),
                "speakers": list(p.get("speakers") or []),
                "created_at": self._now(),
            }
            existing = col.find_one({"name": doc["name"]}, projection={"_id": 1})
            if existing:
                # 幂等更新：确保 TTS provider/model 能被环境变量覆盖
                col.update_one(
                    {"name": doc["name"]},
                    {
                        "$set": {
                            "tts_provider": doc["tts_provider"],
                            "tts_model": doc["tts_model"],
                            "speakers": doc["speakers"],
                        }
                    },
                )
                continue
            col.insert_one(doc)
            inserted += 1
        return inserted

    def _bootstrap_episode_profiles(self) -> int:
        """初始化节目配置文件。
        
        处理逻辑：
        - 从 podcast_creator 包中读取节目配置
        - 支持环境变量覆盖 LLM 提供商和模型
        - 幂等插入：已存在的配置只更新可覆盖字段
        
        Returns:
            新增的节目配置数量
        """
        data = self._read_pkg_resource_json("podcast_creator", "resources/episodes_config.json")
        profiles = data.get("profiles") if isinstance(data, dict) else None
        if not isinstance(profiles, dict):
            return 0

        col = self._col(self._episode_profiles_collection)
        inserted = 0
        for name, p in profiles.items():
            if not isinstance(p, dict):
                continue

            # 检查 OpenAI 兼容配置，用于覆盖默认 LLM 提供商
            compatible_base = (os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or "").strip()
            compatible_key = (os.environ.get("OPENAI_COMPATIBLE_API_KEY") or "").strip()

            # 确定大纲生成提供商
            provider = (
                os.environ.get("PODCAST_OUTLINE_PROVIDER")
                or os.environ.get("PODCAST_LLM_PROVIDER")
                or ("openai-compatible" if (compatible_base and compatible_key) else "openai")
            ).strip()
            model = (
                os.environ.get("PODCAST_OUTLINE_MODEL")
                or os.environ.get("PODCAST_LLM_MODEL")
                or os.environ.get("OPENAI_MODEL")
                or ""
            ).strip()
            # 确定转录生成提供商
            transcript_provider = (
                os.environ.get("PODCAST_TRANSCRIPT_PROVIDER")
                or provider
            ).strip()
            transcript_model = (os.environ.get("PODCAST_TRANSCRIPT_MODEL") or model).strip()

            doc = {
                "name": str(name),
                "description": "",
                "speaker_config": str(p.get("speaker_config") or ""),
                "outline_provider": provider,
                "outline_model": model,
                "transcript_provider": transcript_provider,
                "transcript_model": transcript_model,
                "default_briefing": str(p.get("default_briefing") or ""),
                "num_segments": int(p.get("num_segments") or 4),
                "created_at": self._now(),
            }
            existing = col.find_one({"name": doc["name"]}, projection={"_id": 1})
            if existing:
                # 幂等更新：确保 provider/model 能被环境变量覆盖
                col.update_one(
                    {"name": doc["name"]},
                    {
                        "$set": {
                            "speaker_config": doc["speaker_config"],
                            "outline_provider": doc["outline_provider"],
                            "outline_model": doc["outline_model"],
                            "transcript_provider": doc["transcript_provider"],
                            "transcript_model": doc["transcript_model"],
                            "default_briefing": doc["default_briefing"],
                            "num_segments": doc["num_segments"],
                        }
                    },
                )
                continue
            col.insert_one(doc)
            inserted += 1
        return inserted

    def list_speaker_profiles(self) -> list[dict[str, Any]]:
        """获取所有说话人配置列表。
        
        Returns:
            说话人配置列表，每个配置包含 id/name/description/tts_provider/tts_model/speakers 字段
        """
        cursor = self._col(self._speaker_profiles_collection).find({}, projection={}).sort("name", 1)
        out: list[dict[str, Any]] = []
        for item in cursor:
            out.append(
                {
                    "id": str(item.get("_id")),
                    "name": str(item.get("name") or ""),
                    "description": str(item.get("description") or ""),
                    "tts_provider": str(item.get("tts_provider") or ""),
                    "tts_model": str(item.get("tts_model") or ""),
                    "speakers": item.get("speakers") or [],
                }
            )
        return out

    def list_episode_profiles(self) -> list[dict[str, Any]]:
        """获取所有节目配置列表。
        
        Returns:
            节目配置列表，每个配置包含 id/name/description/speaker_config/outline_provider 等字段
        """
        cursor = self._col(self._episode_profiles_collection).find({}, projection={}).sort("name", 1)
        out: list[dict[str, Any]] = []
        for item in cursor:
            out.append(
                {
                    "id": str(item.get("_id")),
                    "name": str(item.get("name") or ""),
                    "description": str(item.get("description") or ""),
                    "speaker_config": str(item.get("speaker_config") or ""),
                    "outline_provider": str(item.get("outline_provider") or ""),
                    "outline_model": str(item.get("outline_model") or ""),
                    "transcript_provider": str(item.get("transcript_provider") or ""),
                    "transcript_model": str(item.get("transcript_model") or ""),
                    "default_briefing": str(item.get("default_briefing") or ""),
                    "num_segments": int(item.get("num_segments") or 0),
                }
            )
        return out

    def create_run(
        self,
        *,
        episode_profile: str,
        speaker_profile: str,
        source_ids: list[str],
        episode_name: str,
        briefing_suffix: str | None,
    ) -> PodcastRun:
        """创建新的播客生成任务。
        
        Args:
            episode_profile: 节目配置名称
            speaker_profile: 说话人配置名称
            source_ids: 源文件 ID 列表（MongoDB ObjectId）
            episode_name: 节目名称
            briefing_suffix: 可选的附加说明文本
            
        Returns:
            新创建的播客运行记录对象
        """
        now = self._now()
        run_id = self._new_run_id()
        doc = {
            "run_id": run_id,
            "status": "queued",
            "episode_profile": episode_profile,
            "speaker_profile": speaker_profile,
            "episode_name": episode_name,
            "source_ids": source_ids,
            "briefing_suffix": briefing_suffix,
            "created_at": now,
            "updated_at": now,
        }
        self._col(self._runs_collection).insert_one(doc)
        return PodcastRun(id=run_id, status="queued", created_at=self._iso(now))

    def list_runs(self, *, limit: int = 50, skip: int = 0) -> list[dict[str, Any]]:
        """获取播客运行记录列表。
        
        Args:
            limit: 最大返回数量（最大 200）
            skip: 跳过的记录数量
            
        Returns:
            运行记录列表，按创建时间倒序排列
        """
        cursor = (
            self._col(self._runs_collection)
            .find({}, projection={"_id": 0})
            .sort("created_at", -1)
            .skip(max(skip, 0))
            .limit(max(min(limit, 200), 1))
        )
        out: list[dict[str, Any]] = []
        for item in cursor:
            created = item.get("created_at")
            updated = item.get("updated_at")
            out.append(
                {
                    **{k: v for k, v in item.items() if k not in ("created_at", "updated_at")},
                    "created_at": self._iso(created) if isinstance(created, datetime) else str(created),
                    "updated_at": self._iso(updated) if isinstance(updated, datetime) else str(updated),
                }
            )
        return out

    def get_run_detail(self, *, run_id: str) -> dict[str, Any] | None:
        """获取指定运行记录的详细信息。
        
        Args:
            run_id: 运行 ID
            
        Returns:
            运行记录详情，不存在时返回 None
        """
        item = self._col(self._runs_collection).find_one({"run_id": run_id}, projection={"_id": 0})
        if not item:
            return None
        created = item.get("created_at")
        updated = item.get("updated_at")
        return {
            **{k: v for k, v in item.items() if k not in ("created_at", "updated_at")},
            "created_at": self._iso(created) if isinstance(created, datetime) else str(created),
            "updated_at": self._iso(updated) if isinstance(updated, datetime) else str(updated),
        }

    def get_result(self, *, run_id: str) -> dict[str, Any] | None:
        """获取指定运行的结果数据。
        
        Args:
            run_id: 运行 ID
            
        Returns:
            生成结果数据，包含 audio_file_path/transcript/outline 等字段，不存在时返回 None
        """
        item = self._col(self._results_collection).find_one({"run_id": run_id}, projection={"_id": 0})
        if not item:
            return None
        created = item.get("created_at")
        return {
            **{k: v for k, v in item.items() if k != "created_at"},
            "created_at": self._iso(created) if isinstance(created, datetime) else str(created),
        }

    def delete_run(self, *, run_id: str) -> bool:
        """删除指定的播客运行记录及其结果。

        说明：
        - 仅删除 MongoDB 中的运行记录和结果数据
        - 不主动删除本地音频文件，避免误删用户可能复用的资源
        """

        col_runs = self._col(self._runs_collection)
        col_results = self._col(self._results_collection)

        try:
            res = col_runs.delete_one({"run_id": run_id})
        except Exception:
            return False

        # 结果表按 run_id 清理即可，删除失败不影响主流程
        try:
            col_results.delete_many({"run_id": run_id})
        except Exception:
            pass

        return bool(res.deleted_count)

    def start_generation_async(self, *, run_id: str) -> None:
        """异步启动播客生成任务。
        
        Args:
            run_id: 运行 ID
        """
        t = threading.Thread(target=self._run_generation, args=(run_id,), daemon=True)
        t.start()

    def _update_run_status(self, *, run_id: str, status: str, message: str | None = None) -> None:
        """更新运行状态。
        
        Args:
            run_id: 运行 ID
            status: 新状态（queued/running/done/error）
            message: 可选的状态消息或错误信息
        """
        now = self._now()
        upd: dict[str, Any] = {"status": status, "updated_at": now}
        if message is not None:
            upd["message"] = message
        self._col(self._runs_collection).update_one({"run_id": run_id}, {"$set": upd})

    def _load_sources_content(self, *, source_ids: list[str], max_bytes: int = 300_000) -> str:
        """从 MongoDB 加载源文件内容，作为播客生成的素材。
        
        Args:
            source_ids: 源文件 ID 列表（MongoDB ObjectId）
            max_bytes: 每个文件最大读取字节数，防止内存溢出
            
        Returns:
            合并后的文件内容文本，格式为文件名+路径+内容的组合
        """
        parts: list[str] = []
        col = self._col(self._sources_collection)
        for sid in source_ids:
            try:
                oid = ObjectId(sid)
            except Exception:
                continue
            item = col.find_one({"_id": oid})
            if not item:
                continue
            filename = str(item.get("filename") or "")
            rel_path = str(item.get("rel_path") or "")
            content = item.get("content")
            text = ""
            try:
                # 处理二进制内容，限制读取大小
                if isinstance(content, (bytes, bytearray)):
                    raw = bytes(content)
                else:
                    raw = bytes(content)  # type: ignore[arg-type]
                raw = raw[: max(max_bytes, 0)]
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                text = ""
            if not text:
                continue
            parts.append(f"# {filename}\n{rel_path}\n\n{text}")
        return "\n\n---\n\n".join(parts).strip()

    def _run_generation(self, run_id: str) -> None:
        """播客生成的核心执行方法（在独立线程中运行）。
        
        处理流程：
        1. 读取运行配置和源文件内容
        2. 初始化播客配置文件
        3. 兼容 Edge TTS（临时拦截 AIFactory）
        4. 调用 podcast_creator 生成播客
        5. 保存生成结果到数据库
        6. 恢复原始 AIFactory 实现
        
        Args:
            run_id: 运行 ID
        """
        start = time.time()
        run = self._col(self._runs_collection).find_one({"run_id": run_id})
        if not run:
            return

        # 检查调试模式开关
        debug_enabled = (os.environ.get("DEEPAGENTS_PODCAST_DEBUG") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        # 提取运行配置
        episode_profile = str(run.get("episode_profile") or "")
        speaker_profile = str(run.get("speaker_profile") or "")
        episode_name = str(run.get("episode_name") or run_id)
        source_ids = list(run.get("source_ids") or [])
        briefing_suffix = run.get("briefing_suffix")

        # 验证必要配置
        if not episode_profile or not speaker_profile or not episode_name:
            self._update_run_status(run_id=run_id, status="error", message="invalid config")
            return

        # 更新状态为运行中
        self._update_run_status(run_id=run_id, status="running")

        try:
            from podcast_creator import configure, create_podcast

            if debug_enabled:
                print(f"[podcast] run_id={run_id} start")

            # 兼容 Edge TTS：esperanto 默认没有 edge provider，这里做最小化适配。
            # 只在本次生成过程中临时拦截 AIFactory.create_text_to_speech，生成结束后恢复。
            try:
                from esperanto import AIFactory  # type: ignore

                _orig_create_tts = AIFactory.create_text_to_speech

                class _EdgeTTSWrapper:
                    def __init__(self, model_name: str | None = None, **kwargs: Any) -> None:
                        self.model_name = model_name or "neural"

                    async def agenerate_speech(
                        self,
                        *,
                        text: str,
                        voice: str | None = None,
                        output_file: str | Path | None = None,
                        **kwargs: Any,
                    ) -> dict[str, Any]:
                        import edge_tts

                        v = (voice or "").strip()

                        default_voice = (
                            os.environ.get("PODCAST_EDGE_TTS_VOICE_DEFAULT")
                            or "zh-CN-XiaoxiaoNeural"
                        ).strip()
                        alt_voice = (
                            os.environ.get("PODCAST_EDGE_TTS_VOICE_ALT")
                            or "zh-CN-YunyangNeural"
                        ).strip()

                        if not v:
                            v = default_voice
                        elif "Neural" not in v:
                            seed = zlib.crc32(v.encode("utf-8"))
                            v = alt_voice if (seed % 2 == 1) else default_voice

                        communicate = edge_tts.Communicate(text, v)
                        if output_file is not None:
                            out = Path(output_file)
                            out.parent.mkdir(parents=True, exist_ok=True)
                            await communicate.save(str(out))
                            return {"audio_file": str(out)}
                        return {"audio_file": None}

                def _create_tts_patched(provider: str, model_name: str, **kwargs: Any):
                    p = (provider or "").strip().lower()
                    if p in {"edge", "edgetts", "edge-tts"}:
                        return _EdgeTTSWrapper(model_name=model_name, **kwargs)
                    return _orig_create_tts(provider, model_name, **kwargs)

                AIFactory.create_text_to_speech = staticmethod(_create_tts_patched)  # type: ignore[assignment]
            except Exception:
                _orig_create_tts = None

            self.bootstrap_profiles()

            if debug_enabled:
                print(f"[podcast] run_id={run_id} profiles bootstrapped")

            episode_profiles = {p["name"]: p for p in self.list_episode_profiles()}
            speaker_profiles = {p["name"]: p for p in self.list_speaker_profiles()}

            if episode_profile not in episode_profiles:
                raise ValueError("episode profile not found")
            if speaker_profile not in speaker_profiles:
                raise ValueError("speaker profile not found")

            ep = episode_profiles[episode_profile]
            sp = speaker_profiles[speaker_profile]

            briefing = str(ep.get("default_briefing") or "")
            if briefing_suffix:
                briefing = (briefing + "\n\n" + str(briefing_suffix)).strip()

            content = self._load_sources_content(source_ids=source_ids)
            if not content:
                raise ValueError("empty content")

            configure("speakers_config", {"profiles": speaker_profiles})
            configure("episode_config", {"profiles": episode_profiles})

            if debug_enabled:
                print(
                    f"[podcast] run_id={run_id} configured: episode_profile={episode_profile}, speaker_profile={speaker_profile}"
                )

            out_dir = Path(self._data_dir) / "podcasts" / run_id
            out_dir.mkdir(parents=True, exist_ok=True)

            # Force provider to openai-compatible if OPENAI_COMPATIBLE_* is set
            compatible_base = (os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or "").strip()
            compatible_key = (os.environ.get("OPENAI_COMPATIBLE_API_KEY") or "").strip()
            tts_provider_override = (os.environ.get("PODCAST_TTS_PROVIDER") or "").strip().lower()
            prefer_edge_tts = tts_provider_override in {"edge", "edgetts", "edge-tts"}
            if compatible_base and compatible_key:
                if not prefer_edge_tts:
                    if not str(sp.get("tts_provider") or "") or sp.get("tts_provider") == "openai":
                        sp["tts_provider"] = "openai-compatible"
                if not str(ep.get("outline_provider") or "") or ep.get("outline_provider") == "openai":
                    ep["outline_provider"] = "openai-compatible"
                if not str(ep.get("transcript_provider") or "") or ep.get("transcript_provider") == "openai":
                    ep["transcript_provider"] = "openai-compatible"

            maybe = create_podcast(
                content=content,
                briefing=briefing,
                episode_name=episode_name,
                output_dir=str(out_dir),
                speaker_config=speaker_profile,
                episode_profile=episode_profile,
            )
            if inspect.isawaitable(maybe):
                result = asyncio.run(maybe)  # type: ignore[arg-type]
            else:
                result = maybe

            audio_file_path = None
            transcript = None
            outline = None
            if isinstance(result, dict):
                audio_file_path = result.get("final_output_file_path")
                transcript = result.get("transcript")
                outline = result.get("outline")

            def _to_serializable(v: Any) -> Any:
                try:
                    from pydantic import BaseModel  # type: ignore

                    if isinstance(v, BaseModel):
                        return v.model_dump()
                except Exception:
                    pass

                if isinstance(v, dict):
                    return {k: _to_serializable(val) for k, val in v.items()}
                if isinstance(v, (list, tuple)):
                    return [_to_serializable(item) for item in v]
                return v

            transcript = _to_serializable(transcript)
            outline = _to_serializable(outline)

            if debug_enabled:
                t_len = len(transcript) if isinstance(transcript, list) else (-1 if transcript is None else 1)
                print(f"[podcast] run_id={run_id} result: audio={bool(audio_file_path)}, transcript_items={t_len}")

            doc = {
                "run_id": run_id,
                "episode_profile": episode_profile,
                "speaker_profile": speaker_profile,
                "episode_name": episode_name,
                "audio_file_path": str(audio_file_path) if audio_file_path else None,
                "transcript": transcript,
                "outline": outline,
                "created_at": self._now(),
                "processing_time": float(time.time() - start),
            }
            self._col(self._results_collection).update_one({"run_id": run_id}, {"$set": doc}, upsert=True)
            self._update_run_status(run_id=run_id, status="done")
        except Exception as exc:
            if debug_enabled:
                print(f"[podcast] run_id={run_id} error={exc!s}")
                print(traceback.format_exc())
            self._update_run_status(run_id=run_id, status="error", message=str(exc) or "failed")
        finally:
            # 恢复 esperanto AIFactory.create_text_to_speech
            try:
                if "_orig_create_tts" in locals() and _orig_create_tts is not None:
                    from esperanto import AIFactory  # type: ignore

                    AIFactory.create_text_to_speech = _orig_create_tts  # type: ignore[assignment]
            except Exception:
                pass


def build_podcast_middleware() -> PodcastMiddleware:
    """构建播客中间件实例的工厂函数。
    
    功能：
    - 从环境变量读取 MongoDB 连接配置
    - 设置默认的集合名称
    - 确定数据输出目录
    - 创建并返回配置好的 PodcastMiddleware 实例
    
    Returns:
        配置完整的播客中间件实例
    """
    from backend.database.mongo_manager import (
        _DEFAULT_COLLECTION,
        _DEFAULT_DB_NAME,
        _DEFAULT_MONGO_URL,
    )

    # 从环境变量读取集合名称配置，支持自定义覆盖
    runs_collection = os.environ.get("DEEPAGENTS_PODCAST_RUNS_COLLECTION") or "agent_run_records"
    results_collection = os.environ.get("DEEPAGENTS_PODCAST_RESULTS_COLLECTION") or "podcast_generation_results"
    speaker_profiles_collection = os.environ.get("DEEPAGENTS_PODCAST_SPEAKER_PROFILES_COLLECTION") or "speaker_profile"
    episode_profiles_collection = os.environ.get("DEEPAGENTS_PODCAST_EPISODE_PROFILES_COLLECTION") or "episode_profile"
    locks_collection = os.environ.get("DEEPAGENTS_LOCKS_COLLECTION") or "distributed_locks"

    # 确定数据输出目录，默认为项目根目录下的 data 文件夹
    data_dir = os.environ.get("DEEPAGENTS_DATA_DIR") or str(Path(__file__).resolve().parents[3] / "data")

    return PodcastMiddleware(
        mongo_url=_DEFAULT_MONGO_URL,
        db_name=_DEFAULT_DB_NAME,
        sources_collection=_DEFAULT_COLLECTION,
        runs_collection=runs_collection,
        results_collection=results_collection,
        speaker_profiles_collection=speaker_profiles_collection,
        episode_profiles_collection=episode_profiles_collection,
        locks_collection=locks_collection,
        data_dir=data_dir,
    )
