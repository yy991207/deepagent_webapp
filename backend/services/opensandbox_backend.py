"""deepagents 的 OpenSandbox 后端实现。

本模块使用 OpenSandbox SDK 提供 SandboxBackendProtocol 的实现。
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
    """格式化执行结果为输出字符串和退出码。

    参数：
        execution: OpenSandbox 执行结果对象

    返回：
        (output_string, exit_code) 元组
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
    """符合 SandboxBackendProtocol 的 OpenSandbox 后端实现。

    说明：
    - 继承 BaseSandbox 的所有文件操作方法
    - 使用 OpenSandbox 的 API 实现 execute() 方法
    """

    def __init__(self, sandbox: Sandbox, *, owner_loop: asyncio.AbstractEventLoop) -> None:
        """使用 OpenSandbox 实例初始化 OpenSandboxBackend。

        参数：
            sandbox: 活动的 OpenSandbox Sandbox 实例
        """
        self._sandbox = sandbox
        self._timeout = 30 * 60  # 30 分钟默认超时
        # 关键逻辑：OpenSandbox SDK 的底层网络客户端与事件循环强绑定。
        # 这里记录“创建 sandbox 时所在的事件循环”，后续所有同步方法都调度回这个 loop 执行，避免跨 loop 报错。
        self._owner_loop = owner_loop

    @property
    def id(self) -> str:
        """沙箱后端的唯一标识符。"""
        return self._sandbox.id

    def execute(self, command: str) -> ExecuteResponse:
        """在沙箱中执行命令并返回 ExecuteResponse。

        参数：
            command: 要执行的完整 shell 命令字符串

        返回：
            包含合并输出、退出码和截断标志的 ExecuteResponse
        """
        # 关键逻辑：无论调用方是否在事件循环里，这里都把执行调度到 owner_loop，保证与 Sandbox 创建时一致。
        try:
            future = asyncio.run_coroutine_threadsafe(self._aexecute(command), self._owner_loop)
            return future.result(timeout=self._timeout)
        except Exception as e:
            logger.error(f"OpenSandbox execute error: {e}")
            return ExecuteResponse(
                output=f"Error executing command: {e}",
                exit_code=1,
                truncated=False,
            )

    async def _aexecute(self, command: str) -> ExecuteResponse:
        """执行方法的异步实现。"""
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
        """执行方法的异步版本。"""
        return await self._aexecute(command)

    async def als_info(self, path: str) -> list[dict]:
        """异步版本的 ls_info，避免事件循环绑定问题。

        说明：
        - SkillsMiddleware 会调用 backend.als_info() 扫描 skills 目录
        - BaseSandbox 的默认实现是 asyncio.to_thread(self.ls_info)，会创建新线程
        - 新线程中的 execute() 会遇到事件循环绑定问题
        - 因此需要直接实现异步版本，使用同一个事件循环
        """
        import json

        cmd = f"""python3 -c "
import os
import json

path = '{path}'

try:
    with os.scandir(path) as it:
        for entry in it:
            result = {{
                'path': os.path.join(path, entry.name),
                'is_dir': entry.is_dir(follow_symlinks=False)
            }}
            print(json.dumps(result))
except FileNotFoundError:
    pass
except PermissionError:
    pass
" 2>/dev/null"""

        result = await self._aexecute(cmd)

        file_infos: list[dict] = []
        for line in result.output.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                file_infos.append({"path": data["path"], "is_dir": data["is_dir"]})
            except json.JSONDecodeError:
                continue

        return file_infos

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """从 OpenSandbox 下载多个文件。

        参数：
            paths: 要下载的文件路径列表

        返回：
            FileDownloadResponse 对象列表，每个输入路径对应一个
        """
        try:
            future = asyncio.run_coroutine_threadsafe(self._adownload_files(paths), self._owner_loop)
            return future.result(timeout=self._timeout)
        except Exception as e:
            logger.error(f"OpenSandbox download error: {e}")
            return [FileDownloadResponse(path=p, content=None, error="download_failed") for p in paths]

    async def _adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """下载文件方法的异步实现。"""
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
        """下载文件方法的异步版本。"""
        return await self._adownload_files(paths)

    async def aread_bytes(self, path: str) -> bytes:
        """从 sandbox 读取二进制文件内容。

        说明：
        - 使用 OpenSandbox SDK 的 read_bytes 方法直接读取二进制数据
        - 适用于 PDF、图片、Office 文档等二进制文件
        - 对于文本文件，建议使用 read_file 方法

        Args:
            path: sandbox 中的文件路径

        Returns:
            文件的二进制内容（bytes）

        Raises:
            Exception: 如果文件不存在或读取失败
        """
        return await self._sandbox.files.read_bytes(path)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """上传多个文件到 OpenSandbox。

        参数：
            files: 要上传的 (path, content) 元组列表

        返回：
            FileUploadResponse 对象列表，每个输入文件对应一个
        """
        try:
            future = asyncio.run_coroutine_threadsafe(self._aupload_files(files), self._owner_loop)
            return future.result(timeout=self._timeout)
        except Exception as e:
            logger.error(f"OpenSandbox upload error: {e}")
            return [FileUploadResponse(path=p, error="upload_failed") for p, _ in files]

    async def _aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """上传文件方法的异步实现。"""
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
        """上传文件方法的异步版本。"""
        return await self._aupload_files(files)


