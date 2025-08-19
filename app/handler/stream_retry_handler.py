# -*- coding: utf-8 -*-
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Set

import httpx

# --- Constants ---
NON_RETRYABLE_STATUSES: Set[int] = {400, 401, 403, 404, 429}
FINAL_PUNCTUATION: Set[str] = {'.', '?', '!', '。', '？', '！', '}', ']', ')', '"', "'", '”', '’', '`', '\n'}
SSE_ENCODER = str.encode

# --- Logging Setup ---
logger = logging.getLogger(__name__)


# --- Helper Functions ---

async def sse_line_iterator(response: httpx.Response) -> AsyncGenerator[str, None]:
    """Yields lines from an SSE stream."""
    buffer = ""
    line_count = 0
    logger.debug("Starting SSE line iteration")
    async for chunk in response.aiter_bytes():
        buffer += chunk.decode("utf-8")
        lines = buffer.splitlines()
        buffer = lines.pop() if lines and not buffer.endswith(('\n', '\r')) else ""
        for line in lines:
            if line.strip():
                line_count += 1
                logger.debug(f"SSE Line {line_count}: {line[:200]}")
                yield line
    if buffer.strip():
        logger.debug(f"SSE stream ended. Yielding final buffer: \"{buffer.strip()}\"")
        yield buffer.strip()
    logger.debug(f"SSE stream ended. Total lines processed: {line_count}.")


def is_data_line(line: str) -> bool:
    return line.startswith("data: ")

def is_blocked_line(line: str) -> bool:
    return "blockReason" in line

def extract_finish_reason(line: str) -> str | None:
    """Extracts finishReason from a data line."""
    if "finishReason" not in line:
        return None
    try:
        i = line.find("{")
        if i == -1:
            return None
        data = json.loads(line[i:])
        fr = data.get("candidates", [{}])[0].get("finishReason")
        if fr:
            logger.debug(f"Extracted finishReason: {fr}")
        return fr
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logger.debug(f"Failed to extract finishReason from line: {e}")
        return None

def parse_line_content(line: str) -> Dict[str, Any]:
    """Parses text and thought status from a data line."""
    try:
        json_str = line[line.find('{'):]
        data = json.loads(json_str)
        part = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0]
        if not part:
            return {"text": "", "is_thought": False}

        text = part.get("text", "")
        is_thought = part.get("thought") is True

        if is_thought:
            logger.debug("Extracted thought chunk. This will be tracked.")
        elif text:
            logger.debug(f"Extracted text chunk ({len(text)} chars): {text[:100]}")

        return {"text": text, "is_thought": is_thought}
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logger.debug(f"Failed to parse content from data line: {e}")
        return {"text": "", "is_thought": False}

def build_retry_request_body(original_body: Dict, accumulated_text: str) -> Dict:
    """Constructs a new request body for a retry attempt."""
    logger.debug(f"Building retry request body. Accumulated text length: {len(accumulated_text)}")
    logger.debug(f"Accumulated text preview: {accumulated_text[:200]}")
    
    retry_body = json.loads(json.dumps(original_body))
    if "contents" not in retry_body:
        retry_body["contents"] = []
    
    last_user_index = -1
    for i in range(len(retry_body["contents"]) - 1, -1, -1):
        if retry_body["contents"][i].get("role") == "user":
            last_user_index = i
            break
            
    history = [
        {"role": "model", "parts": [{"text": accumulated_text}]},
        {"role": "user", "parts": [{"text": "Continue exactly where you left off without any preamble or repetition."}]}
    ]
    
    if last_user_index != -1:
        retry_body["contents"][last_user_index + 1:last_user_index + 1] = history
        logger.debug(f"Inserted retry context after user message at index {last_user_index}")
    else:
        retry_body["contents"].extend(history)
        logger.debug("Appended retry context to end of conversation")
        
    logger.debug(f"Final retry request has {len(retry_body['contents'])} messages")
    return retry_body


