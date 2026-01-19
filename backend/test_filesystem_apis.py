"""
测试 filesystem 写入接口
验证写入、查询、级联删除功能
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.mongo_manager import get_mongo_manager
from backend.utils.snowflake import generate_snowflake_id


def test_filesystem_write_apis():
    """测试 filesystem 写入接口完整流程"""
    print("\n" + "="*60)
    print("Filesystem 写入接口测试")
    print("="*60)
    
    mongo = get_mongo_manager()
    
    test_session_id = generate_snowflake_id()
    test_write_id = generate_snowflake_id()
    
    print(f"\n测试 session_id: {test_session_id}")
    print(f"测试 write_id: {test_write_id}")
    
    # 1. 创建写入记录
    print("\n[步骤1] 创建写入记录...")
    mongo.create_filesystem_write(
        write_id=test_write_id,
        session_id=test_session_id,
        file_path="/workspace/output/test_document.md",
        content="# 测试文档\n\n这是测试内容。",
        metadata={
            "title": "测试文档",
            "type": "markdown",
            "description": "用于测试的文档"
        }
    )
    print(f"  ✓ 写入记录已创建")
    
    # 2. 查询单条记录
    print("\n[步骤2] 查询单条写入记录...")
    write = mongo.get_filesystem_write(write_id=test_write_id, session_id=test_session_id)
    if write:
        print(f"  ✓ 查询成功:")
        print(f"    - write_id: {write['write_id']}")
        print(f"    - file_path: {write['file_path']}")
        print(f"    - title: {write['metadata'].get('title')}")
        print(f"    - content_length: {len(write['content'])} 字符")
    else:
        print(f"  ✗ 查询失败")
    
    # 3. 查询会话的所有写入记录
    print("\n[步骤3] 查询会话的所有写入记录...")
    writes = mongo.list_filesystem_writes(session_id=test_session_id, limit=100)
    print(f"  ✓ 查询到 {len(writes)} 条写入记录")
    for w in writes:
        print(f"    - {w['title']} ({w['type']}, {w['size']} 字节)")
    
    # 4. 测试级联删除
    print("\n[步骤4] 测试删除会话时级联删除写入记录...")
    
    before_count = len(mongo.list_filesystem_writes(session_id=test_session_id, limit=100))
    print(f"  删除前: {before_count} 条写入记录")
    
    deleted = mongo.delete_chat_session(session_id=test_session_id, assistant_id="agent")
    print(f"  删除结果:")
    print(f"    - filesystem_writes: {deleted['filesystem_writes']} 条")
    
    after_count = len(mongo.list_filesystem_writes(session_id=test_session_id, limit=100))
    print(f"  删除后: {after_count} 条写入记录")
    
    if after_count == 0:
        print(f"\n  ✅ 级联删除测试成功!")
    else:
        print(f"\n  ⚠️  仍有 {after_count} 条记录残留")
    
    print("\n" + "="*60)
    print("测试完成")
    print("="*60)


if __name__ == "__main__":
    test_filesystem_write_apis()