async def create_opensandbox(
    *,
    image: str | None = None,
    timeout_seconds: int = 300,
    working_dir: str = "/workspace",
) -> Sandbox:
    """创建一个新的 OpenSandbox 实例。

    参数：
        image: 要使用的 Docker 镜像。默认为 code-interpreter 镜像。
        timeout_seconds: 沙箱超时时间（秒）。默认 300 秒（5 分钟）。
        working_dir: 沙箱中的工作目录。默认 "/workspace"。

    返回：
        活动的 OpenSandbox Sandbox 实例
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
    # 关键逻辑：健康检查超时时间可配置，避免慢启动导致误判失败
    ready_timeout_seconds = int(
        os.getenv("SANDBOX_READY_TIMEOUT_SECONDS")
        or os.getenv("OPENSANDBOX_READY_TIMEOUT_SECONDS")
        or "30"
    )
    # 关键逻辑：必要时可跳过健康检查，避免创建阶段卡死
    skip_health_check_raw = (
        os.getenv("SANDBOX_SKIP_HEALTH_CHECK")
        or os.getenv("OPENSANDBOX_SKIP_HEALTH_CHECK")
        or ""
    ).strip().lower()
    skip_health_check = skip_health_check_raw in {"1", "true", "yes", "on"}

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
        ready_timeout=timedelta(seconds=ready_timeout_seconds),
        skip_health_check=skip_health_check,
        connection_config=config,
    )

    logger.info(f"OpenSandbox created: {sandbox.id}")
    return sandbox


class OpenSandboxManager:
    """会话内 OpenSandbox 生命周期管理器。

    说明：
    - 处理聊天会话的沙箱创建、重用和清理
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
        """获取会话的现有沙箱或创建新沙箱。

        参数：
            session_id: 唯一会话标识符
            image: 新沙箱使用的 Docker 镜像
            timeout_seconds: 新沙箱的超时时间

        返回：
            会话的 OpenSandboxBackend 实例
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
            backend = OpenSandboxBackend(sandbox, owner_loop=asyncio.get_running_loop())

            self._sandboxes[session_id] = sandbox
            self._backends[session_id] = backend
            return backend
        finally:
            mongo.release_distributed_lock(lock_key=lock_key, owner_id=owner_id)

    async def cleanup_sandbox(self, session_id: str) -> None:
        """清理会话的沙箱。

        参数：
            session_id: 要清理的会话标识符
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
        """清理所有活动的沙箱。"""
        session_ids = list(self._sandboxes.keys())
        for session_id in session_ids:
            await self.cleanup_sandbox(session_id)


# 全局沙箱管理器实例
_sandbox_manager: OpenSandboxManager | None = None


def get_sandbox_manager() -> OpenSandboxManager:
    """获取全局沙箱管理器实例。"""
    global _sandbox_manager
    if _sandbox_manager is None:
        _sandbox_manager = OpenSandboxManager()
    return _sandbox_manager
