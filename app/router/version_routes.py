from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.service.update.update_service import check_for_updates
from app.utils.helpers import get_current_version
from app.log.logger import get_update_logger

router = APIRouter(prefix="/api/version", tags=["Version"])
logger = get_update_logger()

class VersionInfo(BaseModel):
    current_version: str = Field(..., description="当前应用程序版本")
    latest_version: Optional[str] = Field(None, description="可用的最新版本")
    update_available: bool = Field(False, description="是否有可用更新")
    error_message: Optional[str] = Field(None, description="检查更新时发生的错误信息")

@router.get("/check", response_model=VersionInfo, summary="检查应用程序更新")
async def get_version_info():
    """
    检查当前应用程序版本与最新的 GitHub release 版本。
    """
    try:
        current_version = get_current_version()
        update_available, latest_version, error_message = await check_for_updates()

        logger.debug(f"Version check API result: current={current_version}, latest={latest_version}, available={update_available}, error='{error_message}'")

        return VersionInfo(
            current_version=current_version,
            latest_version=latest_version,
            update_available=update_available,
            error_message=error_message
        )
    except Exception as e:
        logger.error(f"Error in /api/version/check endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="检查版本信息时发生内部错误")