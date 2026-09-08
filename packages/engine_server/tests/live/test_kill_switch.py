"""The kill switch.

The question that decides a kill switch's design is what happens when the thing
carrying it is broken — which is exactly when it is reached for.
"""

from __future__ import annotations

from pathlib import Path

import fakeredis
import fakeredis.aioredis
import pytest

from engine.live.kill_switch import (
    CompositeKillSwitch,
    FileKillSwitch,
    NeverEngaged,
    RedisKillSwitch,
)


@pytest.fixture
def redis_switch() -> RedisKillSwitch:
    return RedisKillSwitch(
        fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    )


# --- the Redis path ------------------------------------------------------


async def test_an_account_starts_unengaged(redis_switch: RedisKillSwitch) -> None:
    assert await redis_switch.is_engaged("acct_1") is False


async def test_engaging_and_releasing(redis_switch: RedisKillSwitch) -> None:
    await redis_switch.engage("acct_1")
    assert await redis_switch.is_engaged("acct_1") is True

    await redis_switch.release("acct_1")
    assert await redis_switch.is_engaged("acct_1") is False


async def test_accounts_are_independent(redis_switch: RedisKillSwitch) -> None:
    await redis_switch.engage("acct_1")
    assert await redis_switch.is_engaged("acct_2") is False


async def test_a_global_kill_stops_every_account(redis_switch: RedisKillSwitch) -> None:
    await redis_switch.engage_all()
    assert await redis_switch.is_engaged("acct_1") is True
    assert await redis_switch.is_engaged("acct_99") is True

    await redis_switch.release_all()
    assert await redis_switch.is_engaged("acct_1") is False


async def test_releasing_one_account_does_not_lift_a_global_kill(
    redis_switch: RedisKillSwitch,
) -> None:
    await redis_switch.engage_all()
    await redis_switch.release("acct_1")
    assert await redis_switch.is_engaged("acct_1") is True


# --- the file path -------------------------------------------------------


async def test_a_file_stops_an_account(tmp_path: Path) -> None:
    """The path that survives Redis being down.

    An operator with a shell can always stop a node.
    """
    switch = FileKillSwitch(tmp_path)
    assert await switch.is_engaged("acct_1") is False

    switch.engage("acct_1")
    assert await switch.is_engaged("acct_1") is True

    switch.release("acct_1")
    assert await switch.is_engaged("acct_1") is False


async def test_a_global_kill_file(tmp_path: Path) -> None:
    (tmp_path / "kill-all").touch()
    assert await FileKillSwitch(tmp_path).is_engaged("anything") is True


async def test_an_awkward_account_id_does_not_escape_the_directory(tmp_path: Path) -> None:
    switch = FileKillSwitch(tmp_path)
    switch.engage("../../etc/passwd")
    assert not (tmp_path.parent / "kill-..").exists()
    assert await switch.is_engaged("../../etc/passwd") is True


# --- the composite -------------------------------------------------------


async def test_either_path_is_enough(tmp_path: Path, redis_switch: RedisKillSwitch) -> None:
    file_switch = FileKillSwitch(tmp_path)
    composite = CompositeKillSwitch(redis_switch, file_switch)

    assert await composite.is_engaged("acct_1") is False

    file_switch.engage("acct_1")
    assert await composite.is_engaged("acct_1") is True

    file_switch.release("acct_1")
    await redis_switch.engage("acct_1")
    assert await composite.is_engaged("acct_1") is True


async def test_a_path_that_cannot_answer_is_treated_as_engaged(tmp_path: Path) -> None:
    """Failing safe is the whole point.

    A kill switch that quietly reports "not engaged" because its backing store
    is unreachable has removed itself at the moment it was needed.
    """

    class Broken:
        async def is_engaged(self, account_id: str) -> bool:
            raise ConnectionError("redis is unreachable")

    composite = CompositeKillSwitch(Broken(), FileKillSwitch(tmp_path))
    assert await composite.is_engaged("acct_1") is True


async def test_it_cannot_be_defeated_by_breaking_one_path(tmp_path: Path) -> None:
    # Neither breaking a path nor its absence turns the switch off.
    class Broken:
        async def is_engaged(self, account_id: str) -> bool:
            raise RuntimeError("gone")

    assert await CompositeKillSwitch(FileKillSwitch(tmp_path), Broken()).is_engaged("a") is True


async def test_the_never_engaged_switch_is_for_tests_only() -> None:
    assert await NeverEngaged().is_engaged("acct_1") is False
