"""角色资产总览 API。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.assets import RoleAssetOverviewResponse
from app.services.assets import RoleAssetService

router = APIRouter(prefix="/api/assets", tags=["角色资产总览"])


@router.get("/overview", response_model=RoleAssetOverviewResponse)
async def get_role_asset_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = RoleAssetService(db)
    return await service.get_overview(user_id=current_user.id)
