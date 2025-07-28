import re
from app.log.logger import get_gemini_logger
from app.service.key.key_manager import KeyManager
from app.database.services import add_error_log

logger = get_gemini_logger()


async def handle_api_error_and_get_next_key(
    key_manager: KeyManager, error: Exception, old_key: str, model_name: str = None, retries: int = 1
) -> str:
    """
    统一处理API错误，根据错误类型执行相应操作，并返回一个新的可用密钥。
    """
    error_str = str(error)
    is_429_error = "429" in error_str
    is_fatal_error = "400" in error_str or "401" in error_str or "403" in error_str
    is_503_error = "503" in error_str

    # 提取错误代码
    error_code = None
    match = re.search(r"status code (\d+)", error_str)
    if match:
        error_code = int(match.group(1))
    elif is_429_error:
        error_code = 429
    elif is_fatal_error:
        if "400" in error_str:
            error_code = 400
        elif "401" in error_str:
            error_code = 401
        elif "403" in error_str:
            error_code = 403
    elif is_503_error:
        error_code = 503

    # 确定错误类型
    error_type = None
    if is_429_error:
        error_type = "RATE_LIMIT"
    elif is_fatal_error:
        error_type = "AUTH_ERROR" if error_code in [401, 403] else "CLIENT_ERROR"
    elif is_503_error:
        error_type = "SERVICE_UNAVAILABLE"
    else:
        error_type = "UNKNOWN_ERROR"

    # 记录错误日志
    try:
        await add_error_log(
            gemini_key=old_key,
            model_name=model_name,
            error_type=error_type,
            error_log=error_str,
            error_code=error_code,
            request_msg={"retries": retries, "source": "error_processor"}
        )
        logger.info(f"Error log recorded for key {old_key[:8]}... with error type {error_type}")
    except Exception as log_error:
        logger.error(f"Failed to record error log: {str(log_error)}")

    new_key = None
    if is_429_error and model_name:
        logger.info(f"Detected 429 error for model '{model_name}' with key '{old_key}'. Marking key for model-specific cooldown.")
        await key_manager.mark_key_model_as_cooling(old_key, model_name)
        new_key = await key_manager.get_next_working_key(model_name=model_name)
    elif is_fatal_error:
        logger.warning(f"Detected fatal error ({error_str.split(',')[0]}) for key '{old_key}'. Marking key as failed immediately.")
        await key_manager.mark_key_as_failed(old_key)
        new_key = await key_manager.get_next_working_key(model_name=model_name)
    elif is_503_error:
        logger.warning(f"Detected 503 Service Unavailable for key '{old_key}'. Switching key without penalty.")
        new_key = await key_manager.get_next_working_key(model_name=model_name)
    else:
        # For other errors, use the original failure counting logic
        new_key = await key_manager.handle_api_failure(
            old_key, retries, model_name=model_name
        )

    return new_key