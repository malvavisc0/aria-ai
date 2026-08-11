from aria.config import get_optional_env, get_required_env

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_loopback_host(host: str) -> bool:
    """Return True when the host is a loopback address (secure context).

    ``getUserMedia`` (microphone capture) requires a secure context —
    HTTPS or a loopback origin. Audio is only enabled for loopback
    binds; any LAN bind disables the voice feature so the mic button
    is not shown when it cannot work.

    Args:
        host: The configured ``SERVER_HOST`` bind address.

    Returns:
        True for ``localhost``, ``127.0.0.1``, ``::1``.
    """
    return host.lower() in _LOOPBACK_HOSTS


class Server:
    host = get_optional_env("SERVER_HOST", "localhost")
    port = int(get_required_env("SERVER_PORT"))

    @classmethod
    def get_base_url(cls):
        return f"http://{cls.host}:{cls.port}/"
