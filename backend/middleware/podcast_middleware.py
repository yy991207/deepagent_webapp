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
    id: str
    status: str
    created_at: str


class PodcastMiddleware:
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
        self._mongo_url = mongo_url
        self._db_name = db_name
        self._sources_collection = sources_collection
        self._runs_collection = runs_collection
        self._results_collection = results_collection
        self._speaker_profiles_collection = speaker_profiles_collection
        self._episode_profiles_collection = episode_profiles_collection
        self._locks_collection = locks_collection
        self._data_dir = data_dir
        self._client: MongoClient | None = None

    def _get_client(self) -> MongoClient:
        if self._client is None:
            self._client = MongoClient(self._mongo_url)
        return self._client

    def _col(self, name: str):
        return self._get_client()[self._db_name][name]

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _iso(self, dt: datetime | None) -> str:
        if dt is None:
            return ""
        return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)

    def _new_run_id(self) -> str:
        return f"podcast-{uuid.uuid4().hex[:12]}"

    def _acquire_lock(self, *, key: str, ttl_seconds: int = 300) -> bool:
        now = self._now()
        col = self._col(self._locks_collection)
        # Clean expired lock
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
        try:
            self._col(self._locks_collection).delete_one({"_id": key})
        except Exception:
            return

    def bootstrap_profiles(self) -> dict[str, Any]:
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
        try:
            from importlib.resources import files

            p = files(pkg).joinpath(rel_path)
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _bootstrap_speaker_profiles(self) -> int:
        data = self._read_pkg_resource_json("podcast_creator", "resources/speakers_config.json")
        profiles = data.get("profiles") if isinstance(data, dict) else None
        if not isinstance(profiles, dict):
            return 0

        compatible_base = (os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or "").strip()
        compatible_key = (os.environ.get("OPENAI_COMPATIBLE_API_KEY") or "").strip()

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
                # 幂等更新：确保 TTS provider/model 能被 deepagents/.env 覆盖
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
        data = self._read_pkg_resource_json("podcast_creator", "resources/episodes_config.json")
        profiles = data.get("profiles") if isinstance(data, dict) else None
        if not isinstance(profiles, dict):
            return 0

        col = self._col(self._episode_profiles_collection)
        inserted = 0
        for name, p in profiles.items():
            if not isinstance(p, dict):
                continue

            compatible_base = (os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or "").strip()
            compatible_key = (os.environ.get("OPENAI_COMPATIBLE_API_KEY") or "").strip()

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
                # 幂等更新：确保 provider/model 能被 deepagents/.env 覆盖
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
        item = self._col(self._results_collection).find_one({"run_id": run_id}, projection={"_id": 0})
        if not item:
            return None
        created = item.get("created_at")
        return {
            **{k: v for k, v in item.items() if k != "created_at"},
            "created_at": self._iso(created) if isinstance(created, datetime) else str(created),
        }

    def start_generation_async(self, *, run_id: str) -> None:
        t = threading.Thread(target=self._run_generation, args=(run_id,), daemon=True)
        t.start()

    def _update_run_status(self, *, run_id: str, status: str, message: str | None = None) -> None:
        now = self._now()
        upd: dict[str, Any] = {"status": status, "updated_at": now}
        if message is not None:
            upd["message"] = message
        self._col(self._runs_collection).update_one({"run_id": run_id}, {"$set": upd})

    def _load_sources_content(self, *, source_ids: list[str], max_bytes: int = 300_000) -> str:
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
        start = time.time()
        run = self._col(self._runs_collection).find_one({"run_id": run_id})
        if not run:
            return

        debug_enabled = (os.environ.get("DEEPAGENTS_PODCAST_DEBUG") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        episode_profile = str(run.get("episode_profile") or "")
        speaker_profile = str(run.get("speaker_profile") or "")
        episode_name = str(run.get("episode_name") or run_id)
        source_ids = list(run.get("source_ids") or [])
        briefing_suffix = run.get("briefing_suffix")

        if not episode_profile or not speaker_profile or not episode_name:
            self._update_run_status(run_id=run_id, status="error", message="invalid config")
            return

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
    from backend.database.mongo_manager import (
        _DEFAULT_COLLECTION,
        _DEFAULT_DB_NAME,
        _DEFAULT_MONGO_URL,
    )

    runs_collection = os.environ.get("DEEPAGENTS_PODCAST_RUNS_COLLECTION") or "agent_run_records"
    results_collection = os.environ.get("DEEPAGENTS_PODCAST_RESULTS_COLLECTION") or "podcast_generation_results"
    speaker_profiles_collection = os.environ.get("DEEPAGENTS_PODCAST_SPEAKER_PROFILES_COLLECTION") or "speaker_profile"
    episode_profiles_collection = os.environ.get("DEEPAGENTS_PODCAST_EPISODE_PROFILES_COLLECTION") or "episode_profile"
    locks_collection = os.environ.get("DEEPAGENTS_LOCKS_COLLECTION") or "distributed_locks"

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
