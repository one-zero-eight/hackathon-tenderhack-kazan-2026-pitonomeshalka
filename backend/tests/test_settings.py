"""Configuration loading and overrides without contacting either model."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dotenv import dotenv_values

from experiments.config import ROOT, Settings, env, load_environment
from experiments.embedding_retrieval import MeowEmbedClient
from experiments.classifier_experiments import ClassifierClient


class ConfigurationTests(unittest.TestCase):
    def test_example_is_complete_and_has_local_services(self):
        with patch.dict(os.environ, {}, clear=True):
            load_environment(ROOT / ".example.env")
            settings = Settings()
            self.assertEqual(settings.classifier_base_url, "http://127.0.0.1:8769")
            self.assertEqual(settings.embedding_base_url, "http://127.0.0.1:8067")
            self.assertEqual(settings.database_url, "postgresql://tenderhack:tenderhack-local@127.0.0.1:5432/tenderhack")
            self.assertNotIn(settings.database_url, repr(settings))
            self.assertTrue(env("EMBEDDING_QUERY_PROMPT").endswith(" "))
            self.assertTrue(env("EMBEDDING_DOCUMENT_PROMPT").endswith(" "))

    def test_exported_variables_win_and_paths_do_not_depend_on_cwd(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "CLASSIFIER_BASE_URL": "https://classifier.example/service/",
            "CLASSIFIER_TIMEOUT_SECONDS": "17",
            "EMBEDDING_BASE_URL": "https://embeddings.example/service/",
            "EMBEDDING_TIMEOUT_SECONDS": "11",
            "EMBEDDING_MODEL": "custom-model",
        }, clear=True):
            try:
                os.chdir(directory)
                load_environment(ROOT / ".example.env")
                settings = Settings()
                self.assertEqual(settings.classifier_base_url, "https://classifier.example/service")
                self.assertEqual(settings.classifier_timeout_seconds, 17)
                self.assertEqual(settings.catalog_path, ROOT / "experiments/results/catalog.json")
                self.assertEqual(settings.embedding_cache_path, ROOT / "backend/cache/catalog_embeddings.json")
                self.assertEqual(ClassifierClient().timeout, 17)
                embedder = MeowEmbedClient()
                self.assertEqual(embedder.base_url, "https://embeddings.example/service")
                self.assertEqual(embedder.model_id, "custom-model")
                self.assertEqual(embedder.timeout, 11)
            finally:
                os.chdir(previous)

    def test_default_env_location_is_repository_root(self):
        with patch("experiments.config.load_dotenv") as loader:
            load_environment()
        loader.assert_called_once_with(dotenv_path=ROOT / ".env", override=False)

    def test_missing_service_address_has_setup_message(self):
        with patch.dict(os.environ, dict(dotenv_values(ROOT / ".example.env")), clear=True):
            del os.environ["CLASSIFIER_BASE_URL"]
            with self.assertRaisesRegex(ValueError, "Missing CLASSIFIER_BASE_URL.*Copy .example.env"):
                Settings()

    def test_invalid_configuration_is_rejected(self):
        invalid = [
            ("CLASSIFIER_BASE_URL", "file:///tmp/model"),
            ("EMBEDDING_BASE_URL", "https://example.com?query=bad"),
            ("CLASSIFIER_TIMEOUT_SECONDS", "nan"),
            ("STARTUP_CHECK_TIMEOUT_SECONDS", "0"),
            ("CLASSIFIER_HEALTH_TIMEOUT_SECONDS", "0"),
            ("EMBEDDING_TIMEOUT_SECONDS", "0"),
            ("EMBEDDING_BATCH_SIZE", "0"),
            ("EMBEDDING_MAX_NAMES", "0"),
            ("BACKEND_MAX_QUESTIONS", "0"),
            ("BACKEND_PORT", "65536"),
            ("PIPELINE_TOP_K", "33"),
            ("PIPELINE_CHUNK_SIZE", "9"),
            ("PIPELINE_THRESHOLD", "nan"),
            ("LOG_LEVEL", "not-a-level"),
            ("DATABASE_URL", "https://example.com"),
            ("DATABASE_CONNECT_TIMEOUT_SECONDS", "0"),
            ("DATABASE_POOL_TIMEOUT_SECONDS", "nan"),
            ("DATABASE_POOL_MIN_SIZE", "0"),
            ("DATABASE_POOL_MIN_SIZE", "5"),
            ("DATABASE_POOL_MAX_SIZE", "0"),
        ]
        for name, value in invalid:
            with self.subTest(name=name), patch.dict(os.environ, dict(dotenv_values(ROOT / ".example.env")), clear=True):
                os.environ[name] = value
                with self.assertRaises(ValueError):
                    Settings()

    def test_launcher_uses_configuration_and_preserves_cli_overrides(self):
        from backend.src.__main__ import main

        with patch.dict(os.environ, {"BACKEND_HOST": "0.0.0.0", "BACKEND_PORT": "9001", "LOG_LEVEL": "debug"}), \
                patch("sys.argv", ["backend", "--port=9002"]), \
                patch("backend.src.__main__.uvicorn.main.main") as launch:
            main()
        launch.assert_called_once_with([
            "backend.src.app:app", "--host=0.0.0.0", "--port=9001", "--log-level=debug", "--workers=1", "--port=9002",
        ])


if __name__ == "__main__":
    unittest.main()
