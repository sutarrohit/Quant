"""Business logic for users: registration, login, profile and avatars."""

import secrets
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import create_access_token, hash_password, verify_password
from config import settings
from db.models import models
from exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    UnsupportedMediaError,
)
from schema.schema import UserCreate, UserUpdate

ALLOWED_AVATAR_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB


async def _get_by_username(db: AsyncSession, username: str) -> models.User | None:
    result = await db.execute(
        select(models.User).where(func.lower(models.User.username) == username.lower()),
    )
    return result.scalars().first()


async def _get_by_email(db: AsyncSession, email: str) -> models.User | None:
    result = await db.execute(
        select(models.User).where(func.lower(models.User.email) == email.lower()),
    )
    return result.scalars().first()


async def get_user(db: AsyncSession, user_id: int) -> models.User:
    """Fetch a user or raise NotFoundError."""
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise NotFoundError("User not found")

    return user


async def create_user(db: AsyncSession, data: UserCreate) -> models.User:
    if await _get_by_username(db, data.username):
        raise ConflictError("Username already exists")

    if await _get_by_email(db, data.email):
        raise ConflictError("Email already exists")

    user = models.User(
        username=data.username,
        email=data.email.lower(),
        password_hash=hash_password(data.password),
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> str:
    """Verify credentials and return a signed access token."""
    user = await _get_by_email(db, email)

    # Do not reveal which half of the credentials was wrong
    if not user or not verify_password(password, user.password_hash):
        raise AuthenticationError("Incorrect email or password")

    return create_access_token(data={"sub": str(user.id)})


async def list_users(db: AsyncSession, skip: int, limit: int) -> tuple[list[models.User], int]:
    """Return one page of users plus the total row count."""
    count_result = await db.execute(select(func.count(models.User.id)))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.User).order_by(models.User.id).offset(skip).limit(limit),
    )

    return list(result.scalars().all()), total


async def list_user_posts(db: AsyncSession, user_id: int) -> list[models.Post]:
    await get_user(db, user_id)  # 404 if the user does not exist

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.user_id == user_id)
        .order_by(models.Post.date_posted.desc()),
    )

    return list(result.scalars().all())


async def update_user(
    db: AsyncSession,
    user_id: int,
    data: UserUpdate,
    current_user: models.User,
) -> models.User:
    if user_id != current_user.id:
        raise PermissionDeniedError("Not authorized to update this user")

    user = await get_user(db, user_id)
    changes = data.model_dump(exclude_unset=True)

    if "username" in changes:
        existing = await _get_by_username(db, changes["username"])
        if existing and existing.id != user_id:
            raise ConflictError("Username already exists")

    if "email" in changes:
        changes["email"] = changes["email"].lower()
        existing = await _get_by_email(db, changes["email"])
        if existing and existing.id != user_id:
            raise ConflictError("Email already exists")

    for field, value in changes.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    return user


async def delete_user(db: AsyncSession, user_id: int, current_user: models.User) -> None:
    if user_id != current_user.id:
        raise PermissionDeniedError("Not authorized to delete this user")

    result = await db.execute(
        select(models.User).options(selectinload(models.User.posts)).where(models.User.id == user_id),
    )
    user = result.scalars().first()

    if not user:
        raise NotFoundError("User not found")

    # cascade="all, delete-orphan" on User.posts removes the posts too
    await db.delete(user)
    await db.commit()


async def save_avatar(
    db: AsyncSession,
    current_user: models.User,
    contents: bytes,
    content_type: str | None,
) -> models.User:
    """Store an uploaded profile picture and point the user at it."""
    extension = ALLOWED_AVATAR_TYPES.get(content_type or "")
    if extension is None:
        raise UnsupportedMediaError(
            f"Unsupported image type. Allowed: {', '.join(ALLOWED_AVATAR_TYPES)}",
        )

    if len(contents) > MAX_AVATAR_BYTES:
        raise PayloadTooLargeError("Image must be 2 MB or smaller")

    avatar_dir: Path = settings.media_dir / "profile_pics"
    avatar_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{current_user.id}_{secrets.token_hex(8)}{extension}"
    (avatar_dir / filename).write_bytes(contents)

    # Remove the previous upload so the media directory does not grow unbounded
    if current_user.image_file:
        (avatar_dir / current_user.image_file).unlink(missing_ok=True)

    current_user.image_file = filename
    await db.commit()
    await db.refresh(current_user)

    return current_user
