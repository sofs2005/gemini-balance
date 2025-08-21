# app/services/chat_service.py

import json
import re
import datetime
import time
from typing import Any, AsyncGenerator, Dict, List
from app.config.config import settings
from app.core.constants import GEMINI_2_FLASH_EXP_SAFETY_SETTINGS
from app.domain.gemini_models import GeminiRequest
from app.handler.response_handler import GeminiResponseHandler
from app.handler.retry_handler import RetryHandler
from app.handler.stream_optimizer import gemini_optimizer
from app.log.logger import get_gemini_logger
from app.service.client.api_client import GeminiApiClient
from app.service.key.key_manager import KeyManager
import asyncio
from app.database.services import add_error_log, add_request_log, get_file_api_key
from app.handler.stream_retry_handler import process_stream_and_retry_internally
from app.utils.helpers import redact_key_for_logging, simplify_api_error_message
from app.exception.exceptions import MaxRetriesExceededError

logger = get_gemini_logger()


def _has_image_parts(contents: List[Dict[str, Any]]) -> bool:
    """判断消息是否包含图片部分"""
    for content in contents:
        if "parts" in content:
            for part in content["parts"]:
                if "image_url" in part or "inline_data" in part:
                    return True
    return False

def _extract_file_references(contents: List[Dict[str, Any]]) -> List[str]:
    """從內容中提取文件引用"""
    file_names = []
    for content in contents:
        if "parts" in content:
            for part in content["parts"]:
                if not isinstance(part, dict) or "fileData" not in part:
                    continue
                file_data = part["fileData"]
                if "fileUri" not in file_data:
                    continue
                file_uri = file_data["fileUri"]
                # 從 URI 中提取文件名
                # 1. https://generativelanguage.googleapis.com/v1beta/files/{file_id}
                match = re.match(rf"{re.escape(settings.BASE_URL)}/(files/.*)", file_uri)
                if not match:
                    logger.warning(f"Invalid file URI: {file_uri}")
                    continue
                file_id = match.group(1)
                file_names.append(file_id)
                logger.info(f"Found file reference: {file_id}")
    return file_names

def _clean_json_schema_properties(obj: Any) -> Any:
    """清理JSON Schema中Gemini API不支持的字段"""
    if not isinstance(obj, dict):
        return obj
    
    # Gemini API不支持的JSON Schema字段
    unsupported_fields = {
        "exclusiveMaximum", "exclusiveMinimum", "const", "examples", 
        "contentEncoding", "contentMediaType", "if", "then", "else",
        "allOf", "anyOf", "oneOf", "not", "definitions", "$schema",
        "$id", "$ref", "$comment", "readOnly", "writeOnly"
    }
    
    cleaned = {}
    for key, value in obj.items():
        if key in unsupported_fields:
            continue
        if isinstance(value, dict):
            cleaned[key] = _clean_json_schema_properties(value)
        elif isinstance(value, list):
            cleaned[key] = [_clean_json_schema_properties(item) for item in value]
        else:
            cleaned[key] = value
    
    return cleaned


