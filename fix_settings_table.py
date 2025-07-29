#!/usr/bin/env python3
"""
修复 t_settings 表的 value 字段类型
确保能存储大量密钥数据
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.database.connection import database, engine
from app.log.logger import get_database_logger
from sqlalchemy import text

logger = get_database_logger()


async def check_table_structure():
    """检查当前表结构"""
    try:
        if not database.is_connected:
            await database.connect()
        
        # 检查 t_settings 表的结构
        query = text("DESCRIBE t_settings")
        result = await database.fetch_all(query)
        
        print("当前 t_settings 表结构:")
        for row in result:
            print(f"  {row['Field']}: {row['Type']} | Null: {row['Null']} | Key: {row['Key']}")
            
        return result
    except Exception as e:
        logger.error(f"检查表结构失败: {e}")
        return None


async def fix_value_column():
    """修复 value 字段类型为 LONGTEXT"""
    try:
        if not database.is_connected:
            await database.connect()
        
        print("正在修复 value 字段类型...")
        
        # 修改字段类型为 LONGTEXT
        alter_query = text("ALTER TABLE t_settings MODIFY COLUMN value LONGTEXT")
        await database.execute(alter_query)
        
        print("✅ value 字段已修改为 LONGTEXT 类型")
        
        # 验证修改结果
        await check_table_structure()
        
    except Exception as e:
        logger.error(f"修复字段类型失败: {e}")
        print(f"❌ 修复失败: {e}")


async def test_large_data():
    """测试存储大量数据"""
    try:
        # 创建一个包含大量密钥的测试数据
        test_keys = [f"AIzaSyTest{i:04d}{'x' * 35}" for i in range(1500)]  # 1500个测试密钥
        test_data = str(test_keys)
        
        print(f"测试数据大小: {len(test_data)} 字符")
        
        # 尝试插入或更新测试数据
        query = text("""
            INSERT INTO t_settings (key, value, description) 
            VALUES ('TEST_LARGE_DATA', :value, 'Test large data storage')
            ON DUPLICATE KEY UPDATE value = :value
        """)
        
        await database.execute(query, {"value": test_data})
        print("✅ 大数据存储测试成功")
        
        # 清理测试数据
        cleanup_query = text("DELETE FROM t_settings WHERE key = 'TEST_LARGE_DATA'")
        await database.execute(cleanup_query)
        print("✅ 测试数据已清理")
        
    except Exception as e:
        logger.error(f"大数据测试失败: {e}")
        print(f"❌ 大数据测试失败: {e}")


async def main():
    """主函数"""
    print("🔧 开始修复 t_settings 表...")
    
    try:
        # 1. 检查当前表结构
        structure = await check_table_structure()
        if not structure:
            print("❌ 无法检查表结构")
            return
        
        # 2. 检查 value 字段类型
        value_field = next((row for row in structure if row['Field'] == 'value'), None)
        if value_field:
            current_type = value_field['Type'].upper()
            print(f"当前 value 字段类型: {current_type}")
            
            if 'TEXT' not in current_type or current_type == 'TEXT':
                print("需要修复字段类型...")
                await fix_value_column()
            else:
                print("✅ 字段类型已经是 LONGTEXT 或更大类型")
        
        # 3. 测试大数据存储
        print("\n🧪 测试大数据存储...")
        await test_large_data()
        
        print("\n✅ 修复完成！现在可以存储大量密钥数据了。")
        
    except Exception as e:
        logger.error(f"修复过程出错: {e}")
        print(f"❌ 修复失败: {e}")
    
    finally:
        if database.is_connected:
            await database.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
