
import re
from functools import wraps
from typing import Callable, TypeVar

from app.config.config import settings
from app.log.logger import get_retry_logger

T = TypeVar("T")
logger = get_retry_logger()


class RetryHandler:
    """重试处理装饰器"""

    def __init__(self, key_arg: str = "api_key"):
        self.key_arg = key_arg

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(settings.MAX_RETRIES):
                retries = attempt + 1
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    logger.warning(
                        f"API call failed with error: {str(e)}. Attempt {retries} of {settings.MAX_RETRIES}"
                    )

                    # 从函数参数中获取 key_manager
                    key_manager = kwargs.get("key_manager")
                    if key_manager:
                        old_key = kwargs.get(self.key_arg)
                        model_name = kwargs.get("model_name")

                        error_str = str(e)
                        is_429_error = "429" in error_str
                        is_403_error = "403" in error_str

                        new_key = None
                        if is_429_error and model_name:
                            logger.info(f"Detected 429 error for model '{model_name}' with key '{old_key}'. Marking key for model-specific cooldown.")
                            await key_manager.mark_key_model_as_cooling(old_key, model_name)
                            # 对于429错误，我们只获取下一个可用的key，而不对当前key进行通用失败计数
                            new_key = await key_manager.get_next_working_key(model_name=model_name)
                        elif is_403_error:
                            logger.warning(f"Detected 403 Forbidden error for key '{old_key}'. Marking key as failed immediately.")
                            await key_manager.mark_key_as_failed(old_key)
                            new_key = await key_manager.get_next_working_key(model_name=model_name)
                        else:
                            # 对于其他所有错误，使用原始的失败计数和重试逻辑
                            new_key = await key_manager.handle_api_failure(
                                old_key, retries, model_name=model_name
                            )

                        if new_key and new_key != old_key:
                            kwargs[self.key_arg] = new_key
                            logger.info(f"Switched to new API key: {new_key}")
                        elif not new_key:
                            logger.error(
                                f"No valid API key available after {retries} retries."
                            )
                            break

            logger.error(
                f"All retry attempts failed, raising final exception: {str(last_exception)}"
            )
            raise last_exception

        return wrapper
