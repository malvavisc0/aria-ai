from aria.config import get_optional_env, get_required_env


class Server:
    host = get_optional_env("SERVER_HOST", "localhost")
    port = int(get_required_env("SERVER_PORT"))

    @classmethod
    def get_base_url(cls):
        return f"http://{cls.host}:{cls.port}/"
