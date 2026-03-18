"""实时便笺 API"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.notes import NoteAccountListResponse, NoteSummaryResponse
from app.services.notes import NoteService

router = APIRouter(prefix="/api/notes", tags=["实时便笺"])


@router.get("/accounts", response_model=NoteAccountListResponse)
async def get_note_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NoteService(db)
    return await service.list_supported_accounts(current_user.id)


@router.get("/summary", response_model=NoteSummaryResponse)
async def get_realtime_notes(
    account_id: int = Query(..., ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = NoteService(db)
    account = await service.get_owned_account(account_id, current_user.id)
    return await service.get_summary(account=account)
