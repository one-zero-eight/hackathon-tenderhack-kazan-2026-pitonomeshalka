"""Apply versioned PostgreSQL migrations without importing legacy catalogue/vector caches."""

import argparse
import logging

from backend.src.settings import Settings
from backend.src.storage import PostgresStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    settings = Settings.from_environment()
    logging.basicConfig(level=settings.log_level.upper())
    store = PostgresStore(settings)
    try:
        store.initialize()
    finally:
        store.close()


if __name__ == "__main__":
    main()
