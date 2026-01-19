"""聊天服务类 - 负责聊天记录的保存和管理"""
import logging
from typing import Any
from backend.database.mongo_manager import get_mongo_manager

logger = logging.getLogger(__name__)


class ChatService:
    """聊天服务类"""
    
    def __init__(self):
        self.mongo = get_mongo_manager()
    
    def save_user_message(
        self,
        thread_id: str,
        assistant_id: str,
        content: str,
        attachments: list[Any] | None = None,
    ) -> bool:
        """保存用户消息，返回是否成功"""
        try:
            self.mongo.append_chat_message(
                thread_id=thread_id,
                assistant_id=assistant_id,
                role="user",
                content=content,
                attachments=attachments or [],
            )
            logger.info(f"SUCCESS 用户消息已保存 | thread_id={thread_id} | content_len={len(content)}")
            return True
        except Exception as e:
            logger.error(f"FAIL 用户消息保存失败 | thread_id={thread_id} | error={e}")
            return False
    
    def save_assistant_message(
        self,
        thread_id: str,
        assistant_id: str,
        content: str,
        attachments: list[Any] | None = None,
        references: list[dict[str, Any]] | None = None,
        suggested_questions: list[str] | None = None,
    ) -> bool:
        """保存 AI 回复消息，返回是否成功"""
        try:
            self.mongo.append_chat_message(
                thread_id=thread_id,
                assistant_id=assistant_id,
                role="assistant",
                content=content,
                attachments=attachments or [],
                references=references or [],
                suggested_questions=suggested_questions or [],
            )
            logger.info(f"SUCCESS AI 回复已保存 | thread_id={thread_id} | content_len={len(content)}")
            return True
        except Exception as e:
            logger.error(f"FAIL AI 回复保存失败 | thread_id={thread_id} | error={e}")
            return False
    
    def save_chat_memory(
        self,
        thread_id: str,
        assistant_id: str,
        user_text: str,
        assistant_text: str,
    ) -> bool:
        """保存聊天记忆，返回是否成功"""
        try:
            self.mongo.append_chat_memory(
                thread_id=thread_id,
                assistant_id=assistant_id,
                user_text=user_text,
                assistant_text=assistant_text,
            )
            logger.info(f"SUCCESS 聊天记忆已保存 | thread_id={thread_id}")
            return True
        except Exception as e:
            logger.error(f"FAIL 聊天记忆保存失败 | thread_id={thread_id} | error={e}")
            return False
    
    def get_chat_history(self, thread_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """获取聊天历史"""
        try:
            return self.mongo.get_chat_history(thread_id=thread_id, limit=limit)
        except Exception as e:
            logger.error(f"FAIL 获取聊天历史失败 | thread_id={thread_id} | error={e}")
            return []
    
    def get_chat_memory(self, thread_id: str, assistant_id: str) -> str:
        """获取聊天记忆"""
        try:
            return self.mongo.get_chat_memory(thread_id=thread_id, assistant_id=assistant_id)
        except Exception as e:
            logger.error(f"FAIL 获取聊天记忆失败 | thread_id={thread_id} | error={e}")
            return ""
