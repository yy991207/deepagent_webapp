"""Sandbox module for deepagents-webapp.

This module provides sandbox backends for executing code in isolated environments.
"""

from backend.services.opensandbox_backend import (
    OpenSandboxBackend,
    OpenSandboxManager,
    create_opensandbox,
    get_sandbox_manager,
)

__all__ = [
    "OpenSandboxBackend",
    "OpenSandboxManager",
    "create_opensandbox",
    "get_sandbox_manager",
]
