"""Start the API with `uv run -m backend.src [uvicorn options]`."""

import sys

import uvicorn

from backend.src.settings import Settings


def main() -> None:
    settings = Settings.from_environment()
    uvicorn.main.main([
        "backend.src.app:app",
        f"--host={settings.host}",
        f"--port={settings.port}",
        f"--log-level={settings.log_level}",
        "--workers=1",
        *sys.argv[1:],
    ])


if __name__ == "__main__":
    main()
