"""Backfill pgvector embeddings for the active relational KTRU catalogue.

    uv run python -m scripts.embed_db
    uv run python -m scripts.embed_db --catalog-key ktru --batch-size 32

Each batch commits separately. Rerunning skips matching embeddings and resumes
failed or interrupted imports; vectors from another configuration are replaced.
"""

import argparse
import logging
from time import monotonic

from sqlalchemy import bindparam, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from backend.src.models import EmbeddingConfig, KtruCharacteristic, KtruPosition, KtruValue
from backend.src.retrieval import DIMENSIONS, embedding_config
from backend.src.settings import Settings
from backend.src.storage import PostgresStore
from experiments.embedding_retrieval import EmbeddingError, MeowEmbedClient, unit_vector

logger = logging.getLogger("uvicorn.error")


def embedding_sources():
    """Select only fields searched by the backend, with their product context."""
    positions = KtruPosition.__table__
    characteristics = KtruCharacteristic.__table__
    values = KtruValue.__table__
    chars = characteristics.join(positions,
        (characteristics.c.import_sha256 == positions.c.import_sha256) &
        (characteristics.c.position_code == positions.c.code))
    texts = values.join(chars,
        (values.c.import_sha256 == characteristics.c.import_sha256) &
        (values.c.position_code == characteristics.c.position_code) &
        (values.c.characteristic_code == characteristics.c.code))
    return (
        (positions, (positions.c.code,), select(positions.c.code, positions.c.name.label("document")), ()),
        (characteristics, (characteristics.c.position_code, characteristics.c.code),
         select(characteristics.c.position_code, characteristics.c.code,
                (positions.c.name + "\n" + characteristics.c.name).label("document")).select_from(chars),
         (characteristics.c.actual.is_(True),)),
        (values, (values.c.id,),
         select(values.c.id,
                (positions.c.name + "\n" + characteristics.c.name + "\n" + values.c.text).label("document"))
         .select_from(texts),
         (characteristics.c.actual.is_(True), values.c.text.is_not(None), values.c.issue.is_(None))),
    )


def backfill_embeddings(store, settings, client, *, catalog_key=None, batch_size=None):
    """Fill one pinned snapshot using an initialized PostgresStore."""
    key = settings.catalog_key if catalog_key is None else catalog_key
    batch_size = settings.embedding_batch_size if batch_size is None else batch_size
    if batch_size < 1:
        raise ValueError("Embedding batch size must be positive")
    import_id = store.get_active_import(key)
    if import_id is None:
        raise ValueError(f"No active catalogue for {key!r}; import XML with --activate {key} first")
    config = embedding_config(settings)
    fingerprint = config["fingerprint"]
    logger.info("Embedding backfill: catalogue=%s import=%s config=%s", key, import_id, fingerprint)
    with store.engine.begin() as connection:
        connection.execute(insert(EmbeddingConfig.__table__).values(**config)
                           .on_conflict_do_nothing(index_elements=["fingerprint"]))
    counts = {}
    for table, keys, source, conditions in embedding_sources():
        pending = or_(table.c.embedding.is_(None), table.c.embedding_config.is_distinct_from(fingerprint))
        source = source.where(table.c.import_sha256 == import_id, pending, *conditions).order_by(*keys)
        statement = (update(table).where(table.c.import_sha256 == import_id, pending,
                     *(column == bindparam(f"key_{column.name}") for column in keys))
                     .values(embedding=bindparam("vector"), embedding_config=fingerprint))
        count, cursor = 0, None
        while True:
            batch = source
            if cursor is not None:
                batch = batch.where(tuple_(*keys) > tuple_(*cursor))
            # Release the read connection before the network call; no long-lived transaction.
            with store.engine.connect() as connection:
                rows = connection.execute(batch.limit(batch_size)).mappings().all()
            if not rows:
                break
            documents = list(dict.fromkeys(row["document"] for row in rows))
            vectors = client.embed(documents, config["document_prompt"])
            if len(vectors) != len(documents):
                raise EmbeddingError("Embedding batch did not return every document; batch was not saved")
            normalized = []
            for vector in vectors:
                vector = unit_vector(vector)
                if len(vector) != DIMENSIONS:
                    raise EmbeddingError(f"Expected {DIMENSIONS}-dimensional embeddings; batch was not saved")
                normalized.append(vector)
            by_document = dict(zip(documents, normalized, strict=True))
            updates = [{**{f"key_{column.name}": row[column.name] for column in keys},
                        "vector": by_document[row["document"]]} for row in rows]
            with store.engine.begin() as connection:
                result = connection.execute(statement, updates)
                count += result.rowcount
            cursor = tuple(rows[-1][column.name] for column in keys)
            logger.info("Embedding backfill: table=%s updated=%d batch_rows=%d documents=%d",
                        table.name, count, len(rows), len(documents))
        counts[table.name] = count
        logger.info("Embedding backfill complete: table=%s updated=%d", table.name, count)
    return {"import_sha256": import_id, "embedding_config": fingerprint, "counts": counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-key", help="catalogue key (default: KTRU_CATALOG_KEY)")
    parser.add_argument("--batch-size", type=int, help="rows per batch (default: EMBEDDING_BATCH_SIZE)")
    args = parser.parse_args()
    if args.batch_size is not None and args.batch_size < 1:
        parser.error("--batch-size must be positive")
    settings = Settings.from_environment()
    logging.basicConfig(level=settings.log_level.upper())
    store = PostgresStore(settings)
    client = MeowEmbedClient(settings.embedding_base_url, settings.embedding_model,
                             settings.embedding_timeout_seconds)
    started = monotonic()
    try:
        store.initialize()
        client.health()
        result = backfill_embeddings(store, settings, client,
                                     catalog_key=args.catalog_key, batch_size=args.batch_size)
    except (ValueError, EmbeddingError) as error:
        parser.exit(1, f"{error}\nPreviously committed batches are retained; rerun to resume.\n")
    finally:
        store.close()
    print(f"catalogue {result['import_sha256']}; config {result['embedding_config']}; "
          f"updated {result['counts']}; done in {monotonic() - started:.0f}s")


if __name__ == "__main__":
    main()
