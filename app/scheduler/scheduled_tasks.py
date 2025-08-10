
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config.config import settings
from app.log.logger import Logger
from app.service.error_log.error_log_service import delete_old_error_logs
from app.service.key.key_manager import get_key_manager_instance
from app.service.request_log.request_log_service import delete_old_request_logs_task
from app.service.files.files_service import get_files_service

logger = Logger.setup_logger("scheduler")


# 原有的定时检查失败密钥功能已禁用
# 现在使用ValidKeyPool的定期维护机制来管理密钥有效性，避免浪费API调用次数
#
# async def check_failed_keys():
#     """
#     定时检查失败次数大于0的API密钥，并尝试验证它们。
#     如果验证成功，重置失败计数；如果失败，增加失败计数。
#
#     注意：此功能已禁用，因为ValidKeyPool提供了更高效的密钥管理机制
#     """
#     pass


# 原有的批量密钥验证功能已禁用
# 现在使用ValidKeyPool的定期维护机制，更高效且避免浪费API调用次数
#
# async def staggered_key_verification(keys_to_check: list, key_manager, chat_service):
#     """
#     批量错峰检测密钥，将密钥分批验证，批次间有间隔时间
#     动态读取当前配置的检测间隔
#
#     注意：此功能已禁用，因为ValidKeyPool提供了更高效的密钥管理机制
#     """
#     pass
#
# async def verify_single_key(key: str, key_manager, chat_service, key_index: int, total_keys: int):
#     """
#     验证单个密钥
#
#     注意：此功能已禁用，因为ValidKeyPool提供了更高效的密钥管理机制
#     """
#     pass


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
    # 原有的检查失败密钥的定时任务已移除
    # 现在使用ValidKeyPool的定期维护机制来管理密钥有效性
    logger.info("Legacy key check job disabled - using ValidKeyPool maintenance instead")

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
