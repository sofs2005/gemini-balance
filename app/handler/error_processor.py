import asyncio
from typing import Any, Dict, Optional
from fastapi import HTTPException
from app.service.key.key_manager import KeyManager
from app.service.model.model_service import ModelService
from app.database.services import add_error_log
from app.utils.helpers import simplify_api_error_message

class ErrorProcessor:
    def __init__(self, key_manager: KeyManager, model_service: ModelService):
        self.key_manager = key_manager
        self.model_service = model_service

    async def process_error(
        self,
        key: str,
        exception: Exception,
        model_name: str = "unknown",
        request_msg: Optional[Dict[str, Any]] = None,
        status_code_override: Optional[int] = None
    ):
        # Import APIError here to avoid circular dependency at module level
        from app.exception.exceptions import APIError

        # 1. Determine error type and status code with more precision
        status_code = status_code_override if status_code_override is not None else getattr(exception, 'status_code', None)
        error_type = "UNKNOWN_ERROR"

        if isinstance(exception, APIError):
            # Use the specific error_code from our custom exceptions
            error_type = exception.error_code.upper()
        elif status_code:
            # Fallback for generic HTTPException
            if status_code == 429:
                error_type = "RATE_LIMIT"
            elif status_code in [401, 403]:
                error_type = "AUTH_ERROR"
            elif status_code >= 500:
                error_type = "SERVER_ERROR"
            else:
                error_type = f"HTTP_{status_code}"
        else:
            # For all other exceptions
            error_type = type(exception).__name__.upper()

        # 2. Log the error to the database
        error_message = str(exception)
        simplified_message = simplify_api_error_message(error_message)
        asyncio.create_task(add_error_log(
            gemini_key=key,
            model_name=model_name,
            error_log=simplified_message,
            error_type=error_type,
            error_code=status_code,
            request_msg=request_msg
        ))

        # 3. Handle the key state based on the determined status_code
        if status_code:
            if status_code == 429:
                await self.handle_rate_limit_error(key, model_name)
            elif status_code in [401, 403]:
                await self.handle_authentication_error(key)
            elif status_code >= 500:
                await self.handle_server_error(key)
        else:
            # For exceptions without a status code, treat as a server-side/unknown issue
            await self.handle_server_error(key)

    async def handle_rate_limit_error(self, key: str, model_name: str):
        # Mark the key as cooling for this specific model
        await self.key_manager.mark_key_model_as_cooling(key, model_name)
        # Also increment failure count as it's a form of failure
        await self.key_manager.increment_failure_count(key)
        # Remove the key from the active pool
        await self.key_manager.remove_key_from_pool(key)

    async def handle_authentication_error(self, key: str):
        # Mark the key as failed immediately, which also removes it from all pools
        await self.key_manager.mark_key_as_failed(key)

    async def handle_server_error(self, key: str):
        # Temporarily remove the key from the pool and increase the failure count
        await self.key_manager.increment_failure_count(key)
        await self.key_manager.remove_key_from_pool(key)