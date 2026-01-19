"""
测试会话管理接口
验证 session_id 绑定、checkpoint 清理、删除会话功能
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiosqlite
from backend.database.mongo_manager import get_mongo_manager
from backend.services.checkpoint_service import CheckpointService
from backend.utils.snowflake import generate_snowflake_id
from deepagents_cli.sessions import get_db_path


async def test_session_apis():
    """测试会话管理完整流程"""
    print("\n" + "="*60)
    print("会话管理接口测试")
    print("="*60)
    
    mongo = get_mongo_manager()
    checkpoint_service = CheckpointService()
    
    # 生成测试 session_id
    test_session_id = generate_snowflake_id()
    print(f"\n测试 session_id: {test_session_id}")
    
    # 1. 模拟创建聊天消息
    print("\n[步骤1] 模拟创建聊天消息...")
    for i in range(5):
        mongo.append_chat_message(
            thread_id=test_session_id,
            assistant_id="agent",
            role="user" if i % 2 == 0 else "assistant",
            content=f"测试消息 {i+1}",
        )
    print(f"  ✓ 已创建 5 条聊天消息")
    
    # 2. 模拟创建 checkpoint
    print("\n[步骤2] 模拟创建 checkpoint...")
    db_path = get_db_path()
    async with aiosqlite.connect(str(db_path)) as db:
        for i in range(30):
            checkpoint_id = f"test-ckpt-{test_session_id}-{i:03d}"
            await db.execute(
                """
                INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata)
                VALUES (?, '', ?, ?, ?)
                """,
                (test_session_id, checkpoint_id, b"test_checkpoint_data", b"test_metadata"),
            )
            await db.execute(
                """
                INSERT INTO writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, value)
                VALUES (?, '', ?, 'task-1', ?, 'channel-1', ?)
                """,
                (test_session_id, checkpoint_id, i, b"test_write_data"),
            )
        await db.commit()
    print(f"  ✓ 已创建 30 个 checkpoint 和 writes")
    
    # 3. 查询会话列表
    print("\n[步骤3] 查询会话列表...")
    sessions = mongo.list_chat_sessions(assistant_id="agent", limit=50)
    test_session = next((s for s in sessions if s["session_id"] == test_session_id), None)
    if test_session:
        print(f"  ✓ 找到测试会话:")
        print(f"    - session_id: {test_session['session_id']}")
        print(f"    - title: {test_session['title']}")
        print(f"    - message_count: {test_session['message_count']}")
    else:
        print(f"  ✗ 未找到测试会话")
    
    # 4. 查询会话消息
    print("\n[步骤4] 查询会话消息...")
    messages = mongo.get_chat_history(thread_id=test_session_id, limit=200)
    print(f"  ✓ 查询到 {len(messages)} 条消息")
    for msg in messages[:3]:
        print(f"    - {msg['role']}: {msg['content'][:20]}...")
    
    # 5. 测试 checkpoint 限量清理
    print("\n[步骤5] 测试 checkpoint 限量清理 (保留最近 10 条)...")
    checkpoint_service_test = CheckpointService(keep_last=10)
    result = await checkpoint_service_test.cleanup_keep_last(session_id=test_session_id)
    print(f"  ✓ 删除了 {result.deleted_checkpoints} 个 checkpoint")
    print(f"  ✓ 删除了 {result.deleted_writes} 个 writes")
    
    # 验证剩余数量
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?",
            (test_session_id,)
        )
        row = await cursor.fetchone()
        remaining_checkpoints = row[0] if row else 0
        print(f"  ✓ 剩余 checkpoint 数量: {remaining_checkpoints}")
        
        if remaining_checkpoints == 10:
            print(f"  ✅ checkpoint 限量清理成功!")
        else:
            print(f"  ⚠️  预期剩余 10 个,实际剩余 {remaining_checkpoints} 个")
    
    # 6. 测试删除会话
    print("\n[步骤6] 测试删除会话...")
    
    # 删除前统计
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?",
            (test_session_id,)
        )
        row = await cursor.fetchone()
        before_checkpoints = row[0] if row else 0
        
        cursor = await db.execute(
            "SELECT COUNT(*) FROM writes WHERE thread_id = ?",
            (test_session_id,)
        )
        row = await cursor.fetchone()
        before_writes = row[0] if row else 0
    
    before_messages = len(mongo.get_chat_history(thread_id=test_session_id, limit=500))
    
    print(f"  删除前统计:")
    print(f"    - checkpoint: {before_checkpoints} 个")
    print(f"    - writes: {before_writes} 个")
    print(f"    - messages: {before_messages} 条")
    
    # 执行删除
    mongo_deleted = mongo.delete_chat_session(session_id=test_session_id, assistant_id="agent")
    ck_deleted = await checkpoint_service.delete_session(session_id=test_session_id)
    
    print(f"\n  删除结果:")
    print(f"    - Mongo messages: {mongo_deleted['messages']} 条")
    print(f"    - Mongo memories: {mongo_deleted['memories']} 条")
    print(f"    - Mongo sessions: {mongo_deleted['sessions']} 条")
    print(f"    - Checkpoints: {ck_deleted.deleted_checkpoints} 个")
    print(f"    - Writes: {ck_deleted.deleted_writes} 个")
    
    # 删除后验证
    async with aiosqlite.connect(str(db_path)) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?",
            (test_session_id,)
        )
        row = await cursor.fetchone()
        after_checkpoints = row[0] if row else 0
        
        cursor = await db.execute(
            "SELECT COUNT(*) FROM writes WHERE thread_id = ?",
            (test_session_id,)
        )
        row = await cursor.fetchone()
        after_writes = row[0] if row else 0
    
    after_messages = len(mongo.get_chat_history(thread_id=test_session_id, limit=500))
    
    print(f"\n  删除后验证:")
    print(f"    - checkpoint: {after_checkpoints} 个")
    print(f"    - writes: {after_writes} 个")
    print(f"    - messages: {after_messages} 条")
    
    # 验证结果
    if after_checkpoints == 0 and after_writes == 0 and after_messages == 0:
        print(f"\n  ✅ 删除会话测试成功! 所有数据已清空")
    else:
        print(f"\n  ⚠️  删除不完整:")
        if after_checkpoints > 0:
            print(f"    - 仍有 {after_checkpoints} 个 checkpoint 残留")
        if after_writes > 0:
            print(f"    - 仍有 {after_writes} 个 writes 残留")
        if after_messages > 0:
            print(f"    - 仍有 {after_messages} 条消息残留")
    
    print("\n" + "="*60)
    print("测试完成")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(test_session_apis())
