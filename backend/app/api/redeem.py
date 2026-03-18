"""兑换码中心 API"""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.redeem import (
    RedeemAccountListResponse,
    RedeemBatchDetailResponse,
    RedeemBatchListResponse,
    RedeemExecuteRequest,
)
from app.services.redeem import RedeemService

router = APIRouter(prefix="/api/redeem", tags=["兑换码中心"])


@router.get("/accounts", response_model=RedeemAccountListResponse)
async def get_redeem_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = RedeemService(db)
    return await service.list_supported_accounts(current_user.id)


@router.post("/execute", response_model=RedeemBatchDetailResponse)
async def execute_redeem_batch(
    data: RedeemExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = RedeemService(db)
    return await service.execute_batch(user_id=current_user.id, request=data)


@router.get("/batches", response_model=RedeemBatchListResponse)
async def list_redeem_batches(
    game: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = RedeemService(db)
    return await service.list_batches(user_id=current_user.id, game=game)


@router.get("/batches/{batch_id}", response_model=RedeemBatchDetailResponse)
async def get_redeem_batch_detail(
    batch_id: int = Path(..., ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = RedeemService(db)
    return await service.get_batch_detail(user_id=current_user.id, batch_id=batch_id)
