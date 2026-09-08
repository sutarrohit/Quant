"""A key must never reach a log, an exception, a job record, or a response.

ADR-001 states this as a non-negotiable consequence of Option B and adds that
"the structured logger already redacts nothing by default; that changes". This
file is the change, and the assertions are deliberately about the *key string*
rather than about any particular code path -- because the path that leaks it
will be one nobody thought to test.
"""

from __future__ import annotations

import io
import json
import logging
import os
import stat
from pathlib import Path

import pytest

from engine.live.credentials import (
    CredentialUnavailable,
    EnvironmentCredentialResolver,
    NoCredentialsResolver,
    SecretsFileResolver,
    VenueCredentials,
    assert_usable_in_live,
)
from engine.logging import configure_logging, log_context, redact

#: Distinctive enough that finding it anywhere is unambiguous.
KEY = "AKIA-not-a-real-key-9f3c1d"
SECRET = "sk-not-a-real-secret-77b2e4"


@pytest.fixture
def credentials() -> VenueCredentials:
    return VenueCredentials(api_key=KEY, api_secret=SECRET)


def secret_file(directory: Path, name: str = "binance-main", mode: int = 0o600) -> Path:
    path = directory / name
    path.write_text(json.dumps({"api_key": KEY, "api_secret": SECRET}))
    path.chmod(mode)
    return path


# --- the object itself ---------------------------------------------------


def test_repr_does_not_contain_the_key(credentials: VenueCredentials) -> None:
    # A key that reaches a traceback has reached a log.
    assert KEY not in repr(credentials)
    assert SECRET not in repr(credentials)


def test_str_does_not_contain_the_key(credentials: VenueCredentials) -> None:
    assert KEY not in str(credentials)
    assert SECRET not in f"{credentials}"


def test_an_f_string_does_not_contain_the_key(credentials: VenueCredentials) -> None:
    # The most likely accident: someone logs the object into a message.
    assert KEY not in f"resolved {credentials} for the venue"


def test_it_is_still_usable(credentials: VenueCredentials) -> None:
    # Redaction that broke the value would be found immediately; this asserts
    # the object still carries what the adapter needs.
    assert credentials.api_key == KEY


# --- the logger ----------------------------------------------------------


def capture(emit: object) -> str:
    stream = io.StringIO()
    configure_logging("DEBUG", stream=stream)
    emit()  # type: ignore[operator]
    logging.getLogger().handlers[0].flush()
    return stream.getvalue()


def test_a_secret_named_field_is_redacted() -> None:
    """The mistake that actually happens.

    Not passing the object -- passing the string, in a debug line written at
    2am and never removed.
    """
    output = capture(
        lambda: logging.getLogger("t").info("connecting", extra={"api_secret": SECRET})
    )

    assert SECRET not in output
    assert "***" in output


def test_every_marker_redacts() -> None:
    fields = {
        "api_key": KEY,
        "apiKey": KEY,
        "binance_api_secret": SECRET,
        "password": "hunter2",
        "passphrase": "open sesame",
        "auth_token": "bearer-abc",
    }

    redacted = redact(fields)

    assert set(redacted.values()) == {"***"}


def test_ordinary_fields_are_untouched() -> None:
    # Over-redaction that swallowed account ids would make logs useless.
    assert redact({"account_id": "acct_1", "notional": "500"}) == {
        "account_id": "acct_1",
        "notional": "500",
    }


def test_the_ambient_context_is_redacted_too() -> None:
    # `log_context` fields are merged into every line inside the block, so a
    # secret placed there would leak from everywhere at once.
    def emit() -> None:
        with log_context(api_key=KEY):
            logging.getLogger("t").info("working")

    output = capture(emit)

    assert KEY not in output


def test_the_object_in_a_field_is_redacted(credentials: VenueCredentials) -> None:
    output = capture(
        lambda: logging.getLogger("t").info("built", extra={"credentials": credentials})
    )

    assert KEY not in output


