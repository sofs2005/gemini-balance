"""
静态资源版本控制工具
用于给CSS和JS文件添加版本参数，避免浏览器缓存问题
"""

import hashlib
import time
from functools import lru_cache
from pathlib import Path
from typing import Dict

from app.utils.helpers import get_current_version


class StaticVersionManager:
    """静态资源版本管理器"""

    def __init__(self, static_dir: str = "app/static"):
        self.static_dir = Path(static_dir)
        self._version_cache: Dict[str, str] = {}
        self._use_file_hash = True  # 是否使用文件哈希作为版本号

    def get_version_for_file(self, file_path: str) -> str:
        """
        获取文件的版本号

        Args:
            file_path: 相对于static目录的文件路径，如 'css/fonts.css'

        Returns:
            版本号字符串
        """
        if self._use_file_hash:
            return self._get_file_hash_version(file_path)
        else:
            return self._get_app_version()

    def _get_file_hash_version(self, file_path: str) -> str:
        """基于文件内容生成哈希版本号"""
        # 如果已经缓存过，直接返回
        if file_path in self._version_cache:
            return self._version_cache[file_path]

        full_path = self.static_dir / file_path

        if not full_path.exists():
            # 文件不存在，使用应用版本号作为fallback
            version = self._get_app_version()
        else:
            try:
                # 读取文件内容并计算MD5哈希
                with open(full_path, "rb") as f:
                    content = f.read()
                    hash_object = hashlib.md5(content)
                    version = hash_object.hexdigest()[:8]  # 取前8位
            except Exception:
                # 读取失败，使用应用版本号作为fallback
                version = self._get_app_version()

        # 缓存结果
        self._version_cache[file_path] = version
        return version

    def _get_app_version(self) -> str:
        """获取应用程序版本号"""
        try:
            return get_current_version().replace(".", "")
        except Exception:
            # 如果获取版本失败，使用时间戳
            return str(int(time.time()))

    def get_versioned_url(self, file_path: str) -> str:
        """
        获取带版本参数的URL

        Args:
            file_path: 相对于static目录的文件路径

        Returns:
            带版本参数的URL
        """
        version = self.get_version_for_file(file_path)
        return f"/static/{file_path}?v={version}"

    def clear_cache(self):
        """清空版本缓存"""
        self._version_cache.clear()


# 全局实例
_static_version_manager = StaticVersionManager()


def get_static_url(file_path: str) -> str:
    """
    获取静态资源的版本化URL

    Args:
        file_path: 相对于static目录的文件路径

    Returns:
        带版本参数的完整URL

    Example:
        get_static_url('css/fonts.css') -> '/static/css/fonts.css?v=a1b2c3d4'
        get_static_url('js/config_editor.js') -> '/static/js/config_editor.js?v=e5f6g7h8'
    """
    return _static_version_manager.get_versioned_url(file_path)


def clear_static_cache():
    """清空静态资源版本缓存"""
    _static_version_manager.clear_cache()


@lru_cache(maxsize=128)
def get_cached_static_url(file_path: str) -> str:
    """
    获取缓存的静态资源URL（用于开发环境）

    Args:
        file_path: 相对于static目录的文件路径

    Returns:
        带版本参数的完整URL
    """
    return get_static_url(file_path)