def _build_tools(model: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """构建工具"""
    
    def _has_function_call(contents: List[Dict[str, Any]]) -> bool:
        """检查内容中是否包含 functionCall"""
        if not contents or not isinstance(contents, list):
            return False
        for content in contents:
            if not content or not isinstance(content, dict) or "parts" not in content:
                continue
            parts = content.get("parts", [])
            if not parts or not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict) and "functionCall" in part:
                    return True
        return False
    
    def _merge_tools(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        record = dict()
        for item in tools:
            if not item or not isinstance(item, dict):
                continue

            for k, v in item.items():
                if k == "functionDeclarations" and v and isinstance(v, list):
                    functions = record.get("functionDeclarations", [])
                    # 清理每个函数声明中的不支持字段
                    cleaned_functions = []
                    for func in v:
                        if isinstance(func, dict):
                            cleaned_func = _clean_json_schema_properties(func)
                            cleaned_functions.append(cleaned_func)
                        else:
                            cleaned_functions.append(func)
                    functions.extend(cleaned_functions)
                    record["functionDeclarations"] = functions
                else:
                    record[k] = v
        return record

    def _is_structured_output_request(payload: Dict[str, Any]) -> bool:
        """检查请求是否要求结构化JSON输出"""
        try:
            generation_config = payload.get("generationConfig", {})
            return generation_config.get("responseMimeType") == "application/json"
        except (AttributeError, TypeError):
            return False

    tool = dict()
    if payload and isinstance(payload, dict) and "tools" in payload:
        if payload.get("tools") and isinstance(payload.get("tools"), dict):
            payload["tools"] = [payload.get("tools")]
        items = payload.get("tools", [])
        if items and isinstance(items, list):
            tool.update(_merge_tools(items))

    # "Tool use with a response mime type: 'application/json' is unsupported"
    # Gemini API限制：不支持同时使用tools和结构化输出(response_mime_type='application/json')
    # 当请求指定了JSON响应格式时，跳过所有工具的添加以避免API错误
    has_structured_output = _is_structured_output_request(payload)
    if not has_structured_output:
        if (
            settings.TOOLS_CODE_EXECUTION_ENABLED
            and not (model.endswith("-search") or "-thinking" in model)
            and not _has_image_parts(payload.get("contents", []))
        ):
            tool["codeExecution"] = {}
            
        if model.endswith("-search"):
            tool["googleSearch"] = {}
            
        real_model = _get_real_model(model)
        if real_model in settings.URL_CONTEXT_MODELS and settings.URL_CONTEXT_ENABLED:
            tool["urlContext"] = {}

    # 解决 "Tool use with function calling is unsupported" 问题
    if tool.get("functionDeclarations") or _has_function_call(payload.get("contents", [])):
        tool.pop("googleSearch", None)
        tool.pop("codeExecution", None)
        tool.pop("urlContext", None)

    return [tool] if tool else []


def _get_real_model(model: str) -> str:
    if model.endswith("-search"):
        model = model[:-7]
    if model.endswith("-image"):
        model = model[:-6]
    if model.endswith("-non-thinking"):
        model = model[:-13]
    if "-search" in model and "-non-thinking" in model:
        model = model[:-20]
    return model


def _get_safety_settings(model: str) -> List[Dict[str, str]]:
    """获取安全设置"""
    if model == "gemini-2.0-flash-exp":
        return GEMINI_2_FLASH_EXP_SAFETY_SETTINGS
    return settings.SAFETY_SETTINGS


def _filter_empty_parts(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filters out contents with empty or invalid parts."""
    if not contents:
        return []

    filtered_contents = []
    for content in contents:
        if not content or "parts" not in content or not isinstance(content.get("parts"), list):
            continue

        valid_parts = [part for part in content["parts"] if isinstance(part, dict) and part]

        if valid_parts:
            new_content = content.copy()
            new_content["parts"] = valid_parts
            filtered_contents.append(new_content)

    return filtered_contents


def _build_payload(model: str, request: GeminiRequest) -> Dict[str, Any]:
    """构建请求payload"""
    request_dict = request.model_dump(exclude_none=False)
    if request.generationConfig:
        if request.generationConfig.maxOutputTokens is None:
            # 如果未指定最大输出长度，则不传递该字段，解决截断的问题
            if "maxOutputTokens" in request_dict["generationConfig"]:
                request_dict["generationConfig"].pop("maxOutputTokens")

    # 检查是否为TTS模型
    is_tts_model = "tts" in model.lower()

    if is_tts_model:
        # TTS模型使用简化的payload，不包含tools和safetySettings
        payload = {
            "contents": _filter_empty_parts(request_dict.get("contents", [])),
            "generationConfig": request_dict.get("generationConfig"),
        }

        # 只在有systemInstruction时才添加
        if request_dict.get("systemInstruction"):
            payload["systemInstruction"] = request_dict.get("systemInstruction")
    else:
        # 非TTS模型使用完整的payload
        payload = {
            "contents": _filter_empty_parts(request_dict.get("contents", [])),
            "tools": _build_tools(model, request_dict),
            "safetySettings": _get_safety_settings(model),
            "generationConfig": request_dict.get("generationConfig"),
            "systemInstruction": request_dict.get("systemInstruction"),
        }

    # 确保 generationConfig 不为 None
    if payload["generationConfig"] is None:
        payload["generationConfig"] = {}

    if model.endswith("-image") or model.endswith("-image-generation"):
        payload.pop("systemInstruction")
        payload["generationConfig"]["responseModalities"] = ["Text", "Image"]
    
    # 处理思考配置：优先使用客户端提供的配置，否则使用默认配置
    client_thinking_config = None
    if request.generationConfig and request.generationConfig.thinkingConfig:
        client_thinking_config = request.generationConfig.thinkingConfig
    
    if client_thinking_config is not None:
        # 客户端提供了思考配置，直接使用
        payload["generationConfig"]["thinkingConfig"] = client_thinking_config
    else:
        # 客户端没有提供思考配置，使用默认配置    
        if model.endswith("-non-thinking"):
            if "gemini-2.5-pro" in model:
                payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 128}
            else:
                payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0} 
        elif _get_real_model(model) in settings.THINKING_BUDGET_MAP:
            if settings.SHOW_THINKING_PROCESS:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingBudget": settings.THINKING_BUDGET_MAP.get(model,1000),
                    "includeThoughts": True
                }
            else:
                payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": settings.THINKING_BUDGET_MAP.get(model,1000)}

    return payload


class GeminiChatService:
    """聊天服务"""

    def __init__(self, base_url: str, key_manager: KeyManager):
        self.api_client = GeminiApiClient(base_url, settings.TIME_OUT)
        self.key_manager = key_manager
        self.response_handler = GeminiResponseHandler()

    def _extract_text_from_response(self, response: Dict[str, Any]) -> str:
        """从响应中提取文本内容"""
        if not response.get("candidates"):
            return ""

        candidate = response["candidates"][0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        if parts and "text" in parts[0]:
            return parts[0].get("text", "")
        return ""

    def _create_char_response(
        self, original_response: Dict[str, Any], text: str
    ) -> Dict[str, Any]:
        """创建包含指定文本的响应"""
        response_copy = json.loads(json.dumps(original_response))
        if response_copy.get("candidates") and response_copy["candidates"][0].get(
            "content", {}
        ).get("parts"):
            response_copy["candidates"][0]["content"]["parts"][0]["text"] = text
        return response_copy

    async def _verify_key_with_api(self, key_to_verify: str) -> Exception | None:
        """
        A simplified, non-retrying method to verify a key directly.
        Returns None on success, or the exception on failure.
        """
        try:
            payload = _build_payload(
                settings.TEST_MODEL,
                GeminiRequest(contents=[GeminiContent(role="user", parts=[{"text": "hi"}])])
            )
            await self.api_client.generate_content(payload, settings.TEST_MODEL, key_to_verify)
            return None  # Success
        except Exception as e:
            return e  # Failure

    async def generate_content(
        self, model: str, request: GeminiRequest, api_key: str
    ) -> Dict[str, Any]:
        """生成内容"""
        import time
        import datetime

        # 记录开始时间和请求时间
        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None
        final_api_key = api_key

        retries = 0
        max_retries = settings.MAX_RETRIES

        try:
            # 檢查並獲取文件專用的 API key（如果有文件）
            file_names = _extract_file_references(request.model_dump().get("contents", []))
            if file_names:
                logger.info(f"Request contains file references: {file_names}")
                file_api_key = await get_file_api_key(file_names[0])
                if file_api_key:
                    logger.info(f"Found API key for file {file_names[0]}: {redact_key_for_logging(file_api_key)}")
                    api_key = file_api_key  # 使用文件的 API key
                else:
                    logger.warning(f"No API key found for file {file_names[0]}, using default key: {redact_key_for_logging(api_key)}")

            payload = _build_payload(model, request)

            while retries < max_retries:
                try:
                    final_api_key = api_key
                    response = await self.api_client.generate_content(payload, model, api_key)
                    is_success = True
                    status_code = 200
                    return self.response_handler.handle_response(response, model, stream=False)

                except Exception as e:
                    retries += 1
                    # 检查是否为已知HTTP错误，以决定是否打印完整堆栈
                    error_msg = str(e)
                    is_known_http_error = "API call failed with status code" in error_msg
                    
                    if is_known_http_error:
                        logger.error(f"Content generation attempt {retries} failed: {simplify_api_error_message(error_msg)}")
                    else:
                        logger.error(f"Content generation attempt {retries} failed.", exc_info=True)
                    
                    await self.key_manager.error_processor.process_error(api_key, e, model)
                    # 立即从所有池中移除失败的key，避免在同一轮重试中再次选中
                    await self.key_manager.remove_key(api_key)
                    new_key = await self.key_manager.get_next_working_key(model)

                    if not new_key or new_key == api_key:
                        logger.error("No new valid keys available. Aborting after multiple retries.")
                        raise e
                    
                    api_key = new_key
                    logger.info(f"Switched to new API key for retry: ...{api_key[-4:]}")

            logger.error(f"Max retries ({max_retries}) reached. Failing.")
            raise MaxRetriesExceededError(f"Max retries reached for model {model}. The service may be unstable.")

        except Exception as e:
            is_success = False
            error_log_msg = str(e)
            match = re.search(r"status code (\d+)", error_log_msg)
            if match:
                status_code = int(match.group(1))
            else:
                status_code = 500
            raise e
        finally:
            # 记录请求日志
            end_time = time.perf_counter()
            latency_ms = int((end_time - start_time) * 1000)
            asyncio.create_task(add_request_log(
                model_name=model,
                api_key=final_api_key,
                is_success=is_success,
                status_code=status_code,
                latency_ms=latency_ms,
                request_time=request_datetime
            ))

    async def count_tokens(
        self, model: str, request: GeminiRequest, api_key: str
    ) -> Dict[str, Any]:
        """计算token数量"""
        import time
        import datetime

        # 记录开始时间和请求时间
        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None
        final_api_key = api_key

        retries = 0
        max_retries = settings.MAX_RETRIES

        try:
            payload = {"contents": _filter_empty_parts(request.model_dump().get("contents", []))}
            
            while retries < max_retries:
                try:
                    final_api_key = api_key
                    response = await self.api_client.count_tokens(payload, model, api_key)
                    is_success = True
                    status_code = 200
                    return response

                except Exception as e:
                    retries += 1
                    error_msg = str(e)
                    logger.error(f"Count tokens attempt {retries} failed: {simplify_api_error_message(error_msg)}")
                    
                    await self.key_manager.error_processor.process_error(api_key, e, model)
                    new_key = await self.key_manager.get_next_working_key(model)

                    if not new_key or new_key == api_key:
                        logger.error("No new valid keys available for count_tokens. Aborting.")
                        raise e
                    
                    api_key = new_key
                    logger.info(f"Switched to new API key for count_tokens retry: ...{api_key[-4:]}")

            logger.error(f"Max retries ({max_retries}) reached for count_tokens. Failing.")
            raise MaxRetriesExceededError(f"Max retries reached for count_tokens on model {model}.")

        except Exception as e:
            is_success = False
            error_log_msg = str(e)
            match = re.search(r"status code (\d+)", error_log_msg)
            if match:
                status_code = int(match.group(1))
            else:
                status_code = 500
            raise e
        finally:
            # 记录请求日志
            end_time = time.perf_counter()
            latency_ms = int((end_time - start_time) * 1000)
            asyncio.create_task(add_request_log(
                model_name=f"{model}-count-tokens",
                api_key=final_api_key,
                is_success=is_success,
                status_code=status_code,
                latency_ms=latency_ms,
                request_time=request_datetime
            ))

    async def stream_generate_content(
        self, model: str, request: GeminiRequest, api_key: str
    ) -> AsyncGenerator[str, None]:
        """流式生成内容"""
        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None
        final_api_key = api_key
        
        try:
            # 檢查並獲取文件專用的 API key（如果有文件）
            file_names = _extract_file_references(request.model_dump().get("contents", []))
            if file_names:
                logger.info(f"Request contains file references: {file_names}")
                file_api_key = await get_file_api_key(file_names[0])
                if file_api_key:
                    logger.info(f"Found API key for file {file_names[0]}: {redact_key_for_logging(file_api_key)}")
                    api_key = file_api_key
                else:
                    logger.warning(f"No API key found for file {file_names[0]}, using default key: {redact_key_for_logging(api_key)}")

            payload = _build_payload(model, request)
            retries = 0
            max_retries = settings.MAX_RETRIES

            while retries < max_retries:
                try:
                    final_api_key = api_key
                    async for decoded_chunk in self.api_client.stream_generate_content(payload, model, api_key):
                        # Process with the original stream optimizer for better perceived performance
                        if decoded_chunk.startswith("data:"):
                            try:
                                line_data = decoded_chunk[6:]
                                response_data = self.response_handler.handle_response(
                                    json.loads(line_data), model, stream=True
                                )
                                text = self._extract_text_from_response(response_data)
                                
                                if text and settings.STREAM_OPTIMIZER_ENABLED:
                                    async for optimized_chunk in gemini_optimizer.optimize_stream_output(
                                        text,
                                        lambda t: self._create_char_response(response_data, t),
                                        lambda c: "data: " + json.dumps(c) + "\n\n",
                                    ):
                                        yield optimized_chunk
                                else:
                                    yield "data: " + json.dumps(response_data) + "\n\n"
                            except json.JSONDecodeError:
                                yield decoded_chunk # Yield original chunk if not valid JSON
                        else:
                            yield decoded_chunk
                    
                    is_success = True
                    status_code = 200
                    return

                except Exception as e:
                    retries += 1
                    error_msg = str(e)
                    is_known_http_error = "API call failed with status code" in error_msg
                    
                    if is_known_http_error:
                        logger.error(f"Stream attempt {retries} failed: {simplify_api_error_message(error_msg)}")
                        match = re.search(r"status code (\d+)", error_msg)
                        if match:
                            status_code = int(match.group(1))
                    else:
                        logger.error(f"Stream attempt {retries} failed.", exc_info=True)
                        status_code = 500
                    
                    await self.key_manager.error_processor.process_error(api_key, e, model)
                    await self.key_manager.remove_key(api_key)
                    new_key = await self.key_manager.get_next_working_key(model)

                    if not new_key or new_key == api_key:
                        logger.error("No new valid keys available. Aborting after multiple retries.")
                        raise e
                    
                    api_key = new_key
                    logger.info(f"Switched to new API key for retry: ...{api_key[-4:]}")

            # When max retries are reached, raise an exception to be caught by the outer try-except block
            # This ensures that is_success is correctly set to False for logging.
            raise MaxRetriesExceededError(f"Max retries reached for model {model}. The service may be unstable.")

        except Exception as e:
            is_success = False
            error_log_msg = str(e)
            match = re.search(r"status code (\d+)", error_log_msg)
            if match:
                status_code = int(match.group(1))
            else:
                status_code = 500
            # Log the final error and yield a message to the client without re-raising.
            # This prevents the "response already started" crash.
            final_error_message = f"Stream failed after multiple retries. Last error: {error_log_msg}"
            logger.error(final_error_message)
            
            error_payload = {
                "error": {
                    "code": status_code,
                    "message": simplify_api_error_message(str(e)),
                    "status": "INTERNAL_SERVER_ERROR"
                }
            }
            yield f"data: {json.dumps(error_payload)}\n\n"
        finally:
            end_time = time.perf_counter()
            latency_ms = int((end_time - start_time) * 1000)
            asyncio.create_task(add_request_log(
                model_name=f"{model}-stream",
                api_key=final_api_key,
                is_success=is_success,
                status_code=status_code,
                latency_ms=latency_ms,
                request_time=request_datetime
            ))
