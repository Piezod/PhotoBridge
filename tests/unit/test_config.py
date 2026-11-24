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

