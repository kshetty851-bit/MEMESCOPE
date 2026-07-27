"""Current-user profile routes."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, UserServiceDep
from app.schemas.auth import MessageResponse
from app.schemas.user import PasswordChange, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead, summary="Get the authenticated user")
async def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead, summary="Update the authenticated user")
async def update_me(
    payload: UserUpdate, user: CurrentUser, service: UserServiceDep
) -> UserRead:
    return UserRead.model_validate(await service.update_profile(user, payload))


@router.post(
    "/me/password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Change password and revoke all sessions",
)
async def change_password(
    payload: PasswordChange, user: CurrentUser, service: UserServiceDep
) -> MessageResponse:
    await service.change_password(user, payload)
    return MessageResponse(message="Password updated. Please sign in again.")