# --- resolution failures -------------------------------------------------


def test_a_missing_reference_names_it_without_values(tmp_path: Path) -> None:
    with pytest.raises(CredentialUnavailable) as raised:
        SecretsFileResolver(tmp_path).resolve("binance-main")

    assert "binance-main" in str(raised.value)
    assert KEY not in str(raised.value)


def test_a_malformed_file_does_not_quote_itself(tmp_path: Path) -> None:
    """A JSON decode error quotes the document it failed on.

    That document is the key. So the error is rewritten rather than chained,
    and `from None` cuts the original out of the traceback.
    """
    path = tmp_path / "binance-main"
    path.write_text('{"api_key": "' + KEY + '", oops')
    path.chmod(0o600)

    with pytest.raises(CredentialUnavailable) as raised:
        SecretsFileResolver(tmp_path).resolve("binance-main")

    assert KEY not in str(raised.value)
    assert KEY not in repr(raised.value)
    assert raised.value.__cause__ is None


def test_a_traceback_does_not_carry_the_key(tmp_path: Path) -> None:
    import traceback

    path = tmp_path / "binance-main"
    path.write_text('{"api_key": "' + KEY + '"}')  # no secret
    path.chmod(0o600)

    try:
        SecretsFileResolver(tmp_path).resolve("binance-main")
    except CredentialUnavailable:
        text = traceback.format_exc()

    assert KEY not in text


# --- the file itself -----------------------------------------------------


def test_a_readable_file_is_refused(tmp_path: Path) -> None:
    """A world-readable secret is not a secret.

    A mode that permissive usually means it was written by something that did
    not know it was handling a key.
    """
    secret_file(tmp_path, mode=0o644)

    with pytest.raises(CredentialUnavailable, match="readable beyond its owner"):
        SecretsFileResolver(tmp_path).resolve("binance-main")


def test_a_private_file_resolves(tmp_path: Path) -> None:
    secret_file(tmp_path)

    resolved = SecretsFileResolver(tmp_path).resolve("binance-main")

    assert resolved.api_key == KEY


def test_a_group_readable_file_is_refused(tmp_path: Path) -> None:
    secret_file(tmp_path, mode=0o640)

    with pytest.raises(CredentialUnavailable):
        SecretsFileResolver(tmp_path).resolve("binance-main")


def test_a_reference_cannot_escape_the_directory(tmp_path: Path) -> None:
    """Refused rather than sanitised.

    A reference arrives from a stored record. Silently reading a different file
    is worse than failing.
    """
    outside = tmp_path.parent / "elsewhere"
    outside.mkdir(exist_ok=True)
    (outside / "key").write_text("{}")

    for reference in ("../elsewhere/key", "/etc/passwd", "", "./x"):
        with pytest.raises(CredentialUnavailable):
            SecretsFileResolver(tmp_path).resolve(reference)


def test_the_mode_check_can_be_relaxed_only_deliberately(tmp_path: Path) -> None:
    # Some platforms project secrets with a mode the process cannot control.
    # It is an argument, not a fallback, so relaxing it is visible in a diff.
    secret_file(tmp_path, mode=0o644)

    assert SecretsFileResolver(tmp_path, require_private=False).resolve("binance-main")


# --- resolvers that must not be used live --------------------------------


def test_the_environment_resolver_is_refused_for_live() -> None:
    """A rule, not a docstring.

    ADR-001 forbids keys from environment variables. "Development only" written
    in a comment is a comment; this is enforcement.
    """
    with pytest.raises(CredentialUnavailable, match="must not be used for live"):
        assert_usable_in_live(EnvironmentCredentialResolver())


def test_no_resolver_is_refused_for_live() -> None:
    with pytest.raises(CredentialUnavailable, match="requires a credential resolver"):
        assert_usable_in_live(NoCredentialsResolver())


def test_the_file_resolver_is_accepted(tmp_path: Path) -> None:
    assert_usable_in_live(SecretsFileResolver(tmp_path))


