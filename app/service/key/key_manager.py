import asyncio
import random
from itertools import cycle
from typing import Dict, Union, Optional
from datetime import datetime, timedelta
import pytz

from app.config.config import settings
from app.log.logger import get_key_manager_logger
from app.utils.helpers import redact_key_for_logging

logger = get_key_manager_logger()


class KeyManager:
    def __init__(self, api_keys: list, vertex_api_keys: list):
        self.api_keys = api_keys
        self.vertex_api_keys = vertex_api_keys
        self.valid_api_keys = self.api_keys.copy()
        self.key_index = 0
        self.vertex_key_cycle = cycle(vertex_api_keys) # Vertex keys logic remains for now
        self.vertex_key_cycle_lock = asyncio.Lock()
        self.failure_count_lock = asyncio.Lock()
        self.vertex_failure_count_lock = asyncio.Lock()
        self.key_failure_counts: Dict[str, int] = {key: 0 for key in api_keys}
        self.vertex_key_failure_counts: Dict[str, int] = {
            key: 0 for key in vertex_api_keys
        }
        self.key_model_status: Dict[str, Dict[str, datetime]] = {}
        self.MAX_FAILURES = settings.MAX_FAILURES
        self.paid_key = settings.PAID_KEY
        settings.GEMINI_QUOTA_RESET_HOUR = int(settings.GEMINI_QUOTA_RESET_HOUR)

        # 初始化有效密钥池
        self.valid_key_pool = None
        if settings.VALID_KEY_POOL_ENABLED and api_keys:
            try:
                # 延迟导入避免循环依赖
                from app.service.key.valid_key_pool import ValidKeyPool

                # 确保配置值为整数类型（修复Pydantic警告）
                pool_size = int(settings.VALID_KEY_POOL_SIZE)
                ttl_hours = int(settings.KEY_TTL_HOURS)

                # 同时更新settings对象确保类型一致
                settings.VALID_KEY_POOL_SIZE = pool_size
                settings.KEY_TTL_HOURS = ttl_hours
                settings.POOL_MIN_THRESHOLD = int(settings.POOL_MIN_THRESHOLD)
                settings.EMERGENCY_REFILL_COUNT = int(settings.EMERGENCY_REFILL_COUNT)
                settings.POOL_MAINTENANCE_INTERVAL_MINUTES = int(settings.POOL_MAINTENANCE_INTERVAL_MINUTES)

                self.valid_key_pool = ValidKeyPool(
                    pool_size=pool_size,
                    ttl_hours=ttl_hours,
                    key_manager=self
                )
                logger.info(f"ValidKeyPool initialized successfully with pool_size={pool_size}, ttl_hours={ttl_hours}")
            except Exception as e:
                logger.error(f"Failed to initialize ValidKeyPool: {e}")
                self.valid_key_pool = None

    async def get_paid_key(self) -> str:
        return self.paid_key

    def set_chat_service(self, chat_service):
        """
        设置聊天服务实例，用于ValidKeyPool的密钥验证

        Args:
            chat_service: 聊天服务实例
        """
        if self.valid_key_pool:
            self.valid_key_pool.set_chat_service(chat_service)
            logger.debug("Chat service set for ValidKeyPool")

    def _ensure_chat_service_set(self):
        """
        确保ValidKeyPool的聊天服务已设置
        如果没有设置，则创建一个临时的聊天服务实例
        """
        if self.valid_key_pool and not self.valid_key_pool.chat_service:
            try:
                from app.config.config import settings
                from app.service.chat.gemini_chat_service import GeminiChatService

                # 创建临时聊天服务实例
                chat_service = GeminiChatService(settings.BASE_URL, self)
                self.valid_key_pool.set_chat_service(chat_service)
                logger.info("Emergency chat service set for ValidKeyPool")
            except Exception as e:
                logger.error(f"Failed to set emergency chat service: {e}")

    async def preload_valid_key_pool(self, target_size: Optional[int] = None) -> int:
        """
        预加载有效密钥池

        Args:
            target_size: 目标大小，默认为池大小的一半

        Returns:
            int: 成功加载的密钥数量
        """
        if self.valid_key_pool:
            return await self.valid_key_pool.preload_pool(target_size)
        return 0

    def get_valid_key_pool_stats(self) -> Optional[Dict]:
        """
        获取有效密钥池统计信息

        Returns:
            Optional[Dict]: 池统计信息，如果池不可用则返回None
        """
        if self.valid_key_pool:
            return self.valid_key_pool.get_pool_stats()
        return None

    async def get_next_key(self) -> Optional[str]:
        """获取下一个有效的API key，使用索引循环"""
        async with self.failure_count_lock: # Re-using lock for simplicity
            if not self.valid_api_keys:
                return None
            
            # Ensure index is within bounds
            if self.key_index >= len(self.valid_api_keys):
                self.key_index = 0
            
            key = self.valid_api_keys[self.key_index]
            self.key_index = (self.key_index + 1) % len(self.valid_api_keys)
            return key

    async def get_next_vertex_key(self) -> str:
        """获取下一个 Vertex Express API key"""
        async with self.vertex_key_cycle_lock:
            return next(self.vertex_key_cycle)

    async def is_key_valid(self, key: str) -> bool:
        """检查key是否有效"""
        async with self.failure_count_lock:
            return self.key_failure_counts[key] < self.MAX_FAILURES

    async def is_vertex_key_valid(self, key: str) -> bool:
        """检查 Vertex key 是否有效"""
        async with self.vertex_failure_count_lock:
            return self.vertex_key_failure_counts[key] < self.MAX_FAILURES

    async def is_key_available_for_verification(self, key: str) -> bool:
        """
        检查一个密钥是否可用于验证。
        一个密钥可用，前提是它没有被永久禁用，并且没有因为测试模型而处于冷却状态。
        """
        async with self.failure_count_lock:
            # 1. 检查是否被永久禁用
            if self.key_failure_counts.get(key, 0) >= self.MAX_FAILURES:
                return False

            # 2. 检查是否因测试模型而处于冷却状态
            test_model = settings.TEST_MODEL
            now = datetime.now(pytz.utc)
            model_statuses = self.key_model_status.get(key, {})
            expiry_time = model_statuses.get(test_model)
            
            if expiry_time and now < expiry_time:
                # 对于测试模型，它正处于冷却期，因此不可用于验证
                return False

            return True

    async def reset_failure_counts(self):
        """重置所有key的失败计数"""
        async with self.failure_count_lock:
            for key in self.key_failure_counts:
                self.key_failure_counts[key] = 0

    async def reset_vertex_failure_counts(self):
        """重置所有 Vertex key 的失败计数"""
        async with self.vertex_failure_count_lock:
            for key in self.vertex_key_failure_counts:
                self.vertex_key_failure_counts[key] = 0

    async def reset_key_failure_count(self, key: str) -> bool:
        """重置指定key的失败计数"""
        async with self.failure_count_lock:
            if key in self.key_failure_counts:
                self.key_failure_counts[key] = 0
                # If key was previously marked as invalid, re-add it to the valid list
                if key not in self.valid_api_keys:
                    self.valid_api_keys.append(key)
                    logger.info(f"Key {redact_key_for_logging(key)} re-validated and added back to the pool.")
                logger.info(f"Reset failure count for key: {redact_key_for_logging(key)}")
                return True
            logger.warning(
                f"Attempt to reset failure count for non-existent key: {key}"
            )
            return False

    async def reset_vertex_key_failure_count(self, key: str) -> bool:
        """重置指定 Vertex key 的失败计数"""
        async with self.vertex_failure_count_lock:
            if key in self.vertex_key_failure_counts:
                self.vertex_key_failure_counts[key] = 0
                logger.info(f"Reset failure count for Vertex key: {redact_key_for_logging(key)}")
                return True
            logger.warning(
                f"Attempt to reset failure count for non-existent Vertex key: {key}"
            )
            return False

    async def get_next_working_key(self, model_name: str = None) -> str:
        """
        获取下一个可用的API key。
        优先使用有效密钥池，如果池不可用则使用原有逻辑。
        如果提供了 model_name，会额外检查该 key 是否因特定模型的配额问题而处于冷却状态。
        """
        # 优先使用有效密钥池
        if self.valid_key_pool:
            try:
                # 确保聊天服务已设置
                if not self.valid_key_pool.chat_service:
                    self._ensure_chat_service_set()

                return await self.valid_key_pool.get_valid_key(model_name)
            except Exception as e:
                logger.warning(f"ValidKeyPool failed, falling back to original logic: {e}")

        # Fallback到原有逻辑
        return await self._original_get_next_working_key(model_name)

    async def _original_get_next_working_key(self, model_name: str = None) -> str:
        """
        获取下一个可用API key的优化逻辑。
        它会从一个只包含有效密钥的列表中获取，并在失败时从中移除。
        """
        async with self.failure_count_lock: # Using this lock to protect valid_api_keys and key_index
            if not self.valid_api_keys:
                logger.error("No valid API keys available in the list.")
                # As a last resort, try to use the original full list
                if self.api_keys:
                    return self.api_keys[0]
                return ""

            start_index = self.key_index
            for _ in range(len(self.valid_api_keys)):
                current_key = self.valid_api_keys[self.key_index]

                # 1. 检查特定模型的冷却状态
                is_in_cooldown = False
                if model_name:
                    now = datetime.now(pytz.utc)
                    model_statuses = self.key_model_status.get(current_key, {})
                    expiry_time = model_statuses.get(model_name)
                    if expiry_time and now < expiry_time:
                        logger.info(f"Key {redact_key_for_logging(current_key)} is in cooldown for model {model_name}. Skipping.")
                        is_in_cooldown = True

                if not is_in_cooldown:
                    # 2. 如果所有检查都通过，返回当前key并更新索引
                    self.key_index = (self.key_index + 1) % len(self.valid_api_keys)
                    return current_key
                
                # 3. 如果在冷却中，继续下一个
                self.key_index = (self.key_index + 1) % len(self.valid_api_keys)
                if self.key_index == start_index:
                    # We have cycled through all keys and all are in cooldown
                    logger.warning(f"All available keys are in cooldown for model {model_name}.")
                    # Return the key anyway, let the caller handle the cooldown error
                    return self.valid_api_keys[self.key_index]

        logger.error("Could not find a working key after a full cycle through the valid list.")
        return self.api_keys[0] if self.api_keys else "" # Absolute fallback

    async def get_next_working_vertex_key(self) -> str:
        """获取下一可用的 Vertex Express API key"""
        initial_key = await self.get_next_vertex_key()
        current_key = initial_key

        while True:
            if await self.is_vertex_key_valid(current_key):
                return current_key

            current_key = await self.get_next_vertex_key()
            if current_key == initial_key:
                return current_key

    async def mark_key_model_as_cooling(self, api_key: str, model_name: str):
        """
        将指定 key 的特定 model 标记为冷却状态，直到下一个重置时间。
        """
        try:
            tz = pytz.timezone(settings.TIMEZONE)
        except pytz.UnknownTimeZoneError:
            logger.error(f"Unknown timezone: {settings.TIMEZONE}. Falling back to UTC.")
            tz = pytz.utc

        now = datetime.now(tz)
        reset_hour = settings.GEMINI_QUOTA_RESET_HOUR
        
        # 计算下一个重置时间
        reset_time_today = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
        if now >= reset_time_today:
            # 如果当前时间已经超过今天的重置时间，则下一个重置点是明天
            next_reset_time = reset_time_today + timedelta(days=1)
        else:
            # 否则是今天的重置时间
            next_reset_time = reset_time_today

        if api_key not in self.key_model_status:
            self.key_model_status[api_key] = {}
        
        self.key_model_status[api_key][model_name] = next_reset_time.astimezone(pytz.utc)
        logger.info(f"Key {api_key} for model {model_name} has been put into cooldown until {next_reset_time} ({settings.TIMEZONE}).")

    async def mark_key_as_failed(self, api_key: str):
        """立即将一个key标记为失败状态"""
        async with self.failure_count_lock:
            if api_key in self.key_failure_counts:
                self.key_failure_counts[api_key] = self.MAX_FAILURES
                # Also remove from valid list
                if api_key in self.valid_api_keys:
                    self.valid_api_keys.remove(api_key)
                logger.warning(f"API key {redact_key_for_logging(api_key)} has been marked as failed immediately due to a critical error (e.g., 403).")

    async def handle_api_failure(self, api_key: str, retries: int, model_name: str = None) -> str:
        """处理API调用失败"""
        async with self.failure_count_lock:
            self.key_failure_counts[api_key] += 1
            if self.key_failure_counts[api_key] >= self.MAX_FAILURES:
                logger.warning(
                    f"API key {redact_key_for_logging(api_key)} has failed {self.MAX_FAILURES} times and is being removed from the valid pool."
                )
                # Remove from valid list
                if api_key in self.valid_api_keys:
                    self.valid_api_keys.remove(api_key)
        if retries < settings.MAX_RETRIES:
            return await self.get_next_working_key(model_name=model_name)
        else:
            return ""

    async def handle_vertex_api_failure(self, api_key: str, retries: int) -> str:
        """处理 Vertex Express API 调用失败"""
        async with self.vertex_failure_count_lock:
            self.vertex_key_failure_counts[api_key] += 1
            if self.vertex_key_failure_counts[api_key] >= self.MAX_FAILURES:
                logger.warning(
                    f"Vertex Express API key {redact_key_for_logging(api_key)} has failed {self.MAX_FAILURES} times"
                )

    def get_fail_count(self, key: str) -> int:
        """获取指定密钥的失败次数"""
        return self.key_failure_counts.get(key, 0)

    def get_vertex_fail_count(self, key: str) -> int:
        """获取指定 Vertex 密钥的失败次数"""
        return self.vertex_key_failure_counts.get(key, 0)

    async def get_all_keys_with_fail_count(self) -> dict:
        """获取所有API key及其失败次数"""
        all_keys = {}
        async with self.failure_count_lock:
            for key in self.api_keys:
                all_keys[key] = self.key_failure_counts.get(key, 0)
        
        valid_keys = {k: v for k, v in all_keys.items() if v < self.MAX_FAILURES}
        invalid_keys = {k: v for k, v in all_keys.items() if v >= self.MAX_FAILURES}
        
        return {"valid_keys": valid_keys, "invalid_keys": invalid_keys, "all_keys": all_keys}

    async def get_keys_by_status(self) -> dict:
        """获取分类后的API key列表，包括失败次数"""
        valid_keys = {}
        invalid_keys = {}

        async with self.failure_count_lock:
            for key in self.api_keys:
                fail_count = self.key_failure_counts[key]
                if fail_count < self.MAX_FAILURES:
                    valid_keys[key] = fail_count
                else:
                    invalid_keys[key] = fail_count

        return {"valid_keys": valid_keys, "invalid_keys": invalid_keys}

    async def get_vertex_keys_by_status(self) -> dict:
        """获取分类后的 Vertex Express API key 列表，包括失败次数"""
        valid_keys = {}
        invalid_keys = {}

        async with self.vertex_failure_count_lock:
            for key in self.vertex_api_keys:
                fail_count = self.vertex_key_failure_counts[key]
                if fail_count < self.MAX_FAILURES:
                    valid_keys[key] = fail_count
                else:
                    invalid_keys[key] = fail_count
        return {"valid_keys": valid_keys, "invalid_keys": invalid_keys}

    async def get_first_valid_key(self) -> str:
        """获取第一个有效的API key"""
        async with self.failure_count_lock:
            for key in self.key_failure_counts:
                if self.key_failure_counts[key] < self.MAX_FAILURES:
                    return key
        if self.api_keys:
            return self.api_keys[0]
        if not self.api_keys:
            logger.warning("API key list is empty, cannot get first valid key.")
            return ""
        return self.api_keys[0]

    async def get_random_valid_key(self) -> str:
        """获取随机的有效API key"""
        valid_keys = []
        async with self.failure_count_lock:
            for key in self.key_failure_counts:
                if self.key_failure_counts[key] < self.MAX_FAILURES:
                    valid_keys.append(key)
        
        if valid_keys:
            return random.choice(valid_keys)
        
        # 如果没有有效的key，返回第一个key作为fallback
        if self.api_keys:
            logger.warning("No valid keys available, returning first key as fallback.")
            return self.api_keys[0]
        
        logger.warning("API key list is empty, cannot get random valid key.")
        return ""

    async def remove_key(self, key_to_remove: str):
        """
        从 KeyManager 中安全地移除一个密钥。
        """
        # Using failure_count_lock as it now protects the valid_api_keys list
        async with self.failure_count_lock:
            if key_to_remove not in self.api_keys:
                logger.warning(f"Attempted to remove a non-existent key: {redact_key_for_logging(key_to_remove)}")
                return False

            # 1. 从主列表中移除
            if key_to_remove in self.api_keys:
                self.api_keys.remove(key_to_remove)
                logger.debug(f"Removed '{redact_key_for_logging(key_to_remove)}' from api_keys list.")

            # 2. 从有效列表中移除
            if key_to_remove in self.valid_api_keys:
                self.valid_api_keys.remove(key_to_remove)
                logger.debug(f"Removed '{redact_key_for_logging(key_to_remove)}' from valid_api_keys list.")

            # 3. 从失败计数中移除
            if key_to_remove in self.key_failure_counts:
                del self.key_failure_counts[key_to_remove]
                logger.debug(f"Removed '{redact_key_for_logging(key_to_remove)}' from failure counts.")

            # 3. 从模型状态中移除
            if key_to_remove in self.key_model_status:
                del self.key_model_status[key_to_remove]
                logger.debug(f"Removed '{redact_key_for_logging(key_to_remove)}' from model status.")

            # 4. 从有效密钥池中移除
            if self.valid_key_pool and self.valid_key_pool.valid_keys:
                initial_pool_size = len(self.valid_key_pool.valid_keys)
                # 保持deque类型，不要转换为list
                from collections import deque
                filtered_keys = deque(
                    key_obj for key_obj in self.valid_key_pool.valid_keys if key_obj.key != key_to_remove
                )
                self.valid_key_pool.valid_keys = filtered_keys

                # 同时从_pool_keys_set中移除
                if hasattr(self.valid_key_pool, '_pool_keys_set') and key_to_remove in self.valid_key_pool._pool_keys_set:
                    self.valid_key_pool._pool_keys_set.remove(key_to_remove)

                removed_count = initial_pool_size - len(self.valid_key_pool.valid_keys)
                if removed_count > 0:
                    logger.debug(f"Removed {removed_count} instance(s) of '{redact_key_for_logging(key_to_remove)}' from ValidKeyPool.")

            # 5. 重置索引（如果需要）
            if self.key_index >= len(self.valid_api_keys) and self.valid_api_keys:
                self.key_index = 0

            logger.info(f"Key '{redact_key_for_logging(key_to_remove)}' has been successfully removed from KeyManager.")
            return True

    async def remove_all_invalid_keys(self) -> int:
        """
        Remove all keys that are marked as invalid (failure count >= MAX_FAILURES).
        """
        invalid_keys_to_remove = []
        async with self.failure_count_lock:
            # Create a copy to iterate over, as we will be modifying the original dict
            key_failure_counts_copy = self.key_failure_counts.copy()
            for key, fail_count in key_failure_counts_copy.items():
                if fail_count >= self.MAX_FAILURES:
                    invalid_keys_to_remove.append(key)
        
        removed_count = 0
        for key in invalid_keys_to_remove:
            if await self.remove_key(key):
                removed_count += 1
        
        logger.info(f"Attempted to remove {len(invalid_keys_to_remove)} invalid keys, successfully removed {removed_count}.")
        return removed_count

    async def remove_key_from_pool(self, key_to_remove: str):
        """
        仅从 ValidKeyPool 中移除一个密钥，不影响其在主列表中的状态。
        用于密钥因临时问题（如速率限制）需要暂时移出活跃池的场景。
        """
        if self.valid_key_pool and self.valid_key_pool.valid_keys:
            async with self.failure_count_lock: # Use a lock to protect pool access
                initial_pool_size = len(self.valid_key_pool.valid_keys)
                
                from collections import deque
                filtered_keys = deque(
                    key_obj for key_obj in self.valid_key_pool.valid_keys if key_obj.key != key_to_remove
                )
                
                if len(filtered_keys) < initial_pool_size:
                    self.valid_key_pool.valid_keys = filtered_keys
                    
                    if hasattr(self.valid_key_pool, '_pool_keys_set') and key_to_remove in self.valid_key_pool._pool_keys_set:
                        self.valid_key_pool._pool_keys_set.remove(key_to_remove)
                    
                    logger.info(f"Key '{redact_key_for_logging(key_to_remove)}' temporarily removed from ValidKeyPool.")
                    return True
        return False


