"""OpenSandbox backend implementation for deepagents.

This module provides a SandboxBackendProtocol implementation using OpenSandbox SDK.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

if TYPE_CHECKING:
    from opensandbox import Sandbox

logger = logging.getLogger(__name__)


def _format_execution(execution) -> tuple[str, int]:
    """Format execution result into output string and exit code.

    Args:
        execution: OpenSandbox execution result object

    Returns:
        Tuple of (output_string, exit_code)
    """
    stdout = "\n".join(msg.text for msg in execution.logs.stdout) if execution.logs.stdout else ""
    stderr = "\n".join(msg.text for msg in execution.logs.stderr) if execution.logs.stderr else ""

    exit_code = 0
    if execution.error:
        stderr = "\n".join([
            stderr,
            f"[error] {execution.error.name}: {execution.error.value}",
        ]).strip()
        exit_code = 1

    output = stdout.strip()
    if stderr:
        output = "\n".join([output, f"[stderr]\n{stderr}"]).strip() if output else f"[stderr]\n{stderr}"

    return output or "(no output)", exit_code


class OpenSandboxBackend(BaseSandbox):
    """OpenSandbox backend implementation conforming to SandboxBackendProtocol.

    This implementation inherits all file operation methods from BaseSandbox
    and implements the execute() method using OpenSandbox's API.
    """

    def __init__(self, sandbox: Sandbox) -> None:
        """Initialize the OpenSandboxBackend with an OpenSandbox instance.

        Args:
            sandbox: Active OpenSandbox Sandbox instance
        """
        self._sandbox = sandbox
        self._timeout = 30 * 60  # 30 minutes default timeout

    @property
    def id(self) -> str:
        """Unique identifier for the sandbox backend."""
        return self._sandbox.id

    def execute(self, command: str) -> ExecuteResponse:
        """Execute a command in the sandbox and return ExecuteResponse.

        Args:
            command: Full shell command string to execute.

        Returns:
            ExecuteResponse with combined output, exit code, and truncation flag.
        """
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self._execute_sync, command)
                return future.result()
        else:
            return loop.run_until_complete(self._aexecute(command))

    def _execute_sync(self, command: str) -> ExecuteResponse:
        """Synchronous execution helper using a new event loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._aexecute(command))
        finally:
            loop.close()

    async def _aexecute(self, command: str) -> ExecuteResponse:
        """Async implementation of execute."""
        try:
            execution = await self._sandbox.commands.run(command)
            output, exit_code = _format_execution(execution)

            return ExecuteResponse(
                output=output,
                exit_code=exit_code,
                truncated=False,
            )
        except Exception as e:
            logger.error(f"OpenSandbox execute error: {e}")
            return ExecuteResponse(
                output=f"Error executing command: {e}",
                exit_code=1,
                truncated=False,
            )

    async def aexecute(self, command: str) -> ExecuteResponse:
        """Async version of execute."""
        return await self._aexecute(command)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files from the OpenSandbox.

        Args:
            paths: List of file paths to download.

        Returns:
            List of FileDownloadResponse objects, one per input path.
        """
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self._download_files_sync, paths)
                return future.result()
        else:
            return loop.run_until_complete(self._adownload_files(paths))

    def _download_files_sync(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Synchronous download helper using a new event loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._adownload_files(paths))
        finally:
            loop.close()

    async def _adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Async implementation of download_files."""
        responses = []
        for path in paths:
            try:
                content = await self._sandbox.files.read_file(path)
                if isinstance(content, str):
                    content = content.encode('utf-8')
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except Exception as e:
                logger.error(f"OpenSandbox download error for {path}: {e}")
                responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
        return responses

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Async version of download_files."""
        return await self._adownload_files(paths)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the OpenSandbox.

        Args:
            files: List of (path, content) tuples to upload.

        Returns:
            List of FileUploadResponse objects, one per input file.
        """
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self._upload_files_sync, files)
                return future.result()
        else:
            return loop.run_until_complete(self._aupload_files(files))

    def _upload_files_sync(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Synchronous upload helper using a new event loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._aupload_files(files))
        finally:
            loop.close()

    async def _aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Async implementation of upload_files."""
        responses = []
        for path, content in files:
            try:
                if isinstance(content, bytes):
                    content = content.decode('utf-8')
                await self._sandbox.files.write_file(path, content)
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception as e:
                logger.error(f"OpenSandbox upload error for {path}: {e}")
                responses.append(FileUploadResponse(path=path, error="permission_denied"))
        return responses

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Async version of upload_files."""
        return await self._aupload_files(files)


