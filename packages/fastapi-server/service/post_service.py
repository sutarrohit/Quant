"""Business logic for posts: CRUD plus ownership rules."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import models
from exceptions import NotFoundError, PermissionDeniedError
from schema.schema import PostCreate, PostUpdate


async def get_post(db: AsyncSession, post_id: int) -> models.Post:
    """Fetch a post with its author eagerly loaded, or raise NotFoundError."""
    result = await db.execute(
        select(models.Post).options(selectinload(models.Post.author)).where(models.Post.id == post_id),
    )
    post = result.scalars().first()

    if not post:
        raise NotFoundError("Post not found")

    return post


def _assert_owner(post: models.Post, current_user: models.User, action: str) -> None:
    if post.user_id != current_user.id:
        raise PermissionDeniedError(f"Not authorized to {action} this post")


async def list_posts(db: AsyncSession, skip: int, limit: int) -> tuple[list[models.Post], int]:
    """Return one page of posts plus the total row count."""
    count_result = await db.execute(select(func.count(models.Post.id)))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .order_by(models.Post.date_posted.desc())
        .offset(skip)
        .limit(limit),
    )

    return list(result.scalars().all()), total


async def create_post(db: AsyncSession, data: PostCreate, current_user: models.User) -> models.Post:
    post = models.Post(
        title=data.title,
        content=data.content,
        user_id=current_user.id,
    )

    db.add(post)
    await db.commit()
    await db.refresh(post, attribute_names=["author"])

    return post


async def replace_post(
    db: AsyncSession,
    post_id: int,
    data: PostCreate,
    current_user: models.User,
) -> models.Post:
    """PUT semantics: every field is overwritten."""
    post = await get_post(db, post_id)
    _assert_owner(post, current_user, "update")

    post.title = data.title
    post.content = data.content

    await db.commit()
    await db.refresh(post, attribute_names=["author"])

    return post


async def update_post(
    db: AsyncSession,
    post_id: int,
    data: PostUpdate,
    current_user: models.User,
) -> models.Post:
    """PATCH semantics: only the fields that were sent are touched."""
    post = await get_post(db, post_id)
    _assert_owner(post, current_user, "update")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(post, field, value)

    await db.commit()
    await db.refresh(post, attribute_names=["author"])

    return post


async def delete_post(db: AsyncSession, post_id: int, current_user: models.User) -> None:
    post = await get_post(db, post_id)
    _assert_owner(post, current_user, "delete")

    await db.delete(post)
    await db.commit()