async def process_stream_and_retry_internally(
    initial_response: httpx.Response,
    original_request_body: Dict,
    api_client: Any, # GeminiApiClient
    model: str,
    api_key: str,
    key_manager: Any, # KeyManager
    max_retries: int,
    retry_delay_ms: int,
    swallow_thoughts: bool,
) -> AsyncGenerator[bytes, None]:
    """The core logic for processing and retrying the SSE stream."""
    accumulated_text = ""
    consecutive_retry_count = 0
    current_response = initial_response
    total_lines_processed = 0
    session_start_time = datetime.now()
    
    is_outputting_formal_text = False
    swallow_mode_active = False

    logger.info(f"Starting stream processing session. Max retries: {max_retries}")

    while True:
        interruption_reason = None
        clean_exit = False
        stream_start_time = datetime.now()
        lines_in_this_stream = 0
        text_in_this_stream = ""

        logger.debug(f"=== Starting stream attempt {consecutive_retry_count + 1}/{max_retries + 1} ===")
        
        try:
            async for line in sse_line_iterator(current_response):
                total_lines_processed += 1
                lines_in_this_stream += 1

                line_content = parse_line_content(line) if is_data_line(line) else {"text": "", "is_thought": False}
                text_chunk, is_thought = line_content["text"], line_content["is_thought"]

                if swallow_mode_active:
                    if is_thought:
                        logger.debug(f"Swallowing thought chunk due to post-retry filter: {line}")
                        finish_reason_on_swallowed_line = extract_finish_reason(line)
                        if finish_reason_on_swallowed_line:
                            logger.error(f"Stream stopped with reason '{finish_reason_on_swallowed_line}' while swallowing a 'thought' chunk. Triggering retry.")
                            interruption_reason = "FINISH_DURING_THOUGHT"
                            break
                        continue
                    else:
                        logger.info("First formal text chunk received after swallowing. Resuming normal stream.")
                        swallow_mode_active = False

                finish_reason = extract_finish_reason(line)
                needs_retry = False
                
                if finish_reason and is_thought:
                    logger.error(f"Stream stopped with reason '{finish_reason}' on a 'thought' chunk. Triggering retry.")
                    interruption_reason = "FINISH_DURING_THOUGHT"
                    needs_retry = True
                elif is_blocked_line(line):
                    logger.error(f"Content blocked detected in line: {line}")
                    interruption_reason = "BLOCK"
                    needs_retry = True
                elif finish_reason == "STOP":
                    temp_accumulated_text = accumulated_text + text_chunk
                    trimmed_text = temp_accumulated_text.strip()
                    last_char = trimmed_text[-1:]
                    if not (len(trimmed_text) == 0 or last_char in FINAL_PUNCTUATION):
                        logger.error(f"Finish reason 'STOP' treated as incomplete because text ends with '{last_char}'. Triggering retry.")
                        interruption_reason = "FINISH_INCOMPLETE"
                        needs_retry = True
                elif finish_reason and finish_reason not in ("MAX_TOKENS", "STOP"):
                    logger.error(f"Abnormal finish reason: {finish_reason}. Triggering retry.")
                    interruption_reason = "FINISH_ABNORMAL"
                    needs_retry = True

                if needs_retry:
                    break
                
                yield SSE_ENCODER(line + "\n\n")

                if text_chunk and not is_thought:
                    is_outputting_formal_text = True
                    accumulated_text += text_chunk
                    text_in_this_stream += text_chunk

                if finish_reason in ("STOP", "MAX_TOKENS"):
                    logger.info(f"Finish reason '{finish_reason}' accepted as final. Stream complete.")
                    clean_exit = True
                    break
            
            if not clean_exit and interruption_reason is None:
                logger.error("Stream ended without finish reason - detected as DROP")
                interruption_reason = "DROP"

        except httpx.RequestError as e:
            logger.error(f"Exception during stream processing: {e}", exc_info=True)
            interruption_reason = "FETCH_ERROR"
        finally:
            if not current_response.is_closed:
                await current_response.aclose()
            
            stream_duration = (datetime.now() - stream_start_time).total_seconds()
            logger.debug("Stream attempt summary:")
            logger.debug(f"  Duration: {stream_duration:.2f}s")
            logger.debug(f"  Lines processed: {lines_in_this_stream}")
            logger.debug(f"  Text generated this stream: {len(text_in_this_stream)} chars")
            logger.debug(f"  Total accumulated text: {len(accumulated_text)} chars")

        if clean_exit:
            session_duration = (datetime.now() - session_start_time).total_seconds()
            logger.info("=== STREAM COMPLETED SUCCESSFULLY ===")
            logger.info(f"Total session duration: {session_duration:.2f}s")
            logger.info(f"Total lines processed: {total_lines_processed}")
            logger.info(f"Total text generated: {len(accumulated_text)} characters")
            logger.info(f"Total retries needed: {consecutive_retry_count}")
            return

        logger.error(f"=== STREAM INTERRUPTED ===\nReason: {interruption_reason}")
        
        if swallow_thoughts and is_outputting_formal_text:
            logger.info("Retry triggered after formal text output. Will swallow subsequent thought chunks.")
            swallow_mode_active = True

        logger.error(f"Current retry count: {consecutive_retry_count}, Max: {max_retries}")

        if consecutive_retry_count >= max_retries:
            payload = { "error": { "code": 504, "status": "DEADLINE_EXCEEDED", "message": f"Retry limit ({max_retries}) exceeded. Last reason: {interruption_reason}.", "details": [{"@type": "proxy.debug", "accumulated_text_chars": len(accumulated_text)}] } }
            yield SSE_ENCODER(f"event: error\ndata: {json.dumps(payload)}\n\n")
            return

        consecutive_retry_count += 1
        logger.info(f"=== STARTING RETRY {consecutive_retry_count}/{max_retries} ===")

        try:
            retry_body = build_retry_request_body(original_request_body, accumulated_text)
            
            # Here we need to integrate with our existing KeyManager
            # Mark the current key as failed for this model before getting a new one
            await key_manager.mark_key_model_as_cooling(api_key, model)
            api_key = await key_manager.get_next_working_key(model_name=model)
            if not api_key:
                logger.error("No more valid keys available. Aborting retry.")
                return

            logger.debug(f"Making retry request with key: ...{api_key[-4:]}")

            retry_response = await api_client.stream_generate_content(retry_body, model, api_key)
            
            logger.info(f"Retry request completed.")

            logger.info(f"✓ Retry attempt {consecutive_retry_count} successful - got new stream")
            current_response = retry_response
        
        except Exception as e:
            logger.error(f"Retry attempt {consecutive_retry_count} failed: {e}")
            if 'retry_response' in locals() and hasattr(retry_response, 'aclose'):
                await retry_response.aclose()
            await asyncio.sleep(retry_delay_ms / 1000)