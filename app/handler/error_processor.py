import re
from app.log.logger import get_gemini_logger
from app.service.key.key_manager import KeyManager
from app.database.services import add_error_log
from app.utils.helpers import redact_key_for_logging

logger = get_gemini_logger()


async def handle_api_error_and_get_next_key(
    key_manager: KeyManager, error: Exception, old_key: str, model_name: str = None, retries: int = 1
) -> str:
    """
    统一处理API错误，根据错误类型执行相应操作，并返回一个新的可用密钥。
    """
    error_str = str(error)

    # 分类错误类型
    is_429_error = "429" in error_str
    is_auth_error = "401" in error_str or "403" in error_str  # 认证/授权错误
    is_client_error = "400" in error_str or "404" in error_str or "422" in error_str  # 客户端错误
    is_server_error = "500" in error_str or "502" in error_str or "504" in error_str  # 服务器错误
    is_service_unavailable = "503" in error_str  # 服务不可用（可重试）
    is_timeout_error = "408" in error_str  # 请求超时（可重试）

    # 需要立即切换key的错误（不应该重试同一个key）
    is_fatal_error = is_auth_error or is_client_error or is_server_error
    # 可以重试的错误（服务端临时问题）
    is_retryable_error = is_service_unavailable or is_timeout_error

    # 提取错误代码
    error_code = None
    match = re.search(r"status code (\d+)", error_str)
    if match:
        error_code = int(match.group(1))
    elif is_429_error:
        error_code = 429
    elif is_auth_error:
        if "401" in error_str:
            error_code = 401
        elif "403" in error_str:
            error_code = 403
    elif is_client_error:
        if "400" in error_str:
            error_code = 400
        elif "404" in error_str:
            error_code = 404
        elif "422" in error_str:
            error_code = 422
    elif is_server_error:
        if "500" in error_str:
            error_code = 500
        elif "502" in error_str:
            error_code = 502
        elif "504" in error_str:
            error_code = 504
    elif is_service_unavailable:
        error_code = 503
    elif is_timeout_error:
        error_code = 408

    # 确定错误类型
    error_type = None
    if is_429_error:
        error_type = "RATE_LIMIT"
    elif is_auth_error:
        error_type = "AUTH_ERROR"
    elif is_client_error:
        error_type = "CLIENT_ERROR"
    elif is_server_error:
        error_type = "SERVER_ERROR"
    elif is_service_unavailable:
        error_type = "SERVICE_UNAVAILABLE"
    elif is_timeout_error:
        error_type = "TIMEOUT_ERROR"
    else:
        error_type = "UNKNOWN_ERROR"

    # 记录错误日志
    try:
        logger.info(f"Attempting to record error log for key {old_key[:8]}... with error type {error_type}")
        result = await add_error_log(
            gemini_key=old_key,
            model_name=model_name,
            error_type=error_type,
            error_log=error_str,
            error_code=error_code,
            request_msg={"retries": retries, "source": "error_processor"}
        )
        if result:
            logger.info(f"Error log recorded successfully for key {old_key[:8]}... with error type {error_type}")
        else:
            logger.warning(f"Error log recording returned False for key {old_key[:8]}... with error type {error_type}")
    except Exception as log_error:
        logger.error(f"Failed to record error log for key {old_key[:8]}...: {str(log_error)}", exc_info=True)

    new_key = None
    logger.info(f"Processing error for key {old_key[:8]}...: error_type={error_type}, should_switch={'yes' if (is_429_error or is_fatal_error or is_retryable_error) else 'no'}")

    if is_429_error:
        if model_name:
            logger.info(f"Detected 429 error for model '{model_name}' with key '{old_key}'. Marking key for model-specific cooldown.")
            await key_manager.mark_key_model_as_cooling(old_key, model_name)
        else:
            logger.info(f"Detected 429 error with key '{old_key}'. Marking key as failed due to rate limit.")
            await key_manager.mark_key_as_failed(old_key)
        logger.info(f"Getting next working key for 429 error...")
        new_key = await key_manager.get_next_working_key(model_name=model_name)
        logger.info(f"429 error: got new_key={redact_key_for_logging(new_key)}")
    elif is_fatal_error:
        error_category = "auth" if is_auth_error else ("client" if is_client_error else "server")
        logger.warning(f"Detected fatal {error_category} error ({error_str.split(',')[0]}) for key '{old_key}'. Marking key as failed immediately.")
        await key_manager.mark_key_as_failed(old_key)
        new_key = await key_manager.get_next_working_key(model_name=model_name)
    elif is_retryable_error:
        if is_service_unavailable:
            logger.warning(f"Detected 503 Service Unavailable for key '{old_key}'. Switching key without penalty.")
        elif is_timeout_error:
            logger.warning(f"Detected 408 Request Timeout for key '{old_key}'. Switching key without penalty.")
        new_key = await key_manager.get_next_working_key(model_name=model_name)
    else:
        # For other errors, use the original failure counting logic
        new_key = await key_manager.handle_api_failure(
            old_key, retries, model_name=model_name
        )

    return new_key