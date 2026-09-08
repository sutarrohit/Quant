from __future__ import annotations

import io
import json
import logging
import re

from engine.logging import JsonFormatter, configure_logging, get_context, log_context


def emit(**kwargs: object) -> dict[str, object]:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    logging.getLogger("test").info("hello", extra=kwargs)  # type: ignore[arg-type]
    return json.loads(stream.getvalue())


def test_emits_one_json_object_per_record() -> None:
    record = emit()
    assert record["message"] == "hello"
    assert record["level"] == "INFO"
    assert record["logger"] == "test"
    assert record["ts"].endswith("+00:00")  # type: ignore[union-attr]


def test_context_fields_land_on_every_record() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    with log_context(job_id="job_1", spec_hash="abc"):
        logging.getLogger("test").info("inside")
    logging.getLogger("test").info("outside")

    inside, outside = (json.loads(line) for line in stream.getvalue().splitlines())
    assert inside["job_id"] == "job_1"
    assert inside["spec_hash"] == "abc"
    assert "job_id" not in outside


def test_context_nests_and_unwinds() -> None:
    with log_context(job_id="job_1"):
        with log_context(spec_hash="abc"):
            assert get_context() == {"job_id": "job_1", "spec_hash": "abc"}
        assert get_context() == {"job_id": "job_1"}
    assert get_context() == {}


def test_per_call_extra_overrides_context() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    with log_context(job_id="ambient"):
        logging.getLogger("test").info("x", extra={"job_id": "explicit"})
    assert json.loads(stream.getvalue())["job_id"] == "explicit"


def test_keys_are_sorted_so_output_is_diffable() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    logging.getLogger("test").info("x", extra={"zeta": 1, "alpha": 2})
    line = stream.getvalue()

    keys = re.findall(r'"([^"]+)":', line)
    assert keys == sorted(keys), line


def test_exception_is_rendered_as_a_field() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("test").exception("failed")
    assert "ValueError: boom" in json.loads(stream.getvalue())["exception"]


def test_configure_logging_is_idempotent() -> None:
    configure_logging("INFO", stream=io.StringIO())
    configure_logging("INFO", stream=io.StringIO())
    assert len(logging.getLogger().handlers) == 1


def test_formatter_survives_unserialisable_values() -> None:
    record = logging.LogRecord("t", logging.INFO, "f", 1, "m", None, None)
    record.thing = object()  # type: ignore[attr-defined]
    assert json.loads(JsonFormatter().format(record))["thing"].startswith("<object")
