
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import pytz

from app.config.config import settings
from app.domain.gemini_models import GeminiContent, GeminiRequest
from app.handler.error_processor import handle_api_error_and_get_next_key
from app.log.logger import Logger
from app.service.chat.gemini_chat_service import GeminiChatService
from app.service.error_log.error_log_service import delete_old_error_logs
from app.service.key.key_manager import get_key_manager_instance
from app.service.request_log.request_log_service import delete_old_request_logs_task
from app.service.files.files_service import get_files_service
from app.utils.helpers import redact_key_for_logging

logger = Logger.setup_logger("scheduler")


async def check_failed_keys():
    """
    定时检查失败次数大于0的API密钥，并尝试验证它们。
    如果验证成功，重置失败计数；如果失败，增加失败计数。
    """
    logger.info("Starting scheduled check for failed API keys...")
    try:
        key_manager = await get_key_manager_instance()
        # 确保 KeyManager 已经初始化
        if not key_manager or not hasattr(key_manager, "key_failure_counts"):
            logger.warning(
                "KeyManager instance not available or not initialized. Skipping check."
            )
            return

        # 创建 GeminiChatService 实例用于验证
        # 注意：这里直接创建实例，而不是通过依赖注入，因为这是后台任务
        chat_service = GeminiChatService(settings.BASE_URL, key_manager)

        # 获取需要检查的 key 列表 - 智能筛选逻辑
        keys_to_check = []
        keys_skipped_failed = 0
        keys_skipped_cooling = 0

        # 遍历所有密钥进行筛选
        for key in key_manager.api_keys:
            # 1. 使用标准方法检查密钥是否已失效 (包括403等直接失效的情况)
            if not await key_manager.is_key_valid(key):
                keys_skipped_failed += 1
                continue

            # 2. 检查是否在429冷却期内 (针对测试模型)
            model_statuses = key_manager.key_model_status.get(key, {})
            test_model_expiry = model_statuses.get(settings.TEST_MODEL)

            if test_model_expiry:
                now = datetime.now(pytz.utc)
                if now < test_model_expiry:
                    keys_skipped_cooling += 1
                    logger.debug(f"Skipping key {redact_key_for_logging(key)} - in cooldown for {settings.TEST_MODEL} until {test_model_expiry}")
                    continue

            # 3. 所有其他密钥都需要检测 (包括失败次数为0的正常密钥)
            keys_to_check.append(key)

        # 输出详细的检测统计信息
        total_keys = len(key_manager.api_keys)
        logger.info(f"Key verification summary:")
        logger.info(f"  Total keys: {total_keys}")
        logger.info(f"  Keys to check: {len(keys_to_check)}")
        logger.info(f"  Skipped (failed): {keys_skipped_failed}")
        logger.info(f"  Skipped (cooling): {keys_skipped_cooling}")

        if not keys_to_check:
            logger.info("No keys need verification. All keys are either failed or in cooldown.")
            return

        # 错峰检测密钥
        await staggered_key_verification(keys_to_check, key_manager, chat_service)

    except Exception as e:
        logger.error(
            f"An error occurred during the scheduled key check: {str(e)}", exc_info=True
        )


async def staggered_key_verification(keys_to_check: list, key_manager, chat_service):
    """
    批量错峰检测密钥，将密钥分批验证，批次间有间隔时间
    动态读取当前配置的检测间隔
    """
    total_keys = len(keys_to_check)
    if total_keys == 0:
        return

    # 动态读取当前配置的检测间隔（转换为秒）
    from app.config.config import settings
    current_interval_hours = settings.CHECK_INTERVAL_HOURS
    interval_seconds = current_interval_hours * 3600

    # 批量验证配置
    batch_size = getattr(settings, 'KEY_VERIFICATION_BATCH_SIZE', 20)  # 每批验证的密钥数量，默认20个
    total_batches = (total_keys + batch_size - 1) // batch_size  # 向上取整

    # 计算批次间的间隔时间
    batch_interval = interval_seconds // total_batches if total_batches > 1 else 0

    logger.info(
        f"Starting batch key verification: {total_keys} keys, "
        f"current interval: {current_interval_hours}h, "
        f"batch size: {batch_size}, total batches: {total_batches}, "
        f"batch interval: {batch_interval}s"
    )

    # 分批验证密钥
    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, total_keys)
        current_batch = keys_to_check[start_idx:end_idx]

        logger.info(f"Processing batch {batch_num + 1}/{total_batches} ({len(current_batch)} keys)...")

        # 并发验证当前批次的所有密钥
        batch_tasks = []
        for key in current_batch:
            task = verify_single_key(key, key_manager, chat_service, start_idx + current_batch.index(key) + 1, total_keys)
            batch_tasks.append(task)

        # 等待当前批次的所有验证完成
        await asyncio.gather(*batch_tasks, return_exceptions=True)

        # 如果不是最后一批，等待批次间隔时间
        if batch_num < total_batches - 1 and batch_interval > 0:
            logger.info(f"Batch {batch_num + 1} completed. Waiting {batch_interval}s before next batch...")
            await asyncio.sleep(batch_interval)
        else:
            logger.info(f"All {total_batches} batches completed.")


