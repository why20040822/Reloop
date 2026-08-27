"""Redact provider callback secrets before framework and access logging."""

from urllib.parse import parse_qsl, urlencode


class RedactAuthCallbackMiddleware:
    """Move callback secrets into ASGI state and replace their query values."""

    _SECRET_KEYS = {
        "/auth/feishu/callback": {"code"},
        "/auth/ttc/callback": {"token", "access_token"},
    }

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "").rstrip("/")
        secret_keys = self._SECRET_KEYS.get(path) if scope.get("type") == "http" else None
        if secret_keys:
            pairs = parse_qsl(scope.get("query_string", b"").decode("utf-8"), keep_blank_values=True)
            secrets: dict[str, str] = {}
            redacted: list[tuple[str, str]] = []
            for key, value in pairs:
                if key in secret_keys:
                    secrets[key] = value
                    redacted.append((key, "[REDACTED]"))
                else:
                    redacted.append((key, value))
            scope.setdefault("state", {})["auth_callback_secrets"] = secrets
            scope["query_string"] = urlencode(redacted).encode("utf-8")
        await self.app(scope, receive, send)
