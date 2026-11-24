import keyring


class KeyringCredentialStore:
    service_name = "PhotoBridge Synology"

    def get_password(self, key: str) -> str | None:
        self._ensure_secure_backend()
        return keyring.get_password(self.service_name, key)

    def set_password(self, key: str, password: str) -> None:
        self._ensure_secure_backend()
        keyring.set_password(self.service_name, key, password)

    @staticmethod
    def _ensure_secure_backend() -> None:
        if keyring.get_keyring().priority <= 0:
            raise RuntimeError(
                "No hay un almacén seguro de credenciales disponible en este sistema."
            )
