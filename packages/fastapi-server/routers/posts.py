from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth import CurrentUser
from db.database import get_db
from schema.schema import PostCreate, PostListResponse, PostResponse, PostUpdate
from service import post_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


# get all posts with pagination
@router.get("", response_model=PostListResponse)
async def get_posts(
    db: DbSession,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    posts, total = await post_service.list_posts(db, skip=skip, limit=limit)

    return PostListResponse(
        items=posts,
        total=total,
        page=skip // limit + 1,
        limit=limit,
        total_pages=(total + limit - 1) // limit if total > 0 else 0,
    )


#  Create Posts
@router.post("", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_posts(post: PostCreate, current_user: CurrentUser, db: DbSession):
    return await post_service.create_post(db, post, current_user)


# get post by id
@router.get("/{post_id}", response_model=PostResponse)
async def get_post(post_id: int, db: DbSession):
    return await post_service.get_post(db, post_id)


# update post by id PUT
@router.put("/{post_id}", response_model=PostResponse)
async def update_post_full(post_id: int, post_data: PostCreate, current_user: CurrentUser, db: DbSession):
    return await post_service.replace_post(db, post_id, post_data, current_user)


# update post by id PATCH
@router.patch("/{post_id}", response_model=PostResponse)
async def update_post_partial(post_id: int, post_data: PostUpdate, current_user: CurrentUser, db: DbSession):
    return await post_service.update_post(db, post_id, post_data, current_user)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(post_id: int, current_user: CurrentUser, db: DbSession):
    await post_service.delete_post(db, post_id, current_user)
