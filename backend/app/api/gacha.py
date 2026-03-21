"""抽卡记录 API"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.gacha import (
    GachaAccountListResponse,
    GachaExportResponse,
    GachaImportFromAccountRequest,
    GachaImportRequest,
    GachaImportResponse,
    GachaImportUIGFRequest,
    GachaRecordListResponse,
    GachaResetResponse,
    GachaSummaryResponse,
)
from app.services.gacha import GachaService

router = APIRouter(prefix="/api/gacha", tags=["抽卡记录"])


@router.get("/accounts", response_model=GachaAccountListResponse)
async def get_gacha_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    return await service.list_supported_accounts(current_user.id)


@router.post("/import", response_model=GachaImportResponse)
async def import_gacha_records(
    data: GachaImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    account = await service.get_owned_account_for_game(data.account_id, current_user.id, data.game, data.game_uid)
    return await service.import_records(
        account=account,
        game=data.game,
        game_uid=data.game_uid,
        import_url=data.import_url,
    )


@router.post("/import-from-account", response_model=GachaImportResponse)
async def import_gacha_records_from_account(
    data: GachaImportFromAccountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    account = await service.get_owned_account_for_game(data.account_id, current_user.id, data.game, data.game_uid)
    return await service.import_records_from_account(account=account, game=data.game, game_uid=data.game_uid)


@router.post("/import-uigf", response_model=GachaImportResponse)
# `/import-json` 只保留为历史兼容别名。
# 正式语义已经切到 UIGF；若后续有人只改别名不改正式路由，很容易让前端/文档再次分叉。
@router.post("/import-json", response_model=GachaImportResponse)
async def import_gacha_records_from_uigf(
    data: GachaImportUIGFRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    account = await service.get_owned_account_for_game(data.account_id, current_user.id, data.game, data.game_uid)
    return await service.import_records_from_uigf(account=account, game=data.game, request=data)


@router.get("/summary", response_model=GachaSummaryResponse)
async def get_gacha_summary(
    account_id: int = Query(..., ge=1),
    # 这里故意保留为 `str`，不在路由层用枚举提前做 422 校验。
    # 所有入口统一下沉到 service 层做同一套 400 业务错误，才能让 HTTP 与内部调用的语义一致。
    game: str = Query(...),
    game_uid: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    await service.get_owned_account_for_game(account_id, current_user.id, game, game_uid)
    return await service.get_summary(account_id=account_id, game=game, game_uid=game_uid)


@router.get("/records", response_model=GachaRecordListResponse)
async def get_gacha_records(
    account_id: int = Query(..., ge=1),
    game: str = Query(...),
    game_uid: str = Query(..., min_length=1),
    pool_type: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    await service.get_owned_account_for_game(account_id, current_user.id, game, game_uid)
    return await service.list_records(
        account_id=account_id,
        game=game,
        game_uid=game_uid,
        pool_type=pool_type,
        page=page,
        page_size=page_size,
    )


@router.get("/export-uigf", response_model=GachaExportResponse)
# `/export` 只保留为历史兼容别名，正式导出命名以 UIGF 为准。
# 这样后续排障时只要看到路由名，就能知道返回体是标准 UIGF，而不是旧的私有 JSON 协议。
@router.get("/export", response_model=GachaExportResponse)
async def export_gacha_records_uigf(
    account_id: int = Query(..., ge=1),
    game: str = Query(...),
    game_uid: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    await service.get_owned_account_for_game(account_id, current_user.id, game, game_uid)
    return await service.export_records(account_id=account_id, game=game, game_uid=game_uid)


@router.delete("/reset", response_model=GachaResetResponse)
async def reset_gacha_records(
    account_id: int = Query(..., ge=1),
    game: str = Query(...),
    game_uid: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    await service.get_owned_account_for_game(account_id, current_user.id, game, game_uid)
    return await service.reset_records(account_id=account_id, game=game, game_uid=game_uid)
