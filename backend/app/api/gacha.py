"""抽卡记录 API"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.gacha import (
    GachaAccountListResponse,
    GachaExportResponse,
    GachaImportJsonRequest,
    GachaImportRequest,
    GachaImportResponse,
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
    account = await service.get_owned_account(data.account_id, current_user.id)
    return await service.import_records(account=account, game=data.game, import_url=data.import_url)


@router.post("/import-json", response_model=GachaImportResponse)
async def import_gacha_records_from_json(
    data: GachaImportJsonRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    account = await service.get_owned_account(data.account_id, current_user.id)
    return await service.import_records_from_json(account=account, game=data.game, request=data)


@router.get("/summary", response_model=GachaSummaryResponse)
async def get_gacha_summary(
    account_id: int = Query(..., ge=1),
    game: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    await service.get_owned_account(account_id, current_user.id)
    return await service.get_summary(account_id=account_id, game=game)


@router.get("/records", response_model=GachaRecordListResponse)
async def get_gacha_records(
    account_id: int = Query(..., ge=1),
    game: str = Query(...),
    pool_type: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    await service.get_owned_account(account_id, current_user.id)
    return await service.list_records(
        account_id=account_id,
        game=game,
        pool_type=pool_type,
        page=page,
        page_size=page_size,
    )


@router.get("/export", response_model=GachaExportResponse)
async def export_gacha_records(
    account_id: int = Query(..., ge=1),
    game: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    await service.get_owned_account(account_id, current_user.id)
    return await service.export_records(account_id=account_id, game=game)


@router.delete("/reset", response_model=GachaResetResponse)
async def reset_gacha_records(
    account_id: int = Query(..., ge=1),
    game: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = GachaService(db)
    await service.get_owned_account(account_id, current_user.id)
    return await service.reset_records(account_id=account_id, game=game)