_singleton_instance = None
_singleton_lock = asyncio.Lock()
_preserved_failure_counts: Union[Dict[str, int], None] = None
_preserved_vertex_failure_counts: Union[Dict[str, int], None] = None
_preserved_old_api_keys_for_reset: Union[list, None] = None
_preserved_vertex_old_api_keys_for_reset: Union[list, None] = None
_preserved_next_key_in_cycle: Union[str, None] = None
_preserved_vertex_next_key_in_cycle: Union[str, None] = None
_preserved_valid_key_pool_keys: Union[list, None] = None  # 保存池子中的密钥
_preserved_valid_key_pool_stats: Union[dict, None] = None  # 保存池子的统计信息


async def get_key_manager_instance(
    api_keys: list = None, vertex_api_keys: list = None
) -> KeyManager:
    """
    获取 KeyManager 单例实例。

    如果尚未创建实例，将使用提供的 api_keys,vertex_api_keys 初始化 KeyManager。
    如果已创建实例，则忽略 api_keys 参数，返回现有单例。
    如果在重置后调用，会尝试恢复之前的状态（失败计数、循环位置）。
    """
    global _singleton_instance, _preserved_failure_counts, _preserved_vertex_failure_counts, _preserved_old_api_keys_for_reset, _preserved_vertex_old_api_keys_for_reset, _preserved_next_key_in_cycle, _preserved_vertex_next_key_in_cycle, _preserved_valid_key_pool_keys, _preserved_valid_key_pool_stats

    async with _singleton_lock:
        if _singleton_instance is None:
            if api_keys is None:
                raise ValueError(
                    "API keys are required to initialize or re-initialize the KeyManager instance."
                )
            if vertex_api_keys is None:
                raise ValueError(
                    "Vertex Express API keys are required to initialize or re-initialize the KeyManager instance."
                )

            if not api_keys:
                logger.warning(
                    "Initializing KeyManager with an empty list of API keys."
                )
            if not vertex_api_keys:
                logger.warning(
                    "Initializing KeyManager with an empty list of Vertex Express API keys."
                )

            _singleton_instance = KeyManager(api_keys, vertex_api_keys)
            logger.info(
                f"KeyManager instance created/re-created with {len(api_keys)} API keys and {len(vertex_api_keys)} Vertex Express API keys."
            )

            # 1. 恢复失败计数
            if _preserved_failure_counts:
                current_failure_counts = {
                    key: 0 for key in _singleton_instance.api_keys
                }
                for key, count in _preserved_failure_counts.items():
                    if key in current_failure_counts:
                        current_failure_counts[key] = count
                _singleton_instance.key_failure_counts = current_failure_counts
                logger.info("Inherited failure counts for applicable keys.")
            _preserved_failure_counts = None

            if _preserved_vertex_failure_counts:
                current_vertex_failure_counts = {
                    key: 0 for key in _singleton_instance.vertex_api_keys
                }
                for key, count in _preserved_vertex_failure_counts.items():
                    if key in current_vertex_failure_counts:
                        current_vertex_failure_counts[key] = count
                _singleton_instance.vertex_key_failure_counts = (
                    current_vertex_failure_counts
                )
                logger.info("Inherited failure counts for applicable Vertex keys.")
            _preserved_vertex_failure_counts = None

            # 2. 调整 key_cycle 的起始点
            start_key_for_new_cycle = None
            if (
                _preserved_old_api_keys_for_reset
                and _preserved_next_key_in_cycle
                and _singleton_instance.api_keys
            ):
                try:
                    start_idx_in_old = _preserved_old_api_keys_for_reset.index(
                        _preserved_next_key_in_cycle
                    )

                    for i in range(len(_preserved_old_api_keys_for_reset)):
                        current_old_key_idx = (start_idx_in_old + i) % len(
                            _preserved_old_api_keys_for_reset
                        )
                        key_candidate = _preserved_old_api_keys_for_reset[
                            current_old_key_idx
                        ]
                        if key_candidate in _singleton_instance.api_keys:
                            start_key_for_new_cycle = key_candidate
                            break
                except ValueError:
                    logger.warning(
                        f"Preserved next key '{_preserved_next_key_in_cycle}' not found in preserved old API keys. "
                        "New cycle will start from the beginning of the new list."
                    )
                except Exception as e:
                    logger.error(
                        f"Error determining start key for new cycle from preserved state: {e}. "
                        "New cycle will start from the beginning."
                    )

            if start_key_for_new_cycle and _singleton_instance.api_keys:
                try:
                    target_idx = _singleton_instance.api_keys.index(
                        start_key_for_new_cycle
                    )
                    for _ in range(target_idx):
                        next(_singleton_instance.key_cycle)
                    logger.info(
                        f"Key cycle in new instance advanced. Next call to get_next_key() will yield: {start_key_for_new_cycle}"
                    )
                except ValueError:
                    logger.warning(
                        f"Determined start key '{start_key_for_new_cycle}' not found in new API keys during cycle advancement. "
                        "New cycle will start from the beginning."
                    )
                except StopIteration:
                    logger.error(
                        "StopIteration while advancing key cycle, implies empty new API key list previously missed."
                    )
                except Exception as e:
                    logger.error(
                        f"Error advancing new key cycle: {e}. Cycle will start from beginning."
                    )
            else:
                if _singleton_instance.api_keys:
                    logger.info(
                        "New key cycle will start from the beginning of the new API key list (no specific start key determined or needed)."
                    )
                else:
                    logger.info(
                        "New key cycle not applicable as the new API key list is empty."
                    )

            # 清理所有保存的状态
            _preserved_old_api_keys_for_reset = None
            _preserved_next_key_in_cycle = None

            # 3. 调整 vertex_key_cycle 的起始点
            start_key_for_new_vertex_cycle = None
            if (
                _preserved_vertex_old_api_keys_for_reset
                and _preserved_vertex_next_key_in_cycle
                and _singleton_instance.vertex_api_keys
            ):
                try:
                    start_idx_in_old = _preserved_vertex_old_api_keys_for_reset.index(
                        _preserved_vertex_next_key_in_cycle
                    )

                    for i in range(len(_preserved_vertex_old_api_keys_for_reset)):
                        current_old_key_idx = (start_idx_in_old + i) % len(
                            _preserved_vertex_old_api_keys_for_reset
                        )
                        key_candidate = _preserved_vertex_old_api_keys_for_reset[
                            current_old_key_idx
                        ]
                        if key_candidate in _singleton_instance.vertex_api_keys:
                            start_key_for_new_vertex_cycle = key_candidate
                            break
                except ValueError:
                    logger.warning(
                        f"Preserved next key '{_preserved_vertex_next_key_in_cycle}' not found in preserved old Vertex Express API keys. "
                        "New cycle will start from the beginning of the new list."
                    )
                except Exception as e:
                    logger.error(
                        f"Error determining start key for new Vertex key cycle from preserved state: {e}. "
                        "New cycle will start from the beginning."
                    )

            if start_key_for_new_vertex_cycle and _singleton_instance.vertex_api_keys:
                try:
                    target_idx = _singleton_instance.vertex_api_keys.index(
                        start_key_for_new_vertex_cycle
                    )
                    for _ in range(target_idx):
                        next(_singleton_instance.vertex_key_cycle)
                    logger.info(
                        f"Vertex key cycle in new instance advanced. Next call to get_next_vertex_key() will yield: {start_key_for_new_vertex_cycle}"
                    )
                except ValueError:
                    logger.warning(
                        f"Determined start key '{start_key_for_new_vertex_cycle}' not found in new Vertex Express API keys during cycle advancement. "
                        "New cycle will start from the beginning."
                    )
                except StopIteration:
                    logger.error(
                        "StopIteration while advancing Vertex key cycle, implies empty new Vertex Express API key list previously missed."
                    )
                except Exception as e:
                    logger.error(
                        f"Error advancing new Vertex key cycle: {e}. Cycle will start from beginning."
                    )
            else:
                if _singleton_instance.vertex_api_keys:
                    logger.info(
                        "New Vertex key cycle will start from the beginning of the new Vertex Express API key list (no specific start key determined or needed)."
                    )
                else:
                    logger.info(
                        "New Vertex key cycle not applicable as the new Vertex Express API key list is empty."
                    )

            # 4. 恢复有效密钥池状态
            if _preserved_valid_key_pool_keys and _singleton_instance.valid_key_pool:
                try:
                    # 恢复池子中的密钥
                    for key_obj in _preserved_valid_key_pool_keys:
                        # 检查密钥是否仍然有效且在新的密钥列表中
                        if key_obj.key in _singleton_instance.api_keys and not key_obj.is_expired():
                            _singleton_instance.valid_key_pool.valid_keys.append(key_obj)

                    restored_count = len(_singleton_instance.valid_key_pool.valid_keys)
                    logger.info(f"Restored {restored_count} keys to ValidKeyPool after config update")
                except Exception as e:
                    logger.error(f"Error restoring ValidKeyPool state: {e}")
            _preserved_valid_key_pool_keys = None

            # 5. 恢复有效密钥池统计信息
            if _preserved_valid_key_pool_stats and _singleton_instance.valid_key_pool:
                try:
                    _singleton_instance.valid_key_pool.stats = _preserved_valid_key_pool_stats
                    logger.info("Restored ValidKeyPool statistics after config update")
                except Exception as e:
                    logger.error(f"Error restoring ValidKeyPool statistics: {e}")
            _preserved_valid_key_pool_stats = None

            # 清理所有保存的状态
            _preserved_vertex_old_api_keys_for_reset = None
            _preserved_vertex_next_key_in_cycle = None

        return _singleton_instance


