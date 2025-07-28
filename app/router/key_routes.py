from fastapi import APIRouter, Depends, Request
from app.service.key.key_manager import KeyManager, get_key_manager_instance
from app.core.security import verify_auth_token
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/api/keys")
async def get_keys_paginated(
    request: Request,
    page: int = 1,
    limit: int = 10,
    search: str = None,
    fail_count_threshold: int = None,
    status: str = "all",  # 'valid', 'invalid', 'all'
    key_manager: KeyManager = Depends(get_key_manager_instance),
):
    """
    Get paginated, filtered, and searched keys.
    """
    auth_token = request.cookies.get("auth_token")
    if not auth_token or not verify_auth_token(auth_token):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    all_keys_with_status = await key_manager.get_all_keys_with_fail_count()

    # Filter by status
    if status == "valid":
        keys_to_filter = all_keys_with_status["valid_keys"]
    elif status == "invalid":
        keys_to_filter = all_keys_with_status["invalid_keys"]
    else:
        # Combine both for 'all' status, which might be useful for a unified view if ever needed
        keys_to_filter = {**all_keys_with_status["valid_keys"], **all_keys_with_status["invalid_keys"]}


    # Further filtering (search and fail_count_threshold)
    filtered_keys = {}
    for key, fail_count in keys_to_filter.items():
        search_match = True
        if search:
            search_match = search.lower() in key.lower()

        fail_count_match = True
        if fail_count_threshold is not None:
            fail_count_match = fail_count >= fail_count_threshold

        if search_match and fail_count_match:
            filtered_keys[key] = fail_count

    # Pagination
    keys_list = list(filtered_keys.items())
    total_items = len(keys_list)
    start_index = (page - 1) * limit
    end_index = start_index + limit
    paginated_keys = dict(keys_list[start_index:end_index])

    return {
        "keys": paginated_keys,
        "total_items": total_items,
        "total_pages": (total_items + limit - 1) // limit,
        "current_page": page,
    }

@router.get("/api/keys/all")
async def get_all_keys(
    request: Request,
    key_manager: KeyManager = Depends(get_key_manager_instance),
):
    """
    Get all keys (both valid and invalid) for bulk operations.
    """
    auth_token = request.cookies.get("auth_token")
    if not auth_token or not verify_auth_token(auth_token):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    all_keys_with_status = await key_manager.get_all_keys_with_fail_count()
    
    return {
        "valid_keys": list(all_keys_with_status["valid_keys"].keys()),
        "invalid_keys": list(all_keys_with_status["invalid_keys"].keys()),
        "total_count": len(all_keys_with_status["valid_keys"]) + len(all_keys_with_status["invalid_keys"])
    }
