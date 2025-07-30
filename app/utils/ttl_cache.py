"""
TTL缓存工具类模块
基于现有ProxyCheckService的缓存模式实现通用TTL缓存功能
"""
import time
from typing import Any, Dict, Optional, Tuple
from app.log.logger import get_config_logger

logger = get_config_logger()


class TTLCache:
    """
    通用TTL（生存时间）缓存类
    
    提供基于时间的缓存管理功能，支持自动过期清理和统计信息
    """
    
    def __init__(self, ttl_seconds: int):
        """
        初始化TTL缓存
        
        Args:
            ttl_seconds: 缓存项的生存时间（秒）
        """
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self.ttl_seconds = ttl_seconds
        
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存项
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，如果不存在或已过期则返回None
        """
        if key in self._cache:
            value, timestamp = self._cache[key]
            # 检查缓存是否过期
            if time.time() - timestamp < self.ttl_seconds:
                logger.debug(f"Cache hit for key: {key}")
                return value
            else:
                # 移除过期缓存
                del self._cache[key]
                logger.debug(f"Cache expired and removed for key: {key}")
        
        logger.debug(f"Cache miss for key: {key}")
        return None
    
    def put(self, key: str, value: Any) -> None:
        """
        存储缓存项
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        self._cache[key] = (value, time.time())
        logger.debug(f"Cache stored for key: {key}")
    
    def remove(self, key: str) -> bool:
        """
        移除指定缓存项
        
        Args:
            key: 缓存键
            
        Returns:
            是否成功移除
        """
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Cache removed for key: {key}")
            return True
        return False
    
    def remove_expired(self) -> int:
        """
        清理所有过期缓存项
        
        Returns:
            清理的缓存项数量
        """
        current_time = time.time()
        expired_keys = []
        
        for key, (_, timestamp) in self._cache.items():
            if current_time - timestamp >= self.ttl_seconds:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache[key]
        
        if expired_keys:
            logger.info(f"Removed {len(expired_keys)} expired cache items")
        
        return len(expired_keys)
    
    def get_stats(self) -> Dict[str, int]:
        """
        获取缓存统计信息
        
        Returns:
            包含缓存统计信息的字典
        """
        current_time = time.time()
        valid_cache_count = sum(
            1 for _, timestamp in self._cache.values()
            if current_time - timestamp < self.ttl_seconds
        )
        
        return {
            "total_cached": len(self._cache),
            "valid_cached": valid_cache_count,
            "expired_cached": len(self._cache) - valid_cache_count,
            "ttl_seconds": self.ttl_seconds
        }
    
    def clear(self) -> None:
        """清空所有缓存"""
        cache_count = len(self._cache)
        self._cache.clear()
        logger.info(f"Cache cleared, removed {cache_count} items")
    
    def size(self) -> int:
        """获取当前缓存项数量"""
        return len(self._cache)
    
    def contains(self, key: str) -> bool:
        """
        检查缓存中是否包含指定键（不考虑过期）
        
        Args:
            key: 缓存键
            
        Returns:
            是否包含该键
        """
        return key in self._cache
    
    def is_expired(self, key: str) -> bool:
        """
        检查指定缓存项是否已过期
        
        Args:
            key: 缓存键
            
        Returns:
            是否已过期，如果键不存在返回True
        """
        if key not in self._cache:
            return True
        
        _, timestamp = self._cache[key]
        return time.time() - timestamp >= self.ttl_seconds
