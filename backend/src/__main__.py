"""Start the API with `uv run -m backend.src [uvicorn options]`."""

import sys

import uvicorn


def main() -> None:
    uvicorn.main.main([
        "backend.src.app:app",
        "--host=127.0.0.1",
        "--port=8000",
        "--workers=1",
        *sys.argv[1:],
    ])


if __name__ == "__main__":
    main()
