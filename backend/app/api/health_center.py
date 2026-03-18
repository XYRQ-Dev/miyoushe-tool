"""账号健康中心 API。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.health_center import HealthCenterOverviewResponse
from app.services.health_center import HealthCenterService

router = APIRouter(prefix="/api/health-center", tags=["账号健康中心"])


@router.get("/overview", response_model=HealthCenterOverviewResponse)
async def get_health_center_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = HealthCenterService(db)
    return await service.get_overview(user_id=current_user.id)
