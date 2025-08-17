"""
定时任务控制路由模块
"""

from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.security import verify_auth_token
from app.scheduler.scheduled_tasks import start_scheduler, stop_scheduler
from app.log.logger import get_scheduler_routes

logger = get_scheduler_routes()

router = APIRouter(
    prefix="/api/scheduler",
    tags=["Scheduler"]
)

async def verify_token(request: Request):
    auth_token = request.cookies.get("auth_token")
    if not auth_token or not verify_auth_token(auth_token):
        logger.warning("Unauthorized access attempt to scheduler API")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

@router.post("/start", summary="启动定时任务")
async def start_scheduler_endpoint(request: Request):
    """Start the background scheduler task"""
    await verify_token(request)
    try:
        logger.info("Received request to start scheduler.")
        start_scheduler()
        return JSONResponse(content={"message": "Scheduler started successfully."}, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error starting scheduler: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start scheduler: {str(e)}"
        )

@router.post("/stop", summary="停止定时任务")
async def stop_scheduler_endpoint(request: Request):
    """Stop the background scheduler task"""
    await verify_token(request)
    try:
        logger.info("Received request to stop scheduler.")
        stop_scheduler()
        return JSONResponse(content={"message": "Scheduler stopped successfully."}, status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error stopping scheduler: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop scheduler: {str(e)}"
        )
