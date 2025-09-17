"""
Service for request log operations.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete

from app.config.config import settings
from app.database.connection import database
from app.database.models import RequestLog
from app.log.logger import get_request_log_logger

logger = get_request_log_logger()


async def delete_old_request_logs_task():
    """
    定时删除旧的请求日志。
    """
    if not settings.AUTO_DELETE_REQUEST_LOGS_ENABLED:
        logger.info(
            "Auto-delete for request logs is disabled by settings. Skipping task."
        )
        return

    days_to_keep = settings.AUTO_DELETE_REQUEST_LOGS_DAYS
    logger.info(
        f"Starting scheduled task to delete old request logs older than {days_to_keep} days."
    )

    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)

        query = delete(RequestLog).where(RequestLog.request_time < cutoff_date)

        if not database.is_connected:
            logger.info("Connecting to database for request log deletion.")
            await database.connect()

        result = await database.execute(query)
        logger.info(
            f"Request logs older than {cutoff_date} potentially deleted. Rows affected: {result.rowcount if result else 'N/A'}"
        )

    except Exception as e:
        logger.error(
            f"An error occurred during the scheduled request log deletion: {str(e)}",
            exc_info=True,
        )
