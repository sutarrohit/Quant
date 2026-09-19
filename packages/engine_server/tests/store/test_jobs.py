from __future__ import annotations

import asyncio
from typing import Any

import pytest

from engine.errors import JobNotCancellable, JobNotFound, RequestIdConflict
from engine.store.jobs import JobStatus, JobStore
from tests.store.conftest import Clock

#: A stand-in submission. The store does not interpret it; it carries it.
REQUEST: dict[str, Any] = {"venue": "BINANCE", "slippageBps": "5"}

# --- claiming ------------------------------------------------------------


async def test_a_new_request_creates_a_queued_job(store: JobStore, clock: Clock) -> None:
    record, created = await store.claim("req_1", "hash_a", REQUEST)

    assert created is True
    assert record.job_id == "job_0001"
    assert record.request_id == "req_1"
    assert record.status is JobStatus.QUEUED
    assert record.submitted_at == clock.moment
    assert record.started_at is None
    assert record.finished_at is None


async def test_a_repeat_request_returns_the_same_job(store: JobStore) -> None:
    # Spec section 7.2: a repeat submission returns the existing job and never
    # starts a second run.
    first, created_first = await store.claim("req_1", "hash_a", REQUEST)
    second, created_second = await store.claim("req_1", "hash_a", REQUEST)

    assert created_first is True
    assert created_second is False
    assert second.job_id == first.job_id
    assert second.submitted_at == first.submitted_at


async def test_a_repeat_request_does_not_reset_progress(store: JobStore) -> None:
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    await store.mark_running(record.job_id)

    again, created = await store.claim("req_1", "hash_a", REQUEST)

    assert created is False
    assert again.status is JobStatus.RUNNING


async def test_a_different_payload_under_the_same_request_id_conflicts(store: JobStore) -> None:
    original, _ = await store.claim("req_1", "hash_a", REQUEST)

    with pytest.raises(RequestIdConflict) as caught:
        await store.claim("req_1", "hash_b", REQUEST)

    assert caught.value.code.value == "REQUEST_ID_CONFLICT"
    assert caught.value.http_status == 409
    assert caught.value.details == {"jobId": original.job_id}


async def test_different_request_ids_are_independent(store: JobStore) -> None:
    first, _ = await store.claim("req_1", "hash_a", REQUEST)
    second, created = await store.claim("req_2", "hash_a", REQUEST)
    assert created is True
    assert second.job_id != first.job_id


async def test_a_losing_claim_leaves_no_orphan_record(store: JobStore) -> None:
    # The claim writes a candidate before taking the pointer; the loser must
    # clean its candidate up or Redis fills with unreachable jobs.
    await store.claim("req_1", "hash_a", REQUEST)
    await store.claim("req_1", "hash_a", REQUEST)
    assert await store.get("job_0002") is None


async def test_concurrent_claims_create_exactly_one_job(store: JobStore) -> None:
    """The Step 12 gate.

    Read-then-write cannot promise this: both callers read "absent" and both
    create. The claim takes the idempotency pointer with SET NX instead.
    """
    results = await asyncio.gather(*(store.claim("req_race", "hash_a", REQUEST) for _ in range(20)))

    job_ids = {record.job_id for record, _ in results}
    created = [was_created for _, was_created in results]

    assert len(job_ids) == 1, f"race produced {len(job_ids)} jobs"
    assert created.count(True) == 1, f"{created.count(True)} callers believed they created it"


# --- reading -------------------------------------------------------------


async def test_get_returns_none_for_an_unknown_job(store: JobStore) -> None:
    assert await store.get("job_nope") is None


async def test_require_raises_for_an_unknown_job(store: JobStore) -> None:
    with pytest.raises(JobNotFound):
        await store.require("job_nope")


async def test_a_record_round_trips_through_redis(store: JobStore) -> None:
    created, _ = await store.claim("req_1", "hash_a", REQUEST)
    assert await store.get(created.job_id) == created


# --- transitions ---------------------------------------------------------


async def test_the_happy_path(store: JobStore, clock: Clock) -> None:
    record, _ = await store.claim("req_1", "hash_a", REQUEST)

    clock.advance(10)
    running = await store.mark_running(record.job_id)
    assert running.status is JobStatus.RUNNING
    assert running.started_at == clock.moment

    clock.advance(60)
    done = await store.mark_succeeded(record.job_id, {"totalReturn": "0.12"})
    assert done.status is JobStatus.SUCCEEDED
    assert done.finished_at == clock.moment
    assert done.result == {"totalReturn": "0.12"}
    assert done.submitted_at == record.submitted_at


async def test_failure_records_a_code_not_a_traceback(store: JobStore) -> None:
    # Spec section 7.4: tracebacks are logged, never returned to a caller.
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    await store.mark_running(record.job_id)

    failed = await store.mark_failed(record.job_id, "TIMEOUT", "exceeded 600s")

    assert failed.status is JobStatus.FAILED
    assert failed.error == {"code": "TIMEOUT", "message": "exceeded 600s"}
    assert "Traceback" not in failed.to_json()


async def test_a_queued_job_can_fail_without_running(store: JobStore) -> None:
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    failed = await store.mark_failed(record.job_id, "SPEC_INVALID", "bad spec")
    assert failed.status is JobStatus.FAILED


async def test_success_requires_having_run(store: JobStore) -> None:
    # A QUEUED job cannot jump to SUCCEEDED; the transition is refused and the
    # stored status is returned unchanged.
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    unchanged = await store.mark_succeeded(record.job_id, {"x": 1})
    assert unchanged.status is JobStatus.QUEUED
    assert unchanged.result is None