async def verify_single_key(key: str, key_manager, chat_service, key_index: int, total_keys: int):
    """
    验证单个密钥
    """
    log_key = redact_key_for_logging(key)
    logger.info(f"Verifying key: {log_key} ({key_index}/{total_keys})...")

    try:
        # 构造测试请求
        gemini_request = GeminiRequest(
            contents=[
                GeminiContent(
                    role="user",
                    parts=[{"text": "hi"}],
                )
            ]
        )
        await chat_service.generate_content(
            settings.TEST_MODEL, gemini_request, key
        )
        logger.info(
            f"Key {log_key} verification successful ({key_index}/{total_keys}). Resetting failure count."
        )
        await key_manager.reset_key_failure_count(key)
    except Exception as e:
        logger.warning(f"Key {log_key} verification failed ({key_index}/{total_keys}): {str(e)}.")
        # 调用通用错误处理器
        await handle_api_error_and_get_next_key(
            key_manager=key_manager,
            error=e,
            old_key=key,
            model_name=settings.TEST_MODEL,
            # 在定时任务中，我们不进行重试，所以retries可以设为一个较大的值
            # 或者在handle_api_error_and_get_next_key中增加一个参数来区分调用场景
            retries=key_manager.MAX_FAILURES
        )


async def cleanup_expired_files():
    """
    定时清理过期的文件记录
    """
    logger.info("Starting scheduled cleanup for expired files...")
    try:
        files_service = await get_files_service()
        deleted_count = await files_service.cleanup_expired_files()

        if deleted_count > 0:
            logger.info(f"Successfully cleaned up {deleted_count} expired files.")
        else:
            logger.info("No expired files to clean up.")

    except Exception as e:
        logger.error(
            f"An error occurred during the scheduled file cleanup: {str(e)}", exc_info=True
        )


async def maintain_valid_key_pool():
    """
    定期维护有效密钥池
    清理过期密钥、检查池大小、主动补充密钥等
    """
    logger.info("Starting scheduled maintenance for valid key pool...")
    try:
        key_manager = await get_key_manager_instance()

        if not key_manager:
            logger.warning("KeyManager not available for pool maintenance")
            return

        if not key_manager.valid_key_pool:
            logger.debug("ValidKeyPool not enabled, skipping maintenance")
            return

        # 执行池维护操作
        await key_manager.valid_key_pool.maintenance()

        # 获取维护后的统计信息
        stats = key_manager.valid_key_pool.get_pool_stats()
        logger.info(
            f"Valid key pool maintenance completed. "
            f"Pool size: {stats['current_size']}/{stats['pool_size']}, "
            f"Hit rate: {stats['hit_rate']:.2%}, "
            f"Avg key age: {stats['avg_key_age_seconds']}s"
        )

    except Exception as e:
        logger.error(
            f"An error occurred during valid key pool maintenance: {str(e)}", exc_info=True
        )


def setup_scheduler():
    """设置并启动 APScheduler"""
    scheduler = AsyncIOScheduler(timezone=str(settings.TIMEZONE))  # 从配置读取时区
    # 添加检查失败密钥的定时任务
    scheduler.add_job(
        check_failed_keys,
        "interval",
        hours=settings.CHECK_INTERVAL_HOURS,
        id="check_failed_keys_job",
        name="Check Failed API Keys",
    )
    logger.info(
        f"Key check job scheduled to run every {settings.CHECK_INTERVAL_HOURS} hour(s)."
    )

    # 新增：添加自动删除错误日志的定时任务，每天凌晨3点执行
    scheduler.add_job(
        delete_old_error_logs,
        "cron",
        hour=3,
        minute=0,
        id="delete_old_error_logs_job",
        name="Delete Old Error Logs",
    )
    logger.info("Auto-delete error logs job scheduled to run daily at 3:00 AM.")

    # 新增：添加自动删除请求日志的定时任务，每天凌晨3点05分执行
    scheduler.add_job(
        delete_old_request_logs_task,
        "cron",
        hour=3,
        minute=5,
        id="delete_old_request_logs_job",
        name="Delete Old Request Logs",
    )
    logger.info(
        f"Auto-delete request logs job scheduled to run daily at 3:05 AM, if enabled and AUTO_DELETE_REQUEST_LOGS_DAYS is set to {settings.AUTO_DELETE_REQUEST_LOGS_DAYS} days."
    )
    
    # 新增：添加文件过期清理的定时任务，每小时执行一次
    if getattr(settings, 'FILES_CLEANUP_ENABLED', True):
        cleanup_interval = getattr(settings, 'FILES_CLEANUP_INTERVAL_HOURS', 1)
        scheduler.add_job(
            cleanup_expired_files,
            "interval",
            hours=cleanup_interval,
            id="cleanup_expired_files_job",
            name="Cleanup Expired Files",
        )
        logger.info(
            f"File cleanup job scheduled to run every {cleanup_interval} hour(s)."
        )

    # 新增：添加有效密钥池维护的定时任务
    if getattr(settings, 'VALID_KEY_POOL_ENABLED', False):
        maintenance_interval = int(getattr(settings, 'POOL_MAINTENANCE_INTERVAL_MINUTES', 30))
        scheduler.add_job(
            maintain_valid_key_pool,
            "interval",
            minutes=maintenance_interval,
            id="maintain_valid_key_pool_job",
            name="Maintain Valid Key Pool",
        )
        logger.info(
            f"Valid key pool maintenance job scheduled to run every {maintenance_interval} minute(s)."
        )

    scheduler.start()
    logger.info("Scheduler started with all jobs.")
    return scheduler


# 可以在这里添加一个全局的 scheduler 实例，以便在应用关闭时优雅地停止
scheduler_instance = None


def start_scheduler():
    global scheduler_instance
    if scheduler_instance is None or not scheduler_instance.running:
        logger.info("Starting scheduler...")
        scheduler_instance = setup_scheduler()
    logger.info("Scheduler is already running.")


def stop_scheduler():
    global scheduler_instance
    if scheduler_instance and scheduler_instance.running:
        scheduler_instance.shutdown()
        logger.info("Scheduler stopped.")
