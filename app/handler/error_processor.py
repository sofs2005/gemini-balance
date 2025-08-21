from fastapi import HTTPException
from app.service.key.key_manager import KeyManager
from app.service.model.model_service import ModelService

class ErrorProcessor:
    def __init__(self, key_manager: KeyManager, model_service: ModelService):
        self.key_manager = key_manager
        self.model_service = model_service

    async def process_error(self, key, exception: Exception):
        if isinstance(exception, HTTPException):
            status_code = exception.status_code
            if status_code == 429:
                # Rate limit error
                await self.handle_rate_limit_error(key)
            elif status_code in [401, 403]:
                # Authentication error
                await self.handle_authentication_error(key)
            elif status_code >= 500:
                # Server error
                await self.handle_server_error(key)
        else:
            # Other exceptions
            await self.handle_server_error(key)

    async def handle_rate_limit_error(self, key):
        # Cool down the model
        model = await self.key_manager.get_model_from_key(key)
        if model:
            await self.model_service.cool_down_model(model)
        # Remove the key from the pool
        await self.key_manager.remove_key_from_pool(key)

    async def handle_authentication_error(self, key):
        # Disable the key permanently
        await self.key_manager.disable_key(key)

    async def handle_server_error(self, key):
        # Temporarily remove the key from the pool and increase the failure count
        await self.key_manager.increment_failure_count(key)
        await self.key_manager.remove_key_from_pool(key)