"""
有效密钥数据模型模块
定义带TTL的有效密钥数据类
"""
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

from app.log.logger import get_key_manager_logger

logger = get_key_manager_logger()


@dataclass
class ValidKeyWithTTL:
    """
    带TTL的有效密钥数据类
    
    封装密钥字符串、创建时间、过期时间等信息，
    提供TTL管理和过期检查功能
    """
    key: str
    created_at: datetime
    expires_at: datetime
    ttl_hours: int = 2
    
    def __init__(self, key: str, ttl_hours: int = 2):
        """
        初始化有效密钥对象
        
        Args:
            key: API密钥字符串
            ttl_hours: 生存时间（小时），默认2小时
        """
        self.key = key
        self.ttl_hours = ttl_hours
        self.created_at = datetime.now()
        self.expires_at = self.created_at + timedelta(hours=ttl_hours)
        
        logger.debug(f"Created ValidKeyWithTTL for key {key[:8]}..., expires at {self.expires_at}")
    
    def is_expired(self) -> bool:
        """
        检查密钥是否已过期
        
        Returns:
            bool: 如果已过期返回True，否则返回False
        """
        now = datetime.now()
        expired = now > self.expires_at
        
        if expired:
            logger.debug(f"Key {self.key[:8]}... has expired at {self.expires_at}")
        
        return expired
    
    def remaining_time(self) -> timedelta:
        """
        获取剩余有效时间
        
        Returns:
            timedelta: 剩余时间，如果已过期则返回负值
        """
        now = datetime.now()
        remaining = self.expires_at - now
        
        logger.debug(f"Key {self.key[:8]}... has {remaining} remaining time")
        
        return remaining
    
    def remaining_seconds(self) -> int:
        """
        获取剩余有效时间（秒）
        
        Returns:
            int: 剩余秒数，如果已过期则返回0
        """
        remaining = self.remaining_time()
        seconds = max(0, int(remaining.total_seconds()))
        
        return seconds
    
    def age_seconds(self) -> int:
        """
        获取密钥年龄（秒）
        
        Returns:
            int: 从创建到现在的秒数
        """
        now = datetime.now()
        age = now - self.created_at
        return int(age.total_seconds())
    
    def refresh_ttl(self, new_ttl_hours: Optional[int] = None) -> None:
        """
        刷新TTL，重新设置过期时间
        
        Args:
            new_ttl_hours: 新的TTL小时数，如果为None则使用原有TTL
        """
        if new_ttl_hours is not None:
            self.ttl_hours = new_ttl_hours
        
        self.created_at = datetime.now()
        self.expires_at = self.created_at + timedelta(hours=self.ttl_hours)
        
        logger.debug(f"Refreshed TTL for key {self.key[:8]}..., new expiry: {self.expires_at}")
    
    def __str__(self) -> str:
        """字符串表示"""
        return f"ValidKeyWithTTL(key={self.key[:8]}..., expires_at={self.expires_at})"
    
    def __repr__(self) -> str:
        """详细字符串表示"""
        return (f"ValidKeyWithTTL(key='{self.key[:8]}...', "
                f"created_at={self.created_at}, "
                f"expires_at={self.expires_at}, "
                f"ttl_hours={self.ttl_hours})")
    
    def to_dict(self) -> dict:
        """
        转换为字典格式
        
        Returns:
            dict: 包含密钥信息的字典（不包含完整密钥）
        """
        return {
            "key_prefix": self.key[:8] + "...",
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "ttl_hours": self.ttl_hours,
            "is_expired": self.is_expired(),
            "remaining_seconds": self.remaining_seconds(),
            "age_seconds": self.age_seconds()
        }
