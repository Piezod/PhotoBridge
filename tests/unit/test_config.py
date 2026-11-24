import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_use_safe_phase_zero_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "PhotoBridge"
    assert settings.test_mode is True
    assert settings.max_photos_per_test == 10
    assert settings.delete_originals is False
    assert settings.manual_confirmation_required is True
    assert settings.automatic_migrations is False
    assert settings.host == "127.0.0.1"


def test_test_photo_limit_cannot_exceed_ten() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_photos_per_test=11)


def test_server_cannot_bind_to_non_local_interfaces() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, host="0.0.0.0")


def test_synology_download_limits_and_tls_defaults_are_secure(tmp_path) -> None:
    settings = Settings(_env_file=None)

    assert settings.synology_max_photos_per_operation == 10
    assert settings.synology_max_operation_bytes == 250_000_000
    assert settings.tls_verify() is True
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            synology_max_operation_bytes=250_000_001,
        )
    with pytest.raises(ValueError, match="CA configurado"):
        Settings(
            _env_file=None,
            synology_ca_bundle=tmp_path / "missing-ca.pem",
        ).tls_verify()
