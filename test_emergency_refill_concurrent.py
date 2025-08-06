#!/usr/bin/env python3
"""
并发紧急补充计数器测试脚本
用于验证emergency_refill_count计数器在高并发下的准确性
"""
import asyncio
import random
from unittest.mock import AsyncMock, MagicMock, patch
import time
import sys
import os

# 添加项目路径到sys.path
sys.path.insert(0, 'D:\\Programs\\gemini-balance')

from app.service.key.valid_key_pool import ValidKeyPool
from app.service.key.key_manager import KeyManager


class EmergencyRefillTest:
    def __init__(self):
        self.test_results = []
        
    async def setup_test_environment(self):
        """设置测试环境"""
        # 创建模拟的key_manager
        self.mock_key_manager = MagicMock()
        self.mock_key_manager.api_keys = [f"test_key_{i}" for i in range(20)]
        
        # 模拟is_key_valid方法
        async def mock_is_key_valid(key):
            # 80%的概率返回有效
            return random.random() < 0.8
        
        self.mock_key_manager.is_key_valid = mock_is_key_valid
        
        # 模拟get_next_working_key方法
        async def mock_get_next_working_key(model_name=None):
            # 随机返回一个有效密钥
            available_keys = [k for k in self.mock_key_manager.api_keys 
                            if random.random() < 0.8]  # 80%概率有效
            if available_keys:
                return random.choice(available_keys)
            return "fallback_key"
        
        self.mock_key_manager.get_next_working_key = mock_get_next_working_key
        
        # 模拟reset_key_failure_count方法
        self.mock_key_manager.reset_key_failure_count = AsyncMock()
        
        # 创建模拟的chat_service
        self.mock_chat_service = MagicMock()
        
        # 模拟generate_content方法
        async def mock_generate_content(model, request, key):
            # 模拟API调用延迟
            await asyncio.sleep(0.1)
            # 90%概率成功
            if random.random() < 0.9:
                return {"response": "success"}
            else:
                raise Exception("API error")
        
        self.mock_chat_service.generate_content = mock_generate_content
        
        # 创建ValidKeyPool实例
        self.pool = ValidKeyPool(pool_size=15, ttl_hours=24, key_manager=self.mock_key_manager)
        self.pool.set_chat_service(self.mock_chat_service)
        
        # 清空池子确保测试从空池开始
        self.pool.clear_pool()
        
        print("✅ 测试环境设置完成")
        
    async def simulate_concurrent_emergency_requests(self, num_requests: int, delay: float = 0):
        """模拟并发紧急补充请求"""
        print(f"\n🚨 开始模拟 {num_requests} 个并发紧急补充请求...")
        
        # 清空池子，确保从空池开始
        self.pool.clear_pool()
        initial_count = self.pool.stats["emergency_refill_count"]
        print(f"📊 初始紧急补充计数: {initial_count}")
        
        # 创建并发任务
        tasks = []
        for i in range(num_requests):
            # 添加少量延迟模拟真实场景
            await asyncio.sleep(delay * i)
            task = asyncio.create_task(self.pool.emergency_refill(f"test_model_{i}"))
            tasks.append(task)
        
        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 等待后台任务完成
        await asyncio.sleep(2)
        
        final_count = self.pool.stats["emergency_refill_count"]
        pool_size = len(self.pool.valid_keys)
        
        print(f"📊 最终紧急补充计数: {final_count}")
        print(f"📊 池中密钥数量: {pool_size}")
        print(f"📊 成功的请求数: {len([r for r in results if not isinstance(r, Exception)])}")
        print(f"📊 失败的请求数: {len([r for r in results if isinstance(r, Exception)])}")
        
        # 分析结果
        expected_count = 1  # 理想情况下应该只触发一次后台补充
        actual_count = final_count - initial_count
        
        result = {
            "num_requests": num_requests,
            "initial_count": initial_count,
            "final_count": final_count,
            "actual_increments": actual_count,
            "expected_increments": expected_count,
            "pool_size": pool_size,
            "success_rate": len([r for r in results if not isinstance(r, Exception)]) / num_requests,
            "is_correct": actual_count == expected_count,
            "over_count": max(0, actual_count - expected_count)
        }
        
        self.test_results.append(result)
        
        return result
        
    async def test_concurrent_scenarios(self):
        """测试多种并发场景"""
        print("=" * 60)
        print("🧪 开始并发紧急补充计数器测试")
        print("=" * 60)
        
        # 测试场景1: 轻微并发 (5个请求)
        print("\n📋 测试场景1: 轻微并发 (5个请求)")
        result1 = await self.simulate_concurrent_emergency_requests(5, 0.01)
        
        # 测试场景2: 中度并发 (10个请求)
        print("\n📋 测试场景2: 中度并发 (10个请求)")
        result2 = await self.simulate_concurrent_emergency_requests(10, 0.005)
        
        # 测试场景3: 高度并发 (20个请求)
        print("\n📋 测试场景3: 高度并发 (20个请求)")
        result3 = await self.simulate_concurrent_emergency_requests(20, 0.001)
        
        # 测试场景4: 极高并发 (50个请求)
        print("\n📋 测试场景4: 极高并发 (50个请求)")
        result4 = await self.simulate_concurrent_emergency_requests(50, 0.0005)
        
        return [result1, result2, result3, result4]
        
    def analyze_results(self, results):
        """分析测试结果"""
        print("\n" + "=" * 60)
        print("📊 测试结果分析")
        print("=" * 60)
        
        total_tests = len(results)
        passed_tests = len([r for r in results if r["is_correct"]])
        
        print(f"🎯 总测试数: {total_tests}")
        print(f"✅ 通过测试数: {passed_tests}")
        print(f"❌ 失败测试数: {total_tests - passed_tests}")
        print(f"📈 通过率: {passed_tests/total_tests*100:.1f}%")
        
        print("\n📋 详细结果:")
        for i, result in enumerate(results, 1):
            status = "✅ 通过" if result["is_correct"] else "❌ 失败"
            print(f"\n  测试{i}: {status}")
            print(f"    请求数: {result['num_requests']}")
            print(f"    期望计数增加: {result['expected_increments']}")
            print(f"    实际计数增加: {result['actual_increments']}")
            print(f"    超出计数: {result['over_count']}")
            print(f"    最终池大小: {result['pool_size']}")
            print(f"    请求成功率: {result['success_rate']*100:.1f}%")
        
        # 计算总体评分
        if passed_tests == total_tests:
            score = 100
            print("\n🎉 完美！所有测试都通过了！")
        elif passed_tests >= total_tests * 0.8:
            score = 85 + (passed_tests / total_tests) * 10
            print(f"\n👍 良好！大部分测试通过了。")
        elif passed_tests >= total_tests * 0.5:
            score = 60 + (passed_tests / total_tests) * 20
            print(f"\n⚠️  一般。约一半测试通过。")
        else:
            score = (passed_tests / total_tests) * 60
            print(f"\n❌ 较差。大部分测试失败。")
        
        # 扣分项：如果存在超出计数的情况
        total_over_count = sum(r["over_count"] for r in results)
        if total_over_count > 0:
            score = max(0, score - total_over_count * 2)
            print(f"⚠️  因超出计数扣除 {total_over_count * 2} 分")
        
        print(f"\n🏆 最终质量评分: {score:.1f}/100")
        
        return score
        
    async def run_test(self):
        """运行完整测试"""
        try:
            await self.setup_test_environment()
            results = await self.test_concurrent_scenarios()
            score = self.analyze_results(results)
            return score
        except Exception as e:
            print(f"❌ 测试运行出错: {e}")
            import traceback
            traceback.print_exc()
            return 0


async def main():
    """主函数"""
    print("🧪 启动紧急补充计数器并发测试...")
    
    test = EmergencyRefillTest()
    score = await test.run_test()
    
    print(f"\n🏆 测试完成！最终评分: {score:.1f}/100")
    
    return score


if __name__ == "__main__":
    score = asyncio.run(main())
    exit(0 if score >= 90 else 1)