def test_the_environment_resolver_still_works_for_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # It is not removed -- it is the reason the code path could be built and
    # tested before a secrets manager existed.
    monkeypatch.setenv("NT_VENUE_BINANCE_MAIN_KEY", KEY)
    monkeypatch.setenv("NT_VENUE_BINANCE_MAIN_SECRET", SECRET)

    assert EnvironmentCredentialResolver().resolve("binance-main").api_key == KEY


def test_a_simulation_node_holds_no_key(tmp_path: Path) -> None:
    # The default refuses everything, so a key is never resolved by accident.
    with pytest.raises(CredentialUnavailable):
        NoCredentialsResolver().resolve("binance-main")


# --- the HTTP surface ----------------------------------------------------


def test_the_desired_state_response_carries_no_reference() -> None:
    """Even a *reference* is not handed back by default.

    It names where a key lives, which is more than a caller needs and enough to
    start looking.
    """
    from tests.live.conftest import desired

    assert "credential_ref" not in desired(credential_ref="binance-main").to_response()


def test_the_file_permissions_of_a_written_secret(tmp_path: Path) -> None:
    # Guards the fixture itself: a test that wrote 0644 and passed would be
    # asserting nothing.
    path = secret_file(tmp_path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


# --- the documented exception (ADR-001 addendum) -------------------------


def test_the_environment_resolver_is_permitted_when_allowed() -> None:
    """The repo owner's exception, taken explicitly.

    A setting rather than a deleted check, so the choice shows up in a diff, in
    a deployment's config, and in a WARNING on every node start.
    """
    assert_usable_in_live(EnvironmentCredentialResolver(), allow_environment=True)


def test_it_stays_forbidden_by_default() -> None:
    # The rule is still the rule. An exception that quietly became the default
    # would be the guardrail removed rather than overridden.
    with pytest.raises(CredentialUnavailable):
        assert_usable_in_live(EnvironmentCredentialResolver())


def test_the_refusal_names_the_override() -> None:
    # An operator hitting this needs to know it is deliberate and how to take
    # it, not just that something is forbidden.
    with pytest.raises(CredentialUnavailable, match="NT_LIVE_ALLOW_ENV_CREDENTIALS"):
        assert_usable_in_live(EnvironmentCredentialResolver())


def test_the_override_does_not_permit_having_no_resolver() -> None:
    # It relaxes *where* a key comes from, not whether one is required.
    with pytest.raises(CredentialUnavailable):
        assert_usable_in_live(NoCredentialsResolver(), allow_environment=True)


def test_the_default_settings_forbid_it() -> None:
    from engine.settings import Settings

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        redis_url="redis://localhost:6379/0",
        cache_redis_url="redis://localhost:6380/0",
        internal_api_key="x",
        log_level="ERROR",
    )
    assert settings.live_allow_env_credentials is False


def test_the_variable_names_match_the_addendum(monkeypatch: pytest.MonkeyPatch) -> None:
    """`credentialRef: "binance-main"` reads NT_VENUE_BINANCE_MAIN_{KEY,SECRET}.

    Asserted because an operator following the ADR and getting the name wrong
    sees "no credentials for reference", which reads like a missing key rather
    than a misspelt variable.
    """
    monkeypatch.setenv("NT_VENUE_BINANCE_MAIN_KEY", KEY)
    monkeypatch.setenv("NT_VENUE_BINANCE_MAIN_SECRET", SECRET)

    resolved = EnvironmentCredentialResolver().resolve("binance-main")

    assert (resolved.api_key, resolved.api_secret) == (KEY, SECRET)


def test_a_missing_environment_key_names_the_reference_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NT_VENUE_BINANCE_MAIN_KEY", raising=False)

    with pytest.raises(CredentialUnavailable) as raised:
        EnvironmentCredentialResolver().resolve("binance-main")

    assert "binance-main" in str(raised.value)
    assert KEY not in str(raised.value)
