from app.log.logger import get_gemini_logger
from app.service.key.key_manager import KeyManager

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