async def create_opensandbox(
    *,
    image: str | None = None,
    timeout_seconds: int = 300,
    working_dir: str = "/workspace",
) -> Sandbox:
    """Create a new OpenSandbox instance.

    Args:
        image: Docker image to use. Defaults to code-interpreter image.
        timeout_seconds: Sandbox timeout in seconds. Default 300s (5 minutes).
        working_dir: Working directory in the sandbox. Default "/workspace".

    Returns:
        Active OpenSandbox Sandbox instance.
    """
    from opensandbox import Sandbox
    from opensandbox.config import ConnectionConfig

    # 兼容官方示例的环境变量（SANDBOX_*），同时兼容现有的 OPENSANDBOX_* 配置
    domain = os.getenv("SANDBOX_DOMAIN") or os.getenv("OPENSANDBOX_DOMAIN") or "localhost:8080"
    api_key = os.getenv("SANDBOX_API_KEY") or os.getenv("OPENSANDBOX_API_KEY")

    # 关键逻辑：避免网络异常时长时间卡住对话链路，超时允许通过环境变量调整
    # 默认 10 秒，保证失败可快速降级为无沙箱模式
    request_timeout_seconds = int(
        os.getenv("SANDBOX_REQUEST_TIMEOUT_SECONDS")
        or os.getenv("OPENSANDBOX_REQUEST_TIMEOUT_SECONDS")
        or "10"
    )

    if image is None:
        image = (
            os.getenv("SANDBOX_IMAGE")
            or os.getenv("OPENSANDBOX_IMAGE")
            or "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:latest"
        )

    config = ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=request_timeout_seconds),
    )

    logger.info(
        f"OpenSandbox connection config | domain={domain} | request_timeout_seconds={request_timeout_seconds} | timeout_seconds={timeout_seconds}"
    )

    sandbox = await Sandbox.create(
        image,
        timeout=timedelta(seconds=timeout_seconds),
        connection_config=config,
    )

    logger.info(f"OpenSandbox created: {sandbox.id}")
    return sandbox


class OpenSandboxManager:
    """Manager for OpenSandbox lifecycle within a session.

    Handles sandbox creation, reuse, and cleanup for chat sessions.
    """

    def __init__(self):
        self._sandboxes: dict[str, Sandbox] = {}
        self._backends: dict[str, OpenSandboxBackend] = {}

    async def get_or_create_sandbox(
        self,
        session_id: str,
        *,
        image: str | None = None,
        timeout_seconds: int = 300,
    ) -> OpenSandboxBackend:
        """Get existing sandbox for session or create a new one.

        Args:
            session_id: Unique session identifier.
            image: Docker image to use for new sandbox.
            timeout_seconds: Timeout for new sandbox.

        Returns:
            OpenSandboxBackend instance for the session.
        """
        if session_id in self._backends:
            return self._backends[session_id]

        # 并发场景保护：同一个 session 只允许创建一个 sandbox
        # 说明：这里用 Mongo 分布式锁，避免多 worker/多进程同时创建导致资源泄露和状态混乱
        from backend.database.mongo_manager import get_mongo_manager

        mongo = get_mongo_manager()
        lock_key = f"opensandbox:create:{session_id}"
        owner_id = uuid.uuid4().hex
        acquired = False

        # 简单自旋等待（最多 5 秒），避免高并发下直接失败
        for _ in range(25):
            acquired = mongo.acquire_distributed_lock(lock_key=lock_key, owner_id=owner_id, ttl_seconds=30)
            if acquired:
                break
            await asyncio.sleep(0.2)

        if not acquired:
            raise RuntimeError("获取 OpenSandbox 创建锁失败，请稍后重试")

        try:
            # 二次检查：拿到锁后再看一次缓存，避免重复创建
            if session_id in self._backends:
                return self._backends[session_id]

            sandbox = await create_opensandbox(
                image=image,
                timeout_seconds=timeout_seconds,
            )
            backend = OpenSandboxBackend(sandbox)

            self._sandboxes[session_id] = sandbox
            self._backends[session_id] = backend
            return backend
        finally:
            mongo.release_distributed_lock(lock_key=lock_key, owner_id=owner_id)

    async def cleanup_sandbox(self, session_id: str) -> None:
        """Cleanup sandbox for a session.

        Args:
            session_id: Session identifier to cleanup.
        """
        if session_id in self._sandboxes:
            sandbox = self._sandboxes.pop(session_id)
            self._backends.pop(session_id, None)
            try:
                await sandbox.kill()
                await sandbox.close()
                logger.info(f"OpenSandbox cleaned up for session: {session_id}")
            except Exception as e:
                logger.warning(f"Error cleaning up sandbox for {session_id}: {e}")

    async def cleanup_all(self) -> None:
        """Cleanup all active sandboxes."""
        session_ids = list(self._sandboxes.keys())
        for session_id in session_ids:
            await self.cleanup_sandbox(session_id)


# Global sandbox manager instance
_sandbox_manager: OpenSandboxManager | None = None


def get_sandbox_manager() -> OpenSandboxManager:
    """Get the global sandbox manager instance."""
    global _sandbox_manager
    if _sandbox_manager is None:
        _sandbox_manager = OpenSandboxManager()
    return _sandbox_manager