async def test_a_finished_job_is_not_restarted(store: JobStore) -> None:
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    await store.mark_running(record.job_id)
    await store.mark_succeeded(record.job_id, {"x": 1})

    unchanged = await store.mark_running(record.job_id)
    assert unchanged.status is JobStatus.SUCCEEDED


async def test_transitions_on_an_unknown_job_raise(store: JobStore) -> None:
    with pytest.raises(JobNotFound):
        await store.mark_running("job_nope")


# --- cancellation --------------------------------------------------------


async def test_a_queued_job_can_be_cancelled(store: JobStore, clock: Clock) -> None:
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    clock.advance(5)

    cancelled = await store.cancel(record.job_id)

    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.finished_at == clock.moment


async def test_a_running_job_cannot_be_cancelled(store: JobStore) -> None:
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    await store.mark_running(record.job_id)

    with pytest.raises(JobNotCancellable) as caught:
        await store.cancel(record.job_id)

    assert caught.value.http_status == 409
    assert caught.value.details == {"status": "RUNNING"}
    assert (await store.require(record.job_id)).status is JobStatus.RUNNING


async def test_cancel_and_start_cannot_both_win(store: JobStore) -> None:
    # Cancelling races the worker picking the job up. Deciding "still QUEUED?"
    # between two round trips would let both succeed.
    record, _ = await store.claim("req_1", "hash_a", REQUEST)

    outcomes = await asyncio.gather(
        store.cancel(record.job_id),
        store.mark_running(record.job_id),
        return_exceptions=True,
    )
    final = await store.require(record.job_id)

    assert final.status in (JobStatus.CANCELLED, JobStatus.RUNNING)
    succeeded = [o for o in outcomes if not isinstance(o, Exception)]
    if final.status is JobStatus.CANCELLED:
        assert any(isinstance(o, Exception) for o in outcomes) or all(
            getattr(o, "status", None) is JobStatus.CANCELLED for o in succeeded
        )


async def test_cancelling_an_unknown_job_raises(store: JobStore) -> None:
    with pytest.raises(JobNotFound):
        await store.cancel("job_nope")


# --- status semantics ----------------------------------------------------


@pytest.mark.parametrize(
    ("status", "terminal"),
    [
        (JobStatus.QUEUED, False),
        (JobStatus.RUNNING, False),
        (JobStatus.SUCCEEDED, True),
        (JobStatus.FAILED, True),
        (JobStatus.CANCELLED, True),
    ],
)
def test_terminal_statuses(status: JobStatus, terminal: bool) -> None:
    assert status.terminal is terminal


def test_the_documented_status_set(store: JobStore) -> None:
    # Spec section 7.2 fixed five; automatic data provisioning added
    # FETCHING_DATA as a sixth (ADR-003). The TypeScript caller branches on
    # these, so the list is asserted rather than left to drift -- and the four
    # terminal-vs-live semantics below are what it actually branches on.
    assert [s.value for s in JobStatus] == [
        "QUEUED",
        "FETCHING_DATA",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
    ]


# --- expiry and health ---------------------------------------------------


async def test_records_carry_a_ttl(store: JobStore, redis_client: Any) -> None:
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    assert 0 < await redis_client.ttl(f"job:{record.job_id}") <= 3600
    assert 0 < await redis_client.ttl("idem:req_1") <= 3600


async def test_ping_reports_a_reachable_redis(store: JobStore) -> None:
    assert await store.ping() is True


async def test_ping_reports_an_unreachable_redis() -> None:
    import redis.asyncio as aioredis

    unreachable = JobStore(aioredis.from_url("redis://127.0.0.1:6390/0"))
    assert await unreachable.ping() is False


async def test_the_record_carries_the_request(store: JobStore) -> None:
    # The worker loads the job by id and needs everything required to run it,
    # so the queue moves only an identifier.
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    assert (await store.require(record.job_id)).request == REQUEST


async def test_a_replay_returns_the_original_request(store: JobStore) -> None:
    # Same requestId and payload hash: the stored bytes are the first
    # submission's, so a retry cannot silently run something else.
    first, _ = await store.claim("req_1", "hash_a", REQUEST)
    again, created = await store.claim("req_1", "hash_a", {"venue": "OTHER"})
    assert created is False
    assert again.request == REQUEST


async def test_an_empty_object_in_a_result_survives_a_transition(store: JobStore) -> None:
    """Lua has one table type, and cjson encodes an empty object as ``[]``.

    An earlier version of the transition script decoded the whole record,
    patched it and re-encoded, which turned any stored ``{}`` into a list.
    The record is a hash now and the script touches only the fields it is
    given.
    """
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    await store.mark_running(record.job_id)

    await store.mark_succeeded(
        record.job_id, {"summary": {}, "artifacts": {}, "fills": 4}
    )

    result = (await store.require(record.job_id)).result
    assert result == {"summary": {}, "artifacts": {}, "fills": 4}
    assert isinstance(result["summary"], dict)


async def test_nested_structures_survive_a_transition(store: JobStore) -> None:
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    await store.mark_running(record.job_id)
    payload = {
        "summary": {"totalReturn": "5.5", "nested": {"deep": []}},
        "list": [1, 2, 3],
        "empty_list": [],
    }

    await store.mark_succeeded(record.job_id, payload)

    assert (await store.require(record.job_id)).result == payload


async def test_the_stored_request_survives_transitions(store: JobStore) -> None:
    record, _ = await store.claim("req_1", "hash_a", REQUEST)
    await store.mark_running(record.job_id)
    await store.mark_succeeded(record.job_id, {"fills": 1})
    assert (await store.require(record.job_id)).request == REQUEST
