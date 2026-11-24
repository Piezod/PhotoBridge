from typing import Protocol


class CredentialStore(Protocol):
    def get_password(self, key: str) -> str | None: ...

    def set_password(self, key: str, password: str) -> None: ...
