from __future__ import annotations

import pytest

from engine.errors import CredentialUnavailable
from engine.live.credentials import EnvironmentCredentialResolver, NoCredentialsResolver, VenueCredentials


def test_a_key_never_appears_in_its_own_repr() -> None:
    """A key that reaches a traceback has reached a log.

    Exceptions carry their locals in a traceback, and structured logs carry the
    exception. Redacting at the object is the only place that covers all of it.
    """
    credentials = VenueCredentials(api_key="AK_real_key", api_secret="SK_real_secret")

    assert "AK_real_key" not in repr(credentials)
    assert "SK_real_secret" not in repr(credentials)
    assert "AK_real_key" not in str(credentials)
    assert "AK_real_key" not in f"{credentials}"


def test_the_values_are_still_reachable() -> None:
    # Redaction must not stop the node from actually using them.
    credentials = VenueCredentials(api_key="AK", api_secret="SK")
    assert credentials.api_key == "AK"
    assert credentials.api_secret == "SK"


def test_the_environment_resolver_reads_a_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NT_VENUE_BINANCE_ACCT_1_KEY", "AK")
    monkeypatch.setenv("NT_VENUE_BINANCE_ACCT_1_SECRET", "SK")

    credentials = EnvironmentCredentialResolver().resolve("binance-acct-1")

    assert credentials.api_key == "AK"
    assert credentials.api_secret == "SK"


def test_a_missing_reference_refuses_rather_than_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A node must refuse to start rather than trade without credentials.
    monkeypatch.delenv("NT_VENUE_NOPE_KEY", raising=False)
    with pytest.raises(CredentialUnavailable, match="nope"):
        EnvironmentCredentialResolver().resolve("nope")


def test_a_half_configured_reference_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NT_VENUE_HALF_KEY", "AK")
    monkeypatch.delenv("NT_VENUE_HALF_SECRET", raising=False)
    with pytest.raises(CredentialUnavailable):
        EnvironmentCredentialResolver().resolve("half")


def test_the_default_resolver_refuses_everything() -> None:
    # So a key is never resolved by accident.
    with pytest.raises(CredentialUnavailable, match="no credential resolver"):
        NoCredentialsResolver().resolve("anything")


def test_the_error_names_the_reference_not_the_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NT_VENUE_PARTIAL_KEY", "AK_should_not_appear")
    monkeypatch.delenv("NT_VENUE_PARTIAL_SECRET", raising=False)

    with pytest.raises(CredentialUnavailable) as caught:
        EnvironmentCredentialResolver().resolve("partial")

    assert "AK_should_not_appear" not in str(caught.value)
