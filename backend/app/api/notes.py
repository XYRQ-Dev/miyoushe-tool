"""实时便笺 API"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.notes import NoteAccountListResponse, NoteSummaryResponse
from app.services.notes import NoteService
from app.services.system_settings import SystemSettingsService

router = APIRouter(prefix="/api/notes", tags=["实时便笺"])
NOTES_MENU_KEY = "notes"
NOTES_DISABLED_DETAIL = "实时便笺功能已被管理员禁用"


async def _ensure_notes_enabled(*, current_user: User, db: AsyncSession) -> None:
    """
    在进入实时便笺业务链路前统一校验系统级功能开关。

    这里必须把拦截放在 API 入口，而不是等到 NoteService 里访问账号/上游接口之后再失败：
    - 关闭功能时应直接返回稳定的 403 语义，避免继续暴露账号存在性或触发外部请求
    - 两个接口共用同一条判断，后续若还有更多实时便笺端点，也能继承同一套管理员开关语义
    若误把该校验下沉到部分调用点，最直观的后果就是“列表页被禁了，但详情接口还能打通”。
    """
    is_enabled = await SystemSettingsService(db).is_menu_visible_for_role(
        menu_key=NOTES_MENU_KEY,
        role=current_user.role,
    )
    if not is_enabled:
        raise HTTPException(status_code=403, detail=NOTES_DISABLED_DETAIL)


@router.get("/accounts", response_model=NoteAccountListResponse)
async def get_note_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_notes_enabled(current_user=current_user, db=db)
    service = NoteService(db)
    return await service.list_supported_accounts(current_user.id)


@router.get("/summary", response_model=NoteSummaryResponse)
async def get_realtime_notes(
    account_id: int = Query(..., ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_notes_enabled(current_user=current_user, db=db)
    service = NoteService(db)
    account = await service.get_owned_account(account_id, current_user.id)
    return await service.get_summary(account=account)
