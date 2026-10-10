"""Server settings, read from environment variables at application startup."""

from dataclasses import dataclass
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    base_url: str = "http://127.0.0.1:8769"
    timeout_seconds: float = 180
    catalog_path: Path = ROOT / "experiments/results/nimble_catalog.json"
    results_dir: Path = ROOT / "backend/results"
    max_questions: int = 128

    def __post_init__(self):
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("NIMBLE_TIMEOUT_SECONDS must be finite and positive")
        if self.max_questions < 1:
            raise ValueError("BACKEND_MAX_QUESTIONS must be positive")

    @classmethod
    def from_environment(cls):
        def path(name, default):
            value = Path(os.environ.get(name, str(default))).expanduser()
            return value if value.is_absolute() else ROOT / value

        return cls(
            base_url=os.environ.get("NIMBLE_BASE_URL", cls.base_url).rstrip("/"),
            timeout_seconds=float(os.environ.get("NIMBLE_TIMEOUT_SECONDS", "180")),
            catalog_path=path("KTRU_CATALOG_PATH", cls.catalog_path),
            results_dir=path("BACKEND_RESULTS_DIR", cls.results_dir),
            max_questions=int(os.environ.get("BACKEND_MAX_QUESTIONS", "128")),
        )
