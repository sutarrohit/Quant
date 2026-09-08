from __future__ import annotations

import pytest

from engine.errors import ConfigurationError
from engine.settings import Settings, as_local_path, is_remote_uri


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_reads_the_nt_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NT_CATALOG_PATH", "/srv/catalog")
    monkeypatch.setenv("NT_LOG_LEVEL", "DEBUG")
    settings = make()
    assert settings.catalog_path == "/srv/catalog"
    assert settings.log_level == "DEBUG"


def test_rejects_an_unknown_log_level() -> None:
    with pytest.raises(ValueError):
        make(log_level="LOUD")


def test_has_no_database_url() -> None:
    # Spec section 9.4: this service never connects to the platform PostgreSQL.
    # A field appearing here would be the first step towards two writers on the
    # same financial tables.
    assert "database_url" not in Settings.model_fields


def test_internal_api_key_is_secret() -> None:
    settings = make(internal_api_key="hunter2")
    assert "hunter2" not in repr(settings)
    assert settings.require_internal_api_key().get_secret_value() == "hunter2"


def test_require_internal_api_key_raises_when_unset() -> None:
    with pytest.raises(ConfigurationError):
        make().require_internal_api_key()


@pytest.mark.parametrize(
    ("value", "remote"),
    [
        ("./catalog", False),
        ("/srv/catalog", False),
        ("file:///srv/catalog", False),
        ("s3://bucket/catalog", True),
        ("gs://bucket/catalog", True),
    ],
)
def test_is_remote_uri(value: str, remote: bool) -> None:
    assert is_remote_uri(value) is remote


def test_as_local_path_rejects_remote_uris() -> None:
    # Path("s3://bucket/k") silently collapses to "s3:/bucket/k", which is why
    # storage roots are typed as str and go through this function.
    with pytest.raises(ConfigurationError):
        as_local_path("s3://bucket/catalog")
