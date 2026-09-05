"""Seed the database with demo users and posts.

Usage:
    uv run python -m scripts.seed
    uv run python -m scripts.seed --reset   # drop and recreate tables first
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from auth import hash_password  # noqa: E402
from db.database import AsyncSessionLocal, Base, engine  # noqa: E402
from db.models import models  # noqa: E402

DEMO_PASSWORD = "password123"

USERS = [
    {"username": "corey", "email": "corey@example.com"},
    {"username": "jane", "email": "jane@example.com"},
]

POSTS = [
    ("corey", "FastAPI is Awesome", "This framework is really easy to use and super fast."),
    ("corey", "Async SQLAlchemy 2.0", "Typed models with Mapped[] make the ORM much easier to read."),
    ("jane", "Python is Great for Web Development", "Python is a great language for web development."),
]


async def seed(reset: bool) -> None:
    async with engine.begin() as conn:
        if reset:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(models.User))
        if existing.scalars().first():
            print("Database already has users; pass --reset to start over.")
            return

        users = {}
        for entry in USERS:
            user = models.User(**entry, password_hash=hash_password(DEMO_PASSWORD))
            db.add(user)
            users[entry["username"]] = user
        await db.flush()

        for author, title, content in POSTS:
            db.add(models.Post(title=title, content=content, user_id=users[author].id))

        await db.commit()

    print(f"Seeded {len(USERS)} users and {len(POSTS)} posts.")
    print(f"Log in with any email above and the password: {DEMO_PASSWORD}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo data")
    parser.add_argument("--reset", action="store_true", help="drop all tables first")
    asyncio.run(seed(parser.parse_args().reset))
