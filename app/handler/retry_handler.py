
import re
from functools import wraps
from typing import Callable, TypeVar

from app.config.config import settings
from app.handler.error_processor import handle_api_error_and_get_next_key
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

                        new_key = await handle_api_error_and_get_next_key(
                            key_manager, e, old_key, model_name, retries
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
