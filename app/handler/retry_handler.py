
import re
from functools import wraps
from typing import Callable, TypeVar

from app.config.config import settings
from app.handler.error_processor import handle_api_error_and_get_next_key
from app.log.logger import get_retry_logger
from app.utils.helpers import redact_key_for_logging

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
                    error_str = str(e)

                    # 检查是否是应该立即切换key的错误类型
                    is_429_error = "429" in error_str
                    is_auth_error = "401" in error_str or "403" in error_str
                    is_client_error = "400" in error_str or "404" in error_str or "422" in error_str
                    is_server_error = "500" in error_str or "502" in error_str or "504" in error_str
                    is_fatal_error = is_auth_error or is_client_error or is_server_error
                    should_switch_key_immediately = is_429_error or is_fatal_error

                    logger.warning(
                        f"API call failed with error: {error_str}. Attempt {retries} of {settings.MAX_RETRIES}"
                        f"{' (will switch key immediately)' if should_switch_key_immediately else ''}"
                    )

                    # 从函数参数中获取 key_manager
                    key_manager = kwargs.get("key_manager")
                    if key_manager:
                        old_key = kwargs.get(self.key_arg)
                        model_name = kwargs.get("model_name")

                        logger.info(f"Retry attempt {retries}: calling error handler for key {redact_key_for_logging(old_key)}")

                        new_key = await handle_api_error_and_get_next_key(
                            key_manager, e, old_key, model_name, retries
                        )

                        logger.info(f"Error handler returned: old_key={redact_key_for_logging(old_key)}, new_key={redact_key_for_logging(new_key)}")

                        if new_key and new_key != old_key:
                            kwargs[self.key_arg] = new_key
                            logger.info(f"Switched to new API key: {redact_key_for_logging(new_key)} (reason: {error_str[:50]}...)")
                        elif should_switch_key_immediately:
                            # 对于应该立即切换key的错误，如果没有新key可用，直接失败
                            logger.error(f"No valid API key available for immediate switch after {error_str[:50]}... Breaking retry loop.")
                            break
                        else:
                            logger.error(f"No valid API key available after {retries} retries.")
                            break
                    else:
                        logger.warning(f"No key_manager available for retry attempt {retries}, cannot switch keys")

            logger.error(
                f"All retry attempts failed, raising final exception: {str(last_exception)}"
            )
            raise last_exception

        return wrapper
