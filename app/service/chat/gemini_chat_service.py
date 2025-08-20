import json
import re
import time
from typing import Any, AsyncGenerator, Dict, List

from app.config.config import settings
from app.domain.gemini_models import GeminiRequest
from app.handler.error_processor import (handle_api_error_and_get_next_key,
                                         log_api_error)
from app.handler.response_handler import GeminiResponseHandler
from app.handler.retry_handler import RetryHandler
from app.handler.stream_optimizer import gemini_stream_optimizer
from app.handler.stream_retry_handler import StreamRetryHandler
from app.service.client.api_client import GeminiAPIClient
from app.service.key.key_manager import key_manager
from app.service.request_log.request_log_service import RequestLogService
from app.utils.helpers import (convert_sse_to_json, generate_request_id,
                               get_proxy_url)
from app.utils.ttl_cache import ttl_cache


class GeminiChatService:
    def __init__(self, request_log_service: RequestLogService):
        self.request_log_service = request_log_service

    async def _create_chat_completion_stream(
            self,
            request: GeminiRequest,
            api_client: GeminiAPIClient,
            request_id: str,
            retry_handler: RetryHandler,
            response_handler: GeminiResponseHandler,
            stream_retry_handler: StreamRetryHandler,
    ) -> AsyncGenerator[str, Any]:
        last_chunk_time = time.time()
        is_first_chunk = True
        full_content = ""
        buffer = ""

        while True:
            try:
                async for chunk in api_client.stream_generate_content(request.model, request.to_dict()):
                    buffer += chunk
                    if is_first_chunk:
                        response_handler.set_request_id(request_id)
                        is_first_chunk = False

                    if buffer.endswith("\r\n\r\n"):
                        json_chunks = convert_sse_to_json(buffer)
                        buffer = ""
                        stream_retry_handler.add_chunks(json_chunks)
                        async for optimized_chunk in gemini_stream_optimizer(json_chunks):
                            yield optimized_chunk
                        last_chunk_time = time.time()

                if buffer:
                    json_chunks = convert_sse_to_json(buffer)
                    stream_retry_handler.add_chunks(json_chunks)
                    async for optimized_chunk in gemini_stream_optimizer(json_chunks):
                        yield optimized_chunk

                if settings.STREAM_RETRY_ENABLED and stream_retry_handler.is_stream_incomplete():
                    request.contents = stream_retry_handler.prepare_retry_request()
                    continue

                yield response_handler.create_done_chunk()
                break

            except Exception as e:
                next_key_info = await handle_api_error_and_get_next_key(e, api_client.api_key, request.model)
                if not next_key_info:
                    yield response_handler.create_error_chunk(f"All API keys are invalid. Please check your keys.")
                    break

                api_client.update_key(next_key_info["key"])
                retry_handler.record_attempt()
                if not await retry_handler.should_retry():
                    yield response_handler.create_error_chunk(f"Max retries reached. Last error: {e}")
                    break

    async def create_chat_completion(
            self, request: GeminiRequest
    ) -> AsyncGenerator[str, Any]:
        request_id = generate_request_id()
        start_time = time.time()
        api_key_info = key_manager.get_key(request.model)
        if not api_key_info:
            yield GeminiResponseHandler(request_id).create_error_chunk("No valid API key found for the specified model.")
            return

        api_key = api_key_info["key"]
        proxy_url = get_proxy_url(api_key)
        api_client = GeminiAPIClient(api_key, proxy_url=proxy_url)
        retry_handler = RetryHandler(
            max_retries=settings.MAX_RETRIES,
            delay=settings.RETRY_DELAY,
            backoff_factor=settings.RETRY_BACKOFF,
        )
        response_handler = GeminiResponseHandler(request_id)
        stream_retry_handler = StreamRetryHandler()

        try:
            if request.stream:
                async for chunk in self._create_chat_completion_stream(
                        request, api_client, request_id, retry_handler, response_handler, stream_retry_handler
                ):
                    yield chunk
                full_content = stream_retry_handler.get_full_content()
            else:
                response = await api_client.generate_content(request.model, request.to_dict())
                full_content = response_handler.extract_full_content_from_response(response)
                yield response_handler.create_regular_chunk(full_content)

        except Exception as e:
            log_api_error(e, api_key, request.model)
            yield response_handler.create_error_chunk(f"An unexpected error occurred: {e}")
        finally:
            end_time = time.time()
            duration = end_time - start_time
            await self.request_log_service.log_request(
                request_id=request_id,
                model_name=request.model,
                api_key=api_key,
                request_data=request.model_dump_json(),
                response_data=json.dumps({"full_content": full_content}),
                duration=duration,
                is_stream=request.stream,
            )
            key_manager.release_key(api_key)