async def reset_key_manager_instance():
    """
    重置 KeyManager 单例实例。
    将保存当前实例的状态（失败计数、旧 API keys、下一个 key 提示）
    以供下一次 get_key_manager_instance 调用时恢复。
    """
    global _singleton_instance, _preserved_failure_counts, _preserved_vertex_failure_counts, _preserved_old_api_keys_for_reset, _preserved_vertex_old_api_keys_for_reset, _preserved_next_key_in_cycle, _preserved_vertex_next_key_in_cycle, _preserved_valid_key_pool_keys
    async with _singleton_lock:
        if _singleton_instance:
            # 1. 保存失败计数
            _preserved_failure_counts = _singleton_instance.key_failure_counts.copy()
            _preserved_vertex_failure_counts = (
                _singleton_instance.vertex_key_failure_counts.copy()
            )

            # 2. 保存旧的 API keys 列表
            _preserved_old_api_keys_for_reset = _singleton_instance.api_keys.copy()
            _preserved_vertex_old_api_keys_for_reset = (
                _singleton_instance.vertex_api_keys.copy()
            )

            # 3. 保存 key_cycle 的下一个 key 提示
            try:
                if _singleton_instance.api_keys:
                    _preserved_next_key_in_cycle = (
                        await _singleton_instance.get_next_key()
                    )
                else:
                    _preserved_next_key_in_cycle = None
            except StopIteration:
                logger.warning(
                    "Could not preserve next key hint: key cycle was empty or exhausted in old instance."
                )
                _preserved_next_key_in_cycle = None
            except Exception as e:
                logger.error(f"Error preserving next key hint during reset: {e}")
                _preserved_next_key_in_cycle = None

            # 4. 保存 vertex_key_cycle 的下一个 key 提示
            try:
                if _singleton_instance.vertex_api_keys:
                    _preserved_vertex_next_key_in_cycle = (
                        await _singleton_instance.get_next_vertex_key()
                    )
                else:
                    _preserved_vertex_next_key_in_cycle = None
            except StopIteration:
                logger.warning(
                    "Could not preserve next key hint: Vertex key cycle was empty or exhausted in old instance."
                )
                _preserved_vertex_next_key_in_cycle = None
            except Exception as e:
                logger.error(f"Error preserving next key hint during reset: {e}")
                _preserved_vertex_next_key_in_cycle = None

            # 5. 保存有效密钥池状态
            try:
                if _singleton_instance.valid_key_pool:
                    _preserved_valid_key_pool_stats = _singleton_instance.valid_key_pool.stats.copy()
                    if _singleton_instance.valid_key_pool.valid_keys:
                        _preserved_valid_key_pool_keys = list(_singleton_instance.valid_key_pool.valid_keys)
                        logger.info(f"Preserved {len(_preserved_valid_key_pool_keys)} keys and stats from ValidKeyPool")
                    else:
                        _preserved_valid_key_pool_keys = None
                else:
                    _preserved_valid_key_pool_keys = None
                    _preserved_valid_key_pool_stats = None
            except Exception as e:
                logger.error(f"Error preserving ValidKeyPool state during reset: {e}")
                _preserved_valid_key_pool_keys = None
                _preserved_valid_key_pool_stats = None

            _singleton_instance = None
            logger.info(
                "KeyManager instance has been reset. State (failure counts, old keys, next key hint) preserved for next instantiation."
            )
        else:
            logger.info(
                "KeyManager instance was not set (or already reset), no reset action performed."
            )
