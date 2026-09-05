from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from auth import CurrentUser
from db.database import get_db
from schema.schema import (
    PostResponse,
    Token,
    UserCreate,
    UserListResponse,
    UserPrivate,
    UserPublic,
    UserUpdate,
)
from service import user_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


# Create USER
@router.post("", response_model=UserPrivate, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate, db: DbSession):
    return await user_service.create_user(db, user)


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
):
    # OAuth2PasswordRequestForm calls the field "username", but we treat it as email
    access_token = await user_service.authenticate(db, form_data.username, form_data.password)

    return Token(access_token=access_token, token_type="bearer")


# List users with pagination
@router.get("", response_model=UserListResponse)
async def get_users(
    db: DbSession,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    users, total = await user_service.list_users(db, skip=skip, limit=limit)

    return UserListResponse(
        items=users,
        total=total,
        page=skip // limit + 1,
        limit=limit,
        total_pages=(total + limit - 1) // limit if total > 0 else 0,
    )


# Validate user
# NOTE: must be declared before "/{user_id}" so "me" is not parsed as an id.
@router.get("/me", response_model=UserPrivate)
async def read_current_user(current_user: CurrentUser):
    return current_user


# Upload a profile picture for the logged-in user
@router.post("/me/avatar", response_model=UserPrivate)
async def upload_avatar(
    current_user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
):
    contents = await file.read()

    return await user_service.save_avatar(db, current_user, contents, file.content_type)


# Get user by id
@router.get("/{user_id}", response_model=UserPublic)
async def get_user(user_id: int, db: DbSession):
    return await user_service.get_user(db, user_id)


# Get all posts by a user
@router.get("/{user_id}/posts", response_model=list[PostResponse])
async def get_user_posts(user_id: int, db: DbSession):
    return await user_service.list_user_posts(db, user_id)


# Update user by id PATCH
@router.patch("/{user_id}", response_model=UserPrivate)
async def update_user_partial(user_id: int, user_data: UserUpdate, current_user: CurrentUser, db: DbSession):
    return await user_service.update_user(db, user_id, user_data, current_user)


# Delete user by id (cascade - deletes all posts)
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, current_user: CurrentUser, db: DbSession):
    await user_service.delete_user(db, user_id, current_user)
