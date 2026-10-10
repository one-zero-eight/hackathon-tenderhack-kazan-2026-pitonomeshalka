"""Shared runtime configuration for the API and standalone experiment scripts."""

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_environment(path=ROOT / ".env"):
    """Use the repository's .env regardless of cwd; process variables win."""
    load_dotenv(dotenv_path=path, override=False)


load_environment()


def env(name):
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"Missing {name}. Copy .example.env to .env and configure it, or export the variable.")
    return value


def env_path(name):
    value = Path(env(name)).expanduser()
    return value if value.is_absolute() else ROOT / value


def configured(name, convert=str):
    return field(default_factory=lambda: convert(env(name)))


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: env("DATABASE_URL"), repr=False)
    database_connect_timeout_seconds: int = configured("DATABASE_CONNECT_TIMEOUT_SECONDS", int)
    database_pool_min_size: int = configured("DATABASE_POOL_MIN_SIZE", int)
    database_pool_max_size: int = configured("DATABASE_POOL_MAX_SIZE", int)
    database_pool_timeout_seconds: float = configured("DATABASE_POOL_TIMEOUT_SECONDS", float)
    catalog_key: str = configured("KTRU_CATALOG_KEY")
    classifier_base_url: str = configured("CLASSIFIER_BASE_URL", lambda value: value.rstrip("/"))
    classifier_model: str = configured("CLASSIFIER_MODEL")
    classifier_timeout_seconds: float = configured("CLASSIFIER_TIMEOUT_SECONDS", float)
    classifier_health_timeout_seconds: float = configured("CLASSIFIER_HEALTH_TIMEOUT_SECONDS", float)
    classifier_batch_size: int = configured("CLASSIFIER_BATCH_SIZE", int)
    catalog_path: Path = field(default_factory=lambda: env_path("KTRU_CATALOG_PATH"))
    xml_dir: Path = field(default_factory=lambda: env_path("KTRU_XML_DIR"))
    experiment_results_dir: Path = field(default_factory=lambda: env_path("EXPERIMENT_RESULTS_DIR"))
    results_dir: Path = field(default_factory=lambda: env_path("BACKEND_RESULTS_DIR"))
    startup_log_path: Path = field(default_factory=lambda: env_path("BACKEND_STARTUP_LOG_PATH"))
    startup_check_timeout_seconds: float = configured("STARTUP_CHECK_TIMEOUT_SECONDS", float)
    max_questions: int = configured("BACKEND_MAX_QUESTIONS", int)
    host: str = configured("BACKEND_HOST")
    port: int = configured("BACKEND_PORT", int)
    log_level: str = configured("LOG_LEVEL", str.lower)
    embedding_base_url: str = configured("EMBEDDING_BASE_URL", lambda value: value.rstrip("/"))
    embedding_model: str = configured("EMBEDDING_MODEL")
    embedding_timeout_seconds: float = configured("EMBEDDING_TIMEOUT_SECONDS", float)
    embedding_batch_size: int = configured("EMBEDDING_BATCH_SIZE", int)
    embedding_max_names: int = configured("EMBEDDING_MAX_NAMES", int)
    embedding_cache_path: Path = field(default_factory=lambda: env_path("EMBEDDING_CACHE_PATH"))
    top_k: int = configured("PIPELINE_TOP_K", int)
    chunk_size: int = configured("PIPELINE_CHUNK_SIZE", int)
    threshold: float = configured("PIPELINE_THRESHOLD", float)

    def __post_init__(self):
        for name, value in (("CLASSIFIER_BASE_URL", self.classifier_base_url), ("EMBEDDING_BASE_URL", self.embedding_base_url)):
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment:
                raise ValueError(f"{name} must be an HTTP(S) base URL without query or fragment")
        for name, value in (("CLASSIFIER_TIMEOUT_SECONDS", self.classifier_timeout_seconds),
                            ("DATABASE_POOL_TIMEOUT_SECONDS", self.database_pool_timeout_seconds),
                            ("STARTUP_CHECK_TIMEOUT_SECONDS", self.startup_check_timeout_seconds),
                            ("CLASSIFIER_HEALTH_TIMEOUT_SECONDS", self.classifier_health_timeout_seconds),
                            ("EMBEDDING_TIMEOUT_SECONDS", self.embedding_timeout_seconds)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name, value in (("BACKEND_MAX_QUESTIONS", self.max_questions),
                            ("DATABASE_CONNECT_TIMEOUT_SECONDS", self.database_connect_timeout_seconds),
                            ("EMBEDDING_MAX_NAMES", self.embedding_max_names),
                            ("EMBEDDING_BATCH_SIZE", self.embedding_batch_size)):
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if not 1 <= self.port <= 65535:
            raise ValueError("BACKEND_PORT must be between 1 and 65535")
        if not 1 <= self.database_pool_min_size <= self.database_pool_max_size:
            raise ValueError("Database pool sizes must satisfy 1 <= min <= max")
        if urlsplit(self.database_url).scheme not in {"postgresql", "postgres"}:
            raise ValueError("DATABASE_URL must use postgresql:// or postgres://")
        if self.log_level not in {"critical", "error", "warning", "info", "debug"}:
            raise ValueError("LOG_LEVEL must be critical, error, warning, info or debug")
        if not 1 <= self.top_k <= 32 or not 1 <= self.chunk_size <= 8:
            raise ValueError("PIPELINE_TOP_K must be 1–32 and PIPELINE_CHUNK_SIZE 1–8")
        if not 0 <= self.classifier_batch_size <= 64:
            raise ValueError("CLASSIFIER_BATCH_SIZE must be 0 (disabled) or 1–64")
        if not math.isfinite(self.threshold) or not 0 <= self.threshold <= 1:
            raise ValueError("PIPELINE_THRESHOLD must be finite and between 0 and 1")
        if not self.embedding_model.strip() or not self.classifier_model.strip() or not self.host.strip():
            raise ValueError("Model IDs and BACKEND_HOST must not be blank")

    @classmethod
    def from_environment(cls):
        load_environment()
        return cls()
