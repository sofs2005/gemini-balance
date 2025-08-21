"""
有效密钥池核心管理类
实现智能密钥池管理，包括TTL机制、异步验证补充、紧急恢复等功能
"""
import asyncio
import random
from collections import deque
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import pytz
import time

from app.config.config import settings
from app.log.logger import get_key_manager_logger
from app.service.key.valid_key_models import ValidKeyWithTTL
from app.domain.gemini_models import GeminiRequest, GeminiContent
from app.handler.error_processor import ErrorProcessor
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
    
    def __init__(self, pool_size: int, ttl_hours: int, key_manager, error_processor: ErrorProcessor):
        """
        初始化有效密钥池
        
        Args:
            pool_size: 密钥池大小
            ttl_hours: 密钥TTL时间（小时）
            key_manager: 密钥管理器实例
            error_processor: 错误处理器实例
        """
        self.pool_size = pool_size
        self.ttl_hours = ttl_hours
        self.key_manager = key_manager
        self.error_processor = error_processor
        self.valid_keys: deque[ValidKeyWithTTL] = deque(maxlen=pool_size)
        self._pool_keys_set: set[str] = set()
        self._verifying_keys: set[str] = set()
        concurrent_verifications = getattr(settings, 'CONCURRENT_VERIFICATIONS', 1)
        self.verification_semaphore = asyncio.Semaphore(concurrent_verifications)
        logger.info(f"Verification semaphore initialized with {concurrent_verifications} concurrent tasks.")
        self.emergency_lock = asyncio.Lock()     # 紧急补充锁
        self.get_key_lock = asyncio.Lock()       # 获取密钥锁，防止并发竞态条件
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
            "verification_failures": 0,
            "usage_exhausted_keys_removed": 0,  # 新增：因使用次数耗尽而移除的密钥数
            "pro_model_requests": 0,  # 新增：Pro模型请求数
            "non_pro_model_requests": 0,  # 新增：非Pro模型请求数
            "keys_checked_for_expiration": 0  # 新增：检查过期的密钥总数
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

    def _is_pro_model(self, model_name: str) -> bool:
        """
        判断是否为Pro模型

        Args:
            model_name: 模型名称

        Returns:
            bool: 如果是Pro模型返回True，否则返回False
        """
        if not model_name:
            return False

        # 移除模型名称中的后缀
        clean_model = model_name
        if clean_model.endswith("-search"):
            clean_model = clean_model[:-7]
        if clean_model.endswith("-image"):
            clean_model = clean_model[:-6]
        if clean_model.endswith("-non-thinking"):
            clean_model = clean_model[:-13]

        # 检查是否在Pro模型列表中
        is_pro = any(pro_model in clean_model for pro_model in settings.PRO_MODELS)

        if is_pro:
            logger.debug(f"Model {model_name} identified as Pro model")

        return is_pro

    def _get_max_usage_for_model(self, model_name: str) -> int:
        """
        根据模型类型获取最大使用次数

        Args:
            model_name: 模型名称

        Returns:
            int: 最大使用次数
        """
        if self._is_pro_model(model_name):
            return getattr(settings, 'PRO_MODEL_MAX_USAGE', 5)
        else:
            return getattr(settings, 'NON_PRO_MODEL_MAX_USAGE', 20)
    
    async def get_valid_key(self, model_name: str = None, increment_usage: bool = True) -> str:
        """
        优化密钥获取逻辑，增加冷却状态检查和错误处理集成
        """
        self.performance_stats["total_get_key_calls"] += 1
        
        # 记录模型请求统计
        if model_name:
            if self._is_pro_model(model_name):
                self.stats["pro_model_requests"] += 1
            else:
                self.stats["non_pro_model_requests"] += 1

        # 清理过期密钥
        expired_count = self._remove_expired_keys()

        # 使用锁保护整个密钥获取过程
        async with self.get_key_lock:
            return await self._get_key_from_pool_with_checks(model_name, increment_usage)


    async def _get_key_from_pool_with_checks(self, model_name: str = None, increment_usage: bool = True) -> str:
        """
        内部方法：从池中获取密钥并进行检查
        """
        while self.valid_keys:
            key_obj = self.valid_keys.popleft()
            self._pool_keys_set.discard(key_obj.key)
            
            # 检查密钥状态
            if await self._is_key_usable(key_obj, model_name):
                # 密钥可用，进行使用次数检查
                max_usage = self._get_max_usage_for_model(model_name)
                usage_limit_reached = max_usage > 0 and key_obj.usage_count >= max_usage
                
                if not usage_limit_reached:
                    # 密钥可以使用
                    if increment_usage:
                        key_obj.increment_usage()
                    
                    # 放回池中
                    self.valid_keys.append(key_obj)
                    self._pool_keys_set.add(key_obj.key)
                    
                    # 记录命中
                    self._record_key_hit(key_obj, max_usage)
                    return key_obj.key
                else:
                    # 使用次数耗尽
                    self.stats["usage_exhausted_keys_removed"] += 1
                    self._trigger_refill_on_key_removal(model_name)
                    continue
            else:
                # 密钥不可用（过期或冷却中）
                if key_obj.is_expired():
                    self.stats["expired_keys_removed"] += 1
                self._trigger_refill_on_key_removal(model_name)
                continue
        
        # 池为空，进入紧急恢复模式
        return await self.emergency_refill(model_name)


    async def _is_key_usable(self, key_obj: ValidKeyWithTTL, model_name: str = None) -> bool:
        """
        检查密钥是否可用（未过期且未冷却）
        """
        if key_obj.is_expired():
            return False
        
        # 检查冷却状态
        is_in_cooldown = False
        key_statuses = self.key_manager.key_model_status.get(key_obj.key)
        if key_statuses:
            now = datetime.now(pytz.utc)
            for model, expiry_time in key_statuses.items():
                if now < expiry_time:
                    is_in_cooldown = True
                    logger.debug(f"Key {redact_key_for_logging(key_obj.key)} in cooldown for model {model}")
                    break
        
        return not is_in_cooldown


    def _record_key_hit(self, key_obj: ValidKeyWithTTL, max_usage: int):
        """
        记录密钥命中信息
        """
        self.stats["hit_count"] += 1
        self.performance_stats["last_hit_time"] = datetime.now()
        
        # 计算命中率和记录日志
        hit_rate = self.stats["hit_count"] / (self.stats["hit_count"] + self.stats["miss_count"]) if (self.stats["hit_count"] + self.stats["miss_count"]) > 0 else 0
        usage_limit_str = str(max_usage) if max_usage > 0 else "unlimited"
        
        logger.info(f"Pool hit: returned key {redact_key_for_logging(key_obj.key)}, "
                   f"usage: {key_obj.usage_count}/{usage_limit_str}, "
                   f"pool size: {len(self.valid_keys)}, hit rate: {hit_rate:.2%}")

    def _trigger_refill_on_key_removal(self, model_name: str = None) -> None:
        """
        当密钥被移出池子时触发补充逻辑
        """
        min_threshold = int(getattr(settings, 'POOL_MIN_THRESHOLD', 10))
        current_size = len(self.valid_keys)

        # 只要低于阈值，就触发紧急补充
        if current_size < min_threshold:
            logger.warning(f"Pool size {current_size} is below threshold {min_threshold}, triggering emergency refill.")
            asyncio.create_task(self.emergency_refill_async())
        elif current_size < self.pool_size:  # 未达到最大容量时继续补充
            # 降低触发频率，避免过度验证
            import random
            import time
            
            # 记录最后补充时间，避免短时间内频繁补充
            last_refill_time = getattr(self, '_last_refill_time', 0)
            current_time = time.time()
            min_refill_interval = 5  # 最小补充间隔5秒
            
            if current_time - last_refill_time < min_refill_interval:
                logger.debug(f"Skipping refill due to interval limit: {current_time - last_refill_time:.1f}s < {min_refill_interval}s")
                return
            
            # 循序式补充策略：每次只补充1个密钥
            if current_size < self.pool_size * 0.8:  # 低于80%容量时
                # 根据池大小动态调整补充概率
                if current_size < min_threshold * 1.5:  # 低于30个时
                    refill_chance = 0.4  # 40%概率补充
                elif current_size < min_threshold * 2:  # 低于40个时
                    refill_chance = 0.3  # 30%概率补充
                else:  # 40个以上时
                    refill_chance = 0.2  # 20%概率补充
                logger.debug(f"Pool size {current_size} below 80% capacity, refill chance: {refill_chance*100:.0f}%")
            else:
                # 接近满容量时，低概率补充
                refill_chance = 0.05  # 5%概率补充
                logger.debug(f"Pool size {current_size} near capacity, refill chance: {refill_chance*100:.0f}%")

            if random.random() < refill_chance:
                self._last_refill_time = current_time
                logger.info(f"Key removed from pool, current size {current_size}, triggering sequential async refill")
                asyncio.create_task(self.async_verify_and_add(model_name))
            else:
                logger.debug(f"Key removed from pool, current size {current_size}, skipping refill")
        else:
            logger.debug(f"Pool size {current_size} at capacity {self.pool_size}, no refill needed")

    async def async_verify_and_add(self, model_name: str = None) -> None:
        """
        异步验证随机密钥并添加到池中

        Args:
            model_name: 模型名称，用于确定使用次数限制
        """
        logger.info("Starting async_verify_and_add")

        # 使用信号量控制并发验证
        async with self.verification_semaphore:
            # 在获取信号量后，再次检查池是否已满
            if len(self.valid_keys) >= self.pool_size:
                logger.debug("Pool is full, skipping verification")
                return

            # 获取可能有效的密钥列表（排除已知失效的密钥）
            available_keys = []
            total_keys = len(self.key_manager.api_keys)
            for key in self.key_manager.api_keys:
                # 检查密钥是否被标记为失效
                if not await self.key_manager.is_key_valid(key):
                    continue

                # 检查密钥是否处于冷却状态
                is_in_cooldown = False
                key_statuses = self.key_manager.key_model_status.get(key)
                if key_statuses:
                    now = datetime.now(pytz.utc)
                    for model, expiry_time in key_statuses.items():
                        if now < expiry_time:
                            is_in_cooldown = True
                            break
                
                if not is_in_cooldown:
                    available_keys.append(key)

            logger.info(f"Key availability check: {len(available_keys)}/{total_keys} keys are valid")

            if not available_keys:
                logger.warning("No valid API keys available for verification")
                return

            # 选择密钥策略：优先选择未在池中的密钥
            pool_keys = self._pool_keys_set
            unused_keys = [key for key in available_keys if key not in pool_keys and key not in self._verifying_keys]

            if not unused_keys:
                logger.info("No available keys to verify (all are either in pool or currently being verified).")
                return

            selected_key = random.choice(unused_keys)
            logger.info(f"Selected key {redact_key_for_logging(selected_key)} for verification from {len(unused_keys)} available keys.")

            # 验证密钥
            verification_start = time.time()
            if await self._verify_key(selected_key):
                # 验证成功后，再次检查池大小（防止竞态条件）
                if len(self.valid_keys) >= self.pool_size:
                    logger.warning(f"Pool size limit reached ({self.pool_size}) after verification, skipping add for key {redact_key_for_logging(selected_key)}")
                    return

                # 添加到池中（使用默认的无限制，具体限制在获取时根据模型类型判断）
                verification_time = time.time() - verification_start
                self._update_avg_verification_time(verification_time)

                key_obj = ValidKeyWithTTL(selected_key, self.ttl_hours)
                self.valid_keys.append(key_obj)
                self._pool_keys_set.add(key_obj.key)
                self.stats["successful_verifications"] += 1

                # 记录详细的验证成功日志
                pool_utilization = len(self.valid_keys) / self.pool_size if self.pool_size > 0 else 0
                logger.info(f"Successfully verified and added key {redact_key_for_logging(selected_key)} to pool, "
                           f"verification time: {verification_time:.3f}s, pool utilization: {pool_utilization:.1%}")
            else:
                self.stats["verification_failures"] += 1
                logger.debug(f"Key verification failed for {redact_key_for_logging(selected_key)}")
    
    async def emergency_refill(self, model_name: str = None) -> str:
        """
        紧急恢复模式：立即返回一个候选密钥，并在后台异步验证和补充池。
        """
        # self.stats["miss_count"] += 1 # Counting is now handled by the caller when a request ultimately fails
        # self.performance_stats["last_miss_time"] = datetime.now()
        logger.warning("Starting non-blocking emergency refill process")

        # 尝试立即获取一个候选密钥返回，避免阻塞请求
        # 使用fallback逻辑，但不触发池的验证（避免重复验证）
        candidate_key = await self.key_manager._original_get_next_working_key(model_name)
        logger.info(f"Immediately returning candidate key {redact_key_for_logging(candidate_key)} for the current request.")

        # 检查紧急补充锁，如果未锁定，则创建后台任务
        if not self.emergency_lock.locked():
            logger.info("Emergency lock is not locked, creating background refill task.")
            asyncio.create_task(self._background_emergency_refill())
        else:
            logger.info("Emergency refill task is already running in the background.")

        return candidate_key

    async def _background_emergency_refill(self):
        """
        在后台执行实际的密钥验证和池补充，不阻塞主流程。
        """
        if self.emergency_lock.locked():
            logger.info("Background emergency refill is already in progress. Skipping.")
            return

        async with self.emergency_lock:
            refill_start = time.time()
            logger.info("Background emergency refill task started.")

            try:
                # 获取可能有效的密钥列表
                available_keys = [
                    key for key in self.key_manager.api_keys
                    if await self.key_manager.is_key_valid(key) and not self._is_key_in_pool(key)
                ]

                if not available_keys:
                    logger.warning("No available keys for background emergency refill.")
                    return

                # 并发验证多个密钥
                refill_count = min(int(settings.EMERGENCY_REFILL_COUNT), len(available_keys))
                selected_keys = random.sample(available_keys, refill_count)
                logger.info(f"Background refill: selected {refill_count} keys for verification.")

                verification_tasks = [self._verify_key_for_emergency(key) for key in selected_keys]
                results = await asyncio.gather(*verification_tasks, return_exceptions=True)

                # 处理验证结果
                success_count = 0
                for result in results:
                    if isinstance(result, str):  # 验证成功
                        if len(self.valid_keys) < self.pool_size:
                            key_obj = ValidKeyWithTTL(result, self.ttl_hours)
                            self.valid_keys.append(key_obj)
                            self._pool_keys_set.add(key_obj.key)
                            success_count += 1
                            logger.info(f"Background refill: added key {redact_key_for_logging(result)} to pool")
                        else:
                            logger.warning("Pool size limit reached during background refill, stopping.")
                            break
                
                if success_count > 0:
                    self.stats["emergency_refill_count"] += 1
                
                refill_time = time.time() - refill_start
                logger.info(f"Background emergency refill finished in {refill_time:.3f}s. "
                           f"Successfully added {success_count}/{len(selected_keys)} keys. "
                           f"Pool size is now {len(self.valid_keys)}.")

            except Exception as e:
                logger.error(f"An error occurred during background emergency refill: {e}", exc_info=True)

    async def emergency_refill_async(self) -> None:
        """
        异步紧急补充，不返回密钥，只补充池子
        """
        # 使用信号量控制并发验证
        async with self.verification_semaphore:
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
                        self._pool_keys_set.add(key_obj.key)
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
                    # This is slow, but keys_to_validate is small.
                    self.valid_keys.remove(key_obj)
                    self._pool_keys_set.discard(key_obj.key)
                    removed_count += 1
                    logger.debug(f"Removed expired key {redact_key_for_logging(key_obj.key)}")
                    continue

                # 池内密钥本来就已经验证过有效，只需要检查TTL过期
                # 不需要重复验证，避免消耗使用次数
                continue

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
        
        if key in self._verifying_keys:
            logger.warning(f"Key {redact_key_for_logging(key)} is already being verified. Skipping duplicate verification.")
            return False
            
        self._verifying_keys.add(key)
        try:
            if not self.chat_service:
                logger.warning("Chat service not available for key verification")
                self._verifying_keys.discard(key)
                return False
            
            # 使用新的、无副作用的验证方法
            verification_result = await self.chat_service._verify_key_with_api(key)
            
            if verification_result is None:
                # 验证成功
                await self.key_manager.reset_key_failure_count(key)
                logger.debug(f"Key verification successful for {redact_key_for_logging(key)}")
                return True
            else:
                # 验证失败，处理异常
                logger.debug(f"Key verification failed for {redact_key_for_logging(key)}: {str(verification_result)}")
                await self.error_processor.process_error(key, verification_result, settings.TEST_MODEL)
                return False
        except asyncio.CancelledError:
            # 任务被取消，不记录为验证失败
            logger.debug(f"Key verification cancelled for {redact_key_for_logging(key)}")
            raise  # 重新抛出CancelledError
        finally:
            self._verifying_keys.discard(key)
    
    async def _verify_key_for_emergency(self, key: str) -> Optional[str]:
        """
        紧急恢复模式的密钥验证（简化版，避免递归调用）

        Args:
            key: 要验证的密钥

        Returns:
            Optional[str]: 验证成功返回密钥，失败返回None
        """
        self.stats["total_verifications"] += 1
        try:
            if not self.chat_service:
                logger.warning("Chat service not available for emergency key verification")
                return None

            # 紧急验证方法返回布尔值：True表示成功，False表示失败
            is_valid = await self.chat_service._verify_key_with_api(key)
            if is_valid:
                # 验证成功
                self.stats["successful_verifications"] += 1
                await self.key_manager.reset_key_failure_count(key)
                logger.debug(f"Emergency key verification successful for {redact_key_for_logging(key)}")
                return key
            else:
                # 验证失败
                self.stats["verification_failures"] += 1
                # 验证失败，返回None
                return None
        except asyncio.CancelledError:
            # 任务被取消
            logger.debug(f"Emergency key verification cancelled for {redact_key_for_logging(key)}")
            raise

    def _remove_expired_keys(self) -> int:
        """
        处理池中的过期密钥。
        对于过期的密钥，不再直接移除，而是触发一个后台任务对其进行重新验证。
        """
        expired_count = 0
        keys_to_keep = deque()
        keys_to_revalidate = []

        # 遍历当前池，分离出未过期的和已过期的
        while self.valid_keys:
            key_obj = self.valid_keys.popleft()
            self.stats["keys_checked_for_expiration"] += 1
            # The key is always removed from the set here.
            # If it's not expired, it will be added back to both deque and set.
            self._pool_keys_set.discard(key_obj.key)
            if not key_obj.is_expired():
                keys_to_keep.append(key_obj)
            else:
                expired_count += 1
                keys_to_revalidate.append(key_obj.key)
        
        # 将未过期的密钥放回池中
        self.valid_keys = keys_to_keep
        # Re-add the keys that were kept to the set
        for key_obj in self.valid_keys:
            self._pool_keys_set.add(key_obj.key)

        # 为所有过期的密钥创建后台重新验证任务
        if keys_to_revalidate:
            logger.info(f"Found {len(keys_to_revalidate)} expired keys. Triggering async re-validation for them.")
            for key in keys_to_revalidate:
                asyncio.create_task(self._revalidate_and_readd_key(key))
        
        if expired_count > 0:
            self.stats["expired_keys_removed"] += expired_count
            logger.info(f"Processed {expired_count} expired keys. They will be re-validated in the background.")

        return expired_count

    async def _revalidate_and_readd_key(self, key: str):
        """
        在后台异步地重新验证一个密钥，如果成功，则刷新其TTL并将其重新添加到池中。
        """
        # 使用信号量控制并发验证
        async with self.verification_semaphore:
            # 在开始验证前，再次检查池是否已满或密钥是否已通过其他方式被加回
            if len(self.valid_keys) >= self.pool_size:
                logger.debug(f"Pool is full, skipping re-validation for expired key: {redact_key_for_logging(key)}")
                return
            if self._is_key_in_pool(key):
                logger.debug(f"Key {redact_key_for_logging(key)} is already back in the pool, skipping re-validation.")
                return

            logger.info(f"Background re-validating expired key: {redact_key_for_logging(key)}")
            if await self._verify_key(key):
                # 如果验证成功，创建一个新的带有刷新后TTL的密钥对象
                new_key_obj = ValidKeyWithTTL(key, self.ttl_hours)
                # 再次检查池是否已满（以防在验证过程中池被填满）
                if len(self.valid_keys) < self.pool_size:
                    self.valid_keys.append(new_key_obj)
                    self._pool_keys_set.add(new_key_obj.key)
                    logger.info(f"Successfully re-validated and re-added key {redact_key_for_logging(key)} to the pool. "
                               f"New pool size: {len(self.valid_keys)}")
                else:
                    logger.warning(f"Pool became full during re-validation. Discarding re-validated key: {redact_key_for_logging(key)}")
            else:
                # _verify_key 内部已经处理了失败标记，这里只需记录日志
                logger.info(f"Re-validation failed for key {redact_key_for_logging(key)}. It will not be re-added.")

    def _is_key_in_pool(self, key: str) -> bool:
        """
        检查密钥是否已在池中

        Args:
            key: 要检查的密钥

        Returns:
            bool: 密钥是否在池中
        """
        return key in self._pool_keys_set

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
            # 温和的循序补充策略：根据池大小决定补充数量
            if current_size < min_threshold:
                # 低于阈值时，补充2-3个密钥（降低补充数量）
                refill_target = min(3, self.pool_size - current_size)
            elif current_size < self.pool_size * 0.7:
                # 低于70%容量时，补充1-2个密钥
                refill_target = min(2, self.pool_size - current_size)
            else:
                # 接近满容量时，只补充1个密钥
                refill_target = min(1, self.pool_size - current_size)

            logger.info(f"Pool maintenance: current {current_size}/{self.pool_size}, will add {refill_target} keys (sequential)")

            refill_attempt = 0
            max_refill_attempts = refill_target * 2  # 降低重试次数

            while refilled_count < refill_target and refill_attempt < max_refill_attempts:
                try:
                    before_size = len(self.valid_keys)
                    await self.async_verify_and_add()
                    after_size = len(self.valid_keys)

                    if after_size > before_size:
                        refilled_count += 1
                        logger.info(f"Maintenance refilled {refilled_count}/{refill_target} keys, pool size: {after_size}/{self.pool_size}")

                    refill_attempt += 1
                    # 增加延迟，避免过于频繁的验证
                    await asyncio.sleep(1.0)  # 增加到1秒延迟

                except asyncio.CancelledError:
                    logger.info(f"Pool maintenance cancelled during refill attempt {refill_attempt}")
                    break  # 停止补充但继续完成维护
                except Exception as e:
                    logger.warning(f"Failed to refill key attempt {refill_attempt}: {e}")
                    refill_attempt += 1
        else:
            logger.info(f"Pool size ({current_size}) at capacity ({self.pool_size}), no refill needed")

        # 减少池内密钥验证频率，只在维护间隔较长时执行
        # 只在池中密钥数量较少时才进行验证，避免过度验证
        if current_size > 0 and current_size < min_threshold:
            await self._validate_pool_keys()
        elif self.stats["maintenance_count"] % 5 == 0:  # 每5次维护才验证一次
            await self._validate_pool_keys()
        else:
            logger.debug("Skipping pool validation to avoid excessive verification")

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
        total_checked = self.stats.get("keys_checked_for_expiration", 0)
        if total_checked > 0:
            ttl_expiry_rate = self.stats["expired_keys_removed"] / total_checked

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
        self._pool_keys_set.clear()
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

        # 使用并发验证提高预加载效率
        batch_size = min(10, target_size)  # 每批验证10个
        total_loaded = 0

        while len(self.valid_keys) < target_size and total_loaded < target_size * 2:
            # 使用信号量控制每个批次的并发验证
            async with self.verification_semaphore:
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
                        self._pool_keys_set.add(key_obj.key)
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
        logger.info(f"Pro Model Requests: {stats['stats']['pro_model_requests']}, "
                   f"Non-Pro Model Requests: {stats['stats']['non_pro_model_requests']}")
        logger.info(f"Usage Exhausted Keys Removed: {stats['stats']['usage_exhausted_keys_removed']}")
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
            "verification_failures": 0,
            "usage_exhausted_keys_removed": 0,  # 因使用次数耗尽而移除的密钥数
            "pro_model_requests": 0,  # Pro模型请求数
            "non_pro_model_requests": 0,  # 非Pro模型请求数
            "keys_checked_for_expiration": 0
        }

        self.performance_stats = {
            "last_hit_time": None,
            "last_miss_time": None,
            "last_maintenance_time": None,
            "total_get_key_calls": 0,
            "avg_verification_time": 0.0
        }

    def remove_key(self, key_to_remove: str) -> bool:
        """
        Removes a key from the pool and then triggers the probabilistic replenishment logic.
        This is the single, unified entry point for removing a key from the pool.
        """
        initial_size = len(self.valid_keys)
        
        # Create a new deque without the key to remove
        new_keys = deque(
            key_obj for key_obj in self.valid_keys if key_obj.key != key_to_remove
        )
        
        if len(new_keys) < initial_size:
            self.valid_keys = new_keys
            self._pool_keys_set.discard(key_to_remove)
            logger.info(f"Key {redact_key_for_logging(key_to_remove)} removed from pool. Current size: {len(self.valid_keys)}")
            
            # Now, trigger the internal replenishment logic
            self._trigger_refill_on_key_removal()
            return True
            
        return False

    def record_miss(self):
        """
        Records a pool miss event. This should be called when the entire request
        (including all retries) fails to find a working key.
        """
        self.stats["miss_count"] += 1
        self.performance_stats["last_miss_time"] = datetime.now()
        logger.warning("Pool miss recorded. A request failed after all retries.")

