"""Service-layer tests.

These call the services directly with a session -- no HTTP, no routers. This is
what the service layer buys you: the rules are testable without a request.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    UnsupportedMediaError,
)
from schema.schema import PostCreate, PostUpdate, UserCreate, UserUpdate
from service import post_service, user_service


async def _make_user(db: AsyncSession, name: str = "alice") -> object:
    return await user_service.create_user(
        db,
        UserCreate(username=name, email=f"{name}@example.com", password="password123"),
    )


async def test_create_user_hashes_the_password(db_session: AsyncSession):
    user = await _make_user(db_session)

    assert user.password_hash != "password123"
    assert user.password_hash.startswith("$argon2")


async def test_create_user_rejects_duplicate_username_case_insensitively(db_session: AsyncSession):
    await _make_user(db_session)

    with pytest.raises(ConflictError, match="Username already exists"):
        await user_service.create_user(
            db_session,
            UserCreate(username="ALICE", email="other@example.com", password="password123"),
        )


async def test_authenticate_returns_a_token(db_session: AsyncSession):
    await _make_user(db_session)

    token = await user_service.authenticate(db_session, "alice@example.com", "password123")

    assert token


async def test_authenticate_rejects_a_bad_password(db_session: AsyncSession):
    await _make_user(db_session)

    with pytest.raises(AuthenticationError):
        await user_service.authenticate(db_session, "alice@example.com", "nope")


async def test_authenticate_rejects_an_unknown_email(db_session: AsyncSession):
    with pytest.raises(AuthenticationError):
        await user_service.authenticate(db_session, "ghost@example.com", "password123")


async def test_get_user_raises_not_found(db_session: AsyncSession):
    with pytest.raises(NotFoundError, match="User not found"):
        await user_service.get_user(db_session, 999)


async def test_update_user_rejects_a_different_user(db_session: AsyncSession):
    alice = await _make_user(db_session, "alice")
    bob = await _make_user(db_session, "bob")

    with pytest.raises(PermissionDeniedError):
        await user_service.update_user(db_session, alice.id, UserUpdate(username="x"), current_user=bob)


async def test_save_avatar_rejects_a_bad_content_type(db_session: AsyncSession):
    alice = await _make_user(db_session)

    with pytest.raises(UnsupportedMediaError):
        await user_service.save_avatar(db_session, alice, b"data", "text/plain")


async def test_save_avatar_rejects_an_oversized_file(db_session: AsyncSession):
    alice = await _make_user(db_session)
    too_big = b"x" * (user_service.MAX_AVATAR_BYTES + 1)

    with pytest.raises(PayloadTooLargeError):
        await user_service.save_avatar(db_session, alice, too_big, "image/png")


async def test_create_and_get_post(db_session: AsyncSession):
    alice = await _make_user(db_session)

    created = await post_service.create_post(db_session, PostCreate(title="T", content="C"), alice)
    fetched = await post_service.get_post(db_session, created.id)

    assert fetched.id == created.id
    assert fetched.author.username == "alice"


async def test_get_post_raises_not_found(db_session: AsyncSession):
    with pytest.raises(NotFoundError, match="Post not found"):
        await post_service.get_post(db_session, 999)


async def test_update_post_rejects_a_non_owner(db_session: AsyncSession):
    alice = await _make_user(db_session, "alice")
    bob = await _make_user(db_session, "bob")
    post = await post_service.create_post(db_session, PostCreate(title="T", content="C"), alice)

    with pytest.raises(PermissionDeniedError, match="Not authorized to update this post"):
        await post_service.update_post(db_session, post.id, PostUpdate(title="Hacked"), bob)


async def test_delete_post_rejects_a_non_owner(db_session: AsyncSession):
    alice = await _make_user(db_session, "alice")
    bob = await _make_user(db_session, "bob")
    post = await post_service.create_post(db_session, PostCreate(title="T", content="C"), alice)

    with pytest.raises(PermissionDeniedError, match="Not authorized to delete this post"):
        await post_service.delete_post(db_session, post.id, bob)


async def test_delete_missing_post_raises_not_found(db_session: AsyncSession):
    alice = await _make_user(db_session)

    with pytest.raises(NotFoundError):
        await post_service.delete_post(db_session, 999, alice)


async def test_list_posts_returns_items_and_total(db_session: AsyncSession):
    alice = await _make_user(db_session)
    for i in range(3):
        await post_service.create_post(db_session, PostCreate(title=f"T{i}", content="C"), alice)

    posts, total = await post_service.list_posts(db_session, skip=0, limit=2)

    assert total == 3
    assert len(posts) == 2
