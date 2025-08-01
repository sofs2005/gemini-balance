"""
有效密钥池核心管理类
实现智能密钥池管理，包括TTL机制、异步验证补充、紧急恢复等功能
"""
import asyncio
import random
from collections import deque
from typing import Optional, List, Dict, Any
from datetime import datetime
import time

from app.config.config import settings
from app.log.logger import get_key_manager_logger
from app.service.key.valid_key_models import ValidKeyWithTTL
from app.domain.gemini_models import GeminiRequest, GeminiContent
from app.handler.error_processor import handle_api_error_and_get_next_key
from app.utils.helpers import redact_key_for_logging

logger = get_key_manager_logger()


class ValidKeyPool:
    """
    有效密钥池核心管理类
    
    提供智能密钥池管理功能，包括：
    - TTL机制确保密钥新鲜度
    - 异步验证和补充机制
    - 紧急恢复和快速填充
    - 统计监控和日志记录
    """
    
    def __init__(self, pool_size: int, ttl_hours: int, key_manager):
        """
        初始化有效密钥池
        
        Args:
            pool_size: 密钥池大小
            ttl_hours: 密钥TTL时间（小时）
            key_manager: 密钥管理器实例
        """
        self.pool_size = pool_size
        self.ttl_hours = ttl_hours
        self.key_manager = key_manager
        self.valid_keys: deque[ValidKeyWithTTL] = deque(maxlen=pool_size)
        self.verification_lock = asyncio.Lock()  # 常规验证锁
        self.emergency_lock = asyncio.Lock()     # 紧急补充锁
        self.chat_service = None
        
        # 统计信息
        self.stats = {
            "hit_count": 0,
            "miss_count": 0,
            "emergency_refill_count": 0,
            "expired_keys_removed": 0,
            "total_verifications": 0,
            "successful_verifications": 0,
            "maintenance_count": 0,
            "preload_count": 0,
            "fallback_count": 0,
            "verification_failures": 0
        }

        # 性能监控
        self.performance_stats = {
            "last_hit_time": None,
            "last_miss_time": None,
            "last_maintenance_time": None,
            "total_get_key_calls": 0,
            "avg_verification_time": 0.0
        }
        
        logger.info(f"ValidKeyPool initialized with pool_size={pool_size}, ttl_hours={ttl_hours}")
    
    def set_chat_service(self, chat_service):
        """设置聊天服务实例"""
        self.chat_service = chat_service
        logger.debug("Chat service set for ValidKeyPool")
    
    async def get_valid_key(self, model_name: str = None) -> str:
        """
        获取有效密钥，同时触发异步补充

        Args:
            model_name: 模型名称（可选）

        Returns:
            str: 有效的API密钥
        """
        start_time = time.time()
        self.performance_stats["total_get_key_calls"] += 1

        # 清理过期密钥
        expired_count = self._remove_expired_keys()

        # 尝试从池中获取有效密钥
        while self.valid_keys:
            key_obj = self.valid_keys.popleft()

            if not key_obj.is_expired():
                self.stats["hit_count"] += 1
                self.performance_stats["last_hit_time"] = datetime.now()

                # 记录详细的命中日志
                hit_rate = self.stats["hit_count"] / (self.stats["hit_count"] + self.stats["miss_count"]) if (self.stats["hit_count"] + self.stats["miss_count"]) > 0 else 0
                logger.info(f"Pool hit: returned key {redact_key_for_logging(key_obj.key)}, "
                           f"pool size: {len(self.valid_keys)}, hit rate: {hit_rate:.2%}")

                # 检查是否需要紧急补充
                min_threshold = int(getattr(settings, 'POOL_MIN_THRESHOLD', 10))
                current_size = len(self.valid_keys)

                if current_size < min_threshold // 2:  # 低于阈值的一半时触发紧急补充
                    logger.warning(f"Pool size {current_size} critically low (< {min_threshold//2}), triggering emergency refill")
                    asyncio.create_task(self.emergency_refill_async())
                elif current_size < self.pool_size:  # 未达到最大容量时继续补充
                    # 根据当前池大小决定补充策略
                    if current_size < min_threshold:
                        # 低于阈值时，每次补充2个以加速增长
                        logger.info(f"Pool size {current_size} below threshold {min_threshold}, triggering 2x async refill")
                        asyncio.create_task(self.async_verify_and_add())
                        asyncio.create_task(self.async_verify_and_add())
                    elif current_size < self.pool_size * 0.8:  # 低于80%容量时，偶尔补充
                        import random
                        # 根据池大小动态调整补充概率和数量
                        if current_size < min_threshold * 1.5:  # 低于15个时，100%概率补充2个
                            refill_chance = 1.0
                            refill_count = 2
                        elif current_size < min_threshold * 2:  # 低于20个时，100%概率补充1个
                            refill_chance = 1.0
                            refill_count = 1
                        elif current_size < min_threshold * 2.5:  # 低于25个时，80%概率补充1个
                            refill_chance = 0.8
                            refill_count = 1
                        else:  # 25-40个时，30%概率补充1个
                            refill_chance = 0.3
                            refill_count = 1

                        if random.random() < refill_chance:
                            logger.info(f"Pool size {current_size} below 80% capacity, triggering {refill_count}x async refill ({refill_chance*100:.0f}% chance)")
                            for _ in range(refill_count):
                                asyncio.create_task(self.async_verify_and_add())
                        else:
                            logger.debug(f"Pool size {current_size}, skipping refill ({(1-refill_chance)*100:.0f}% chance)")
                    else:
                        # 接近满容量时，低概率补充
                        import random
                        if random.random() < 0.1:  # 10%概率补充
                            logger.info(f"Pool size {current_size} near capacity, triggering async refill (10% chance)")
                            asyncio.create_task(self.async_verify_and_add())
                        else:
                            logger.debug(f"Pool size {current_size}, skipping refill (90% chance)")
                else:
                    logger.debug(f"Pool size {current_size} at capacity {self.pool_size}, no refill needed")

                return key_obj.key
            else:
                self.stats["expired_keys_removed"] += 1
                logger.debug(f"Removed expired key {redact_key_for_logging(key_obj.key)}")

        # 池为空或严重不足，记录miss并进入紧急恢复模式
        self.stats["miss_count"] += 1
        self.performance_stats["last_miss_time"] = datetime.now()

        miss_rate = self.stats["miss_count"] / (self.stats["hit_count"] + self.stats["miss_count"]) if (self.stats["hit_count"] + self.stats["miss_count"]) > 0 else 0
        logger.warning(f"ValidKeyPool miss: pool size {len(self.valid_keys)}, entering emergency refill mode, "
                      f"miss rate: {miss_rate:.2%}, expired removed: {expired_count}")

        return await self.emergency_refill(model_name)
    
    async def async_verify_and_add(self) -> None:
        """
        异步验证随机密钥并添加到池中
        """
        logger.info("Starting async_verify_and_add")

        # 使用锁防止重复验证
        if self.verification_lock.locked():
            logger.info("Verification already in progress, skipping async_verify_and_add")
            return
        
        async with self.verification_lock:
            # 检查池是否已满
            if len(self.valid_keys) >= self.pool_size:
                logger.debug("Pool is full, skipping verification")
                return
            
            # 获取可能有效的密钥列表（排除已知失效的密钥）
            available_keys = []
            total_keys = len(self.key_manager.api_keys)
            for key in self.key_manager.api_keys:
                # 检查密钥是否被标记为失效
                if await self.key_manager.is_key_valid(key):
                    available_keys.append(key)

            logger.info(f"Key availability check: {len(available_keys)}/{total_keys} keys are valid")

            if not available_keys:
                logger.warning("No valid API keys available for verification")
                return

            # 从有效密钥中随机选择
            random_key = random.choice(available_keys)
            logger.info(f"Selected key {redact_key_for_logging(random_key)} from {len(available_keys)} available keys")
            
            # 检查密钥是否已在池中
            if self._is_key_in_pool(random_key):
                logger.info(f"Key {redact_key_for_logging(random_key)} already in pool, skipping")
                return
            
            # 验证密钥
            verification_start = time.time()
            if await self._verify_key(random_key):
                # 验证成功后，再次检查池大小（防止竞态条件）
                if len(self.valid_keys) >= self.pool_size:
                    logger.warning(f"Pool size limit reached ({self.pool_size}) after verification, skipping add for key {redact_key_for_logging(random_key)}")
                    return

                # 添加到池中
                verification_time = time.time() - verification_start
                self._update_avg_verification_time(verification_time)

                key_obj = ValidKeyWithTTL(random_key, self.ttl_hours)
                self.valid_keys.append(key_obj)
                self.stats["successful_verifications"] += 1

                # 记录详细的验证成功日志
                pool_utilization = len(self.valid_keys) / self.pool_size if self.pool_size > 0 else 0
                logger.info(f"Successfully verified and added key {redact_key_for_logging(random_key)} to pool, "
                           f"verification time: {verification_time:.3f}s, pool utilization: {pool_utilization:.1%}")
            else:
                self.stats["verification_failures"] += 1
                logger.debug(f"Key verification failed for {redact_key_for_logging(random_key)}")
    
    async def emergency_refill(self, model_name: str = None) -> str:
        """
        紧急恢复模式：并发验证多个密钥快速填充池

        Args:
            model_name: 模型名称（可选）

        Returns:
            str: 第一个验证成功的密钥
        """
        refill_start = time.time()
        self.stats["emergency_refill_count"] += 1
        logger.warning("Starting emergency refill process")

        # 使用独立的紧急补充锁，防止多个紧急补充并发
        async with self.emergency_lock:
            # 获取可能有效的密钥列表
            available_keys = []
            for key in self.key_manager.api_keys:
                if await self.key_manager.is_key_valid(key):
                    available_keys.append(key)

            if not available_keys:
                logger.error("No valid API keys available for emergency refill")
                # Fallback到原有逻辑
                return await self.key_manager.get_next_working_key(model_name)

            # 并发验证多个密钥（从有效密钥中选择）
            refill_count = min(int(settings.EMERGENCY_REFILL_COUNT), len(available_keys))
            selected_keys = random.sample(available_keys, refill_count)
            logger.info(f"Emergency refill: selected {refill_count} keys from {len(available_keys)} available keys")

            # 创建验证任务
            verification_tasks = [
                self._verify_key_for_emergency(key) for key in selected_keys
            ]

            # 等待验证结果
            results = await asyncio.gather(*verification_tasks, return_exceptions=True)

            # 处理验证结果
            first_valid_key = None
            for i, result in enumerate(results):
                if isinstance(result, str):  # 验证成功返回密钥
                    # 检查池大小限制
                    if len(self.valid_keys) >= self.pool_size:
                        logger.warning(f"Pool size limit reached ({self.pool_size}), skipping additional keys in emergency refill")
                        if first_valid_key is None:
                            first_valid_key = result  # 至少记录一个有效密钥用于返回
                        break

                    key_obj = ValidKeyWithTTL(result, self.ttl_hours)
                    self.valid_keys.append(key_obj)

                    if first_valid_key is None:
                        first_valid_key = result

                    logger.info(f"Emergency refill: added key {redact_key_for_logging(result)} to pool")

            if first_valid_key:
                refill_time = time.time() - refill_start
                success_count = sum(1 for result in results if isinstance(result, str))
                logger.info(f"Emergency refill successful in {refill_time:.3f}s, "
                           f"verified {success_count}/{len(results)} keys, "
                           f"returning {redact_key_for_logging(first_valid_key)}")
                return first_valid_key
            else:
                self.stats["fallback_count"] += 1
                logger.error(f"Emergency refill failed, no valid keys found from {len(selected_keys)} attempts, "
                            f"falling back to original key manager")
                # Fallback到原有逻辑
                return await self.key_manager.get_next_working_key(model_name)

    async def emergency_refill_async(self) -> None:
        """
        异步紧急补充，不返回密钥，只补充池子
        """
        # 使用验证锁防止与其他验证任务冲突
        async with self.verification_lock:
            try:
                min_threshold = int(getattr(settings, 'POOL_MIN_THRESHOLD', 10))
                current_size = len(self.valid_keys)
                needed = min_threshold - current_size

                if needed <= 0:
                    return

                logger.info(f"Starting emergency async refill: need {needed} keys to reach threshold {min_threshold}")

                # 并发验证多个密钥
                refill_count = min(int(settings.EMERGENCY_REFILL_COUNT), needed)

                # 获取可能有效的密钥列表
                available_keys = []
                for key in self.key_manager.api_keys:
                    if await self.key_manager.is_key_valid(key):
                        available_keys.append(key)

                if not available_keys:
                    logger.warning("No valid API keys available for emergency async refill")
                    return

                selected_keys = random.sample(available_keys, min(refill_count, len(available_keys)))
                logger.info(f"Emergency async refill: selected {len(selected_keys)} keys for verification")

                # 并发验证
                tasks = [self._verify_key_for_emergency(key) for key in selected_keys]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 处理结果
                success_count = 0
                for result in results:
                    if isinstance(result, str):  # 验证成功返回密钥
                        # 检查池大小限制
                        if len(self.valid_keys) >= self.pool_size:
                            logger.warning(f"Pool size limit reached ({self.pool_size}), skipping additional keys in emergency async refill")
                            break

                        key_obj = ValidKeyWithTTL(result, self.ttl_hours)
                        self.valid_keys.append(key_obj)
                        success_count += 1

                logger.info(f"Emergency async refill completed: added {success_count} keys, pool size now: {len(self.valid_keys)}")

            except Exception as e:
                logger.error(f"Emergency async refill failed: {e}")

    async def _validate_pool_keys(self) -> None:
        """
        验证池内现有密钥，移除失效的密钥
        """
        if not self.valid_keys:
            logger.debug("Pool is empty, skipping validation")
            return

        logger.info(f"Starting pool validation for {len(self.valid_keys)} keys")

        # 随机选择最多5个密钥进行验证（避免验证过多影响性能）
        keys_to_validate = list(self.valid_keys)
        if len(keys_to_validate) > 5:
            import random
            keys_to_validate = random.sample(keys_to_validate, 5)

        removed_count = 0
        for key_obj in keys_to_validate:
            try:
                # 检查密钥是否过期
                if key_obj.is_expired():
                    self.valid_keys.remove(key_obj)
                    removed_count += 1
                    logger.debug(f"Removed expired key {redact_key_for_logging(key_obj.key)}")
                    continue

                # 验证密钥是否仍然有效
                is_valid = await self._verify_key(key_obj.key)
                if not is_valid:
                    self.valid_keys.remove(key_obj)
                    removed_count += 1
                    logger.info(f"Removed invalid key {redact_key_for_logging(key_obj.key)} from pool")

            except Exception as e:
                logger.warning(f"Error validating key {redact_key_for_logging(key_obj.key)}: {e}")

        if removed_count > 0:
            logger.info(f"Pool validation completed: removed {removed_count} invalid keys, pool size: {len(self.valid_keys)}")
        else:
            logger.debug(f"Pool validation completed: all validated keys are valid, pool size: {len(self.valid_keys)}")

    async def _verify_key(self, key: str) -> bool:
        """
        验证单个密钥
        
        Args:
            key: 要验证的密钥
            
        Returns:
            bool: 验证是否成功
        """
        self.stats["total_verifications"] += 1
        
        try:
            if not self.chat_service:
                logger.warning("Chat service not available for key verification")
                return False
            
            # 构造测试请求
            gemini_request = GeminiRequest(
                contents=[
                    GeminiContent(
                        role="user",
                        parts=[{"text": "hi"}],
                    )
                ]
            )
            
            # 发送验证请求
            await self.chat_service.generate_content(
                settings.TEST_MODEL, gemini_request, key
            )
            
            # 验证成功，重置失败计数
            await self.key_manager.reset_key_failure_count(key)
            logger.debug(f"Key verification successful for {redact_key_for_logging(key)}")
            return True
            
        except asyncio.CancelledError:
            # 任务被取消，不记录为验证失败
            logger.debug(f"Key verification cancelled for {redact_key_for_logging(key)}")
            raise  # 重新抛出CancelledError
        except Exception as e:
            logger.debug(f"Key verification failed for {redact_key_for_logging(key)}: {str(e)}")

            # 调用通用错误处理器
            await handle_api_error_and_get_next_key(
                key_manager=self.key_manager,
                error=e,
                old_key=key,
                model_name=settings.TEST_MODEL,
                retries=self.key_manager.MAX_FAILURES
            )
            return False
    
    async def _verify_key_for_emergency(self, key: str) -> Optional[str]:
        """
        紧急恢复模式的密钥验证（简化版，避免递归调用）

        Args:
            key: 要验证的密钥

        Returns:
            Optional[str]: 验证成功返回密钥，失败返回None
        """
        try:
            if not self.chat_service:
                logger.warning("Chat service not available for emergency key verification")
                return None

            # 构造测试请求
            gemini_request = GeminiRequest(
                contents=[
                    GeminiContent(
                        role="user",
                        parts=[{"text": "hi"}],
                    )
                ]
            )

            # 发送验证请求（不调用错误处理器，避免递归）
            await self.chat_service.generate_content(
                settings.TEST_MODEL, gemini_request, key
            )

            # 验证成功，重置失败计数
            await self.key_manager.reset_key_failure_count(key)
            logger.debug(f"Emergency key verification successful for {redact_key_for_logging(key)}")
            return key

        except asyncio.CancelledError:
            # 任务被取消
            logger.debug(f"Emergency key verification cancelled for {redact_key_for_logging(key)}")
            raise
        except Exception as e:
            # 简化错误处理，不调用错误处理器，避免递归
            logger.debug(f"Emergency key verification failed for {redact_key_for_logging(key)}: {str(e)}")
            return None

    def _remove_expired_keys(self) -> int:
        """
        移除池中的过期密钥

        Returns:
            int: 移除的过期密钥数量
        """
        expired_count = 0
        valid_keys = deque()

        while self.valid_keys:
            key_obj = self.valid_keys.popleft()
            if not key_obj.is_expired():
                valid_keys.append(key_obj)
            else:
                expired_count += 1
                logger.debug(f"Removed expired key {redact_key_for_logging(key_obj.key)}")

        self.valid_keys = valid_keys

        if expired_count > 0:
            self.stats["expired_keys_removed"] += expired_count
            logger.info(f"Removed {expired_count} expired keys from pool")

        return expired_count

    def _is_key_in_pool(self, key: str) -> bool:
        """
        检查密钥是否已在池中

        Args:
            key: 要检查的密钥

        Returns:
            bool: 密钥是否在池中
        """
        return any(key_obj.key == key for key_obj in self.valid_keys)

    async def maintenance(self) -> None:
        """
        池维护操作：清理过期密钥，检查池大小，主动补充
        """
        maintenance_start = time.time()
        self.stats["maintenance_count"] += 1
        self.performance_stats["last_maintenance_time"] = datetime.now()

        logger.info("Starting pool maintenance")

        # 清理过期密钥
        expired_count = self._remove_expired_keys()

        # 检查池大小，如果不足则主动补充
        current_size = len(self.valid_keys)
        min_threshold = int(getattr(settings, 'POOL_MIN_THRESHOLD', 10))

        logger.info(f"Pool maintenance check: current_size={current_size}, min_threshold={min_threshold}, pool_size={self.pool_size}")

        refilled_count = 0
        # 检查是否需要补充（未达到最大容量）
        if current_size < self.pool_size:
            # 固定每次补充10个密钥
            refill_target = min(10, self.pool_size - current_size)
            logger.info(f"Pool maintenance: current {current_size}/{self.pool_size}, will add {refill_target} keys")

            refill_attempt = 0
            max_refill_attempts = refill_target * 2  # 允许一些失败重试

            while refilled_count < refill_target and refill_attempt < max_refill_attempts:
                try:
                    before_size = len(self.valid_keys)
                    await self.async_verify_and_add()
                    after_size = len(self.valid_keys)

                    if after_size > before_size:
                        refilled_count += 1
                        logger.info(f"Maintenance refilled {refilled_count}/{refill_target} keys, pool size: {after_size}/{self.pool_size}")

                    refill_attempt += 1
                    # 短暂延迟避免过于频繁的验证
                    await asyncio.sleep(0.1)

                except asyncio.CancelledError:
                    logger.info(f"Pool maintenance cancelled during refill attempt {refill_attempt}")
                    break  # 停止补充但继续完成维护
                except Exception as e:
                    logger.warning(f"Failed to refill key attempt {refill_attempt}: {e}")
                    refill_attempt += 1
        else:
            logger.info(f"Pool size ({current_size}) at capacity ({self.pool_size}), no refill needed")

        # 定期验证池内密钥，清理失效的密钥
        await self._validate_pool_keys()
                    # 继续尝试下一个密钥

        maintenance_time = time.time() - maintenance_start
        final_size = len(self.valid_keys)
        utilization = final_size / self.pool_size if self.pool_size > 0 else 0

        logger.info(f"Pool maintenance completed in {maintenance_time:.3f}s. "
                   f"Size: {final_size}/{self.pool_size} ({utilization:.1%}), "
                   f"Expired removed: {expired_count}, Refilled: {refilled_count}")

    def _update_avg_verification_time(self, verification_time: float) -> None:
        """
        更新平均验证时间

        Args:
            verification_time: 本次验证耗时
        """
        current_avg = self.performance_stats["avg_verification_time"]
        total_verifications = self.stats["total_verifications"]

        if total_verifications == 0:
            self.performance_stats["avg_verification_time"] = verification_time
        else:
            # 使用移动平均算法
            self.performance_stats["avg_verification_time"] = (
                (current_avg * total_verifications + verification_time) / (total_verifications + 1)
            )

    def get_pool_stats(self) -> Dict[str, Any]:
        """
        获取池统计信息

        Returns:
            Dict[str, Any]: 包含池状态和统计信息的字典
        """
        current_size = len(self.valid_keys)
        hit_rate = 0.0
        miss_rate = 0.0
        total_requests = self.stats["hit_count"] + self.stats["miss_count"]

        if total_requests > 0:
            hit_rate = self.stats["hit_count"] / total_requests
            miss_rate = self.stats["miss_count"] / total_requests

        verification_success_rate = 0.0
        verification_failure_rate = 0.0
        if self.stats["total_verifications"] > 0:
            verification_success_rate = self.stats["successful_verifications"] / self.stats["total_verifications"]
            verification_failure_rate = self.stats["verification_failures"] / self.stats["total_verifications"]

        # 计算平均密钥年龄和最老密钥年龄
        avg_age_seconds = 0
        max_age_seconds = 0
        min_age_seconds = 0
        if self.valid_keys:
            ages = [key_obj.age_seconds() for key_obj in self.valid_keys]
            avg_age_seconds = sum(ages) / len(ages)
            max_age_seconds = max(ages)
            min_age_seconds = min(ages)

        # 计算TTL过期率
        ttl_expiry_rate = 0.0
        if self.stats["expired_keys_removed"] > 0 and total_requests > 0:
            ttl_expiry_rate = self.stats["expired_keys_removed"] / (self.stats["expired_keys_removed"] + self.stats["hit_count"])

        return {
            # 基本池信息
            "pool_size": self.pool_size,
            "current_size": current_size,
            "utilization": current_size / self.pool_size if self.pool_size > 0 else 0,
            "ttl_hours": self.ttl_hours,

            # 性能指标
            "hit_rate": hit_rate,
            "miss_rate": miss_rate,
            "verification_success_rate": verification_success_rate,
            "verification_failure_rate": verification_failure_rate,
            "ttl_expiry_rate": ttl_expiry_rate,

            # 密钥年龄统计
            "avg_key_age_seconds": int(avg_age_seconds),
            "max_key_age_seconds": int(max_age_seconds),
            "min_key_age_seconds": int(min_age_seconds),

            # 详细统计
            "stats": self.stats.copy(),
            "performance_stats": self.performance_stats.copy(),

            # 时间戳
            "stats_timestamp": datetime.now().isoformat()
        }

    def clear_pool(self) -> int:
        """
        清空密钥池

        Returns:
            int: 清除的密钥数量
        """
        cleared_count = len(self.valid_keys)
        self.valid_keys.clear()
        logger.info(f"Cleared {cleared_count} keys from pool")
        return cleared_count

    async def preload_pool(self, target_size: Optional[int] = None) -> int:
        """
        预加载密钥池

        Args:
            target_size: 目标大小，默认为池大小的一半

        Returns:
            int: 成功加载的密钥数量
        """
        if target_size is None:
            target_size = max(1, self.pool_size // 2)

        logger.info(f"Starting pool preload, target size: {target_size}")

        # 使用验证锁防止与其他验证任务冲突
        async with self.verification_lock:
            # 使用并发验证提高预加载效率
            batch_size = min(10, target_size)  # 每批验证10个
            total_loaded = 0

            while len(self.valid_keys) < target_size and total_loaded < target_size * 2:
                # 获取可用密钥
                available_keys = []
                for key in self.key_manager.api_keys:
                    if await self.key_manager.is_key_valid(key) and not self._is_key_in_pool(key):
                        available_keys.append(key)

                if not available_keys:
                    logger.warning("No more valid keys available for preload")
                    break

                # 选择一批密钥进行并发验证
                batch_keys = random.sample(available_keys, min(batch_size, len(available_keys), target_size - len(self.valid_keys)))
                logger.info(f"Preload batch: verifying {len(batch_keys)} keys")

                # 并发验证
                tasks = [self._verify_key_for_emergency(key) for key in batch_keys]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 处理结果
                batch_loaded = 0
                for result in results:
                    if isinstance(result, str):  # 验证成功
                        # 检查是否达到目标大小
                        if len(self.valid_keys) >= target_size:
                            logger.info(f"Preload target size reached ({target_size}), stopping preload")
                            break

                        key_obj = ValidKeyWithTTL(result, self.ttl_hours)
                        self.valid_keys.append(key_obj)
                        batch_loaded += 1
                        total_loaded += 1

                logger.info(f"Preload batch completed: loaded {batch_loaded}/{len(batch_keys)} keys, pool size: {len(self.valid_keys)}")

                if batch_loaded == 0:  # 如果这批全部失败，停止预加载
                    logger.warning("Preload batch failed completely, stopping preload")
                    break

        logger.info(f"Pool preload completed. Loaded {len(self.valid_keys)} keys")
        return len(self.valid_keys)

    def log_performance_summary(self) -> None:
        """
        记录性能摘要日志
        """
        stats = self.get_pool_stats()

        logger.info("=== ValidKeyPool Performance Summary ===")
        logger.info(f"Pool Status: {stats['current_size']}/{stats['pool_size']} "
                   f"({stats['utilization']:.1%} utilization)")
        logger.info(f"Hit Rate: {stats['hit_rate']:.2%}, Miss Rate: {stats['miss_rate']:.2%}")
        logger.info(f"Verification Success Rate: {stats['verification_success_rate']:.2%}")
        logger.info(f"TTL Expiry Rate: {stats['ttl_expiry_rate']:.2%}")
        logger.info(f"Average Key Age: {stats['avg_key_age_seconds']}s "
                   f"(min: {stats['min_key_age_seconds']}s, max: {stats['max_key_age_seconds']}s)")
        logger.info(f"Total Requests: {stats['stats']['hit_count'] + stats['stats']['miss_count']}")
        logger.info(f"Emergency Refills: {stats['stats']['emergency_refill_count']}")
        logger.info(f"Maintenance Runs: {stats['stats']['maintenance_count']}")
        logger.info(f"Average Verification Time: {stats['performance_stats']['avg_verification_time']:.3f}s")
        logger.info("========================================")

    def reset_stats(self) -> None:
        """
        重置统计信息
        """
        logger.info("Resetting ValidKeyPool statistics")

        self.stats = {
            "hit_count": 0,
            "miss_count": 0,
            "emergency_refill_count": 0,
            "expired_keys_removed": 0,
            "total_verifications": 0,
            "successful_verifications": 0,
            "maintenance_count": 0,
            "preload_count": 0,
            "fallback_count": 0,
            "verification_failures": 0
        }

        self.performance_stats = {
            "last_hit_time": None,
            "last_miss_time": None,
            "last_maintenance_time": None,
            "total_get_key_calls": 0,
            "avg_verification_time": 0.0
        }
