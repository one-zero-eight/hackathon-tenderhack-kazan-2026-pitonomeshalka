"""Import an immutable relational catalogue snapshot (KTRU XML by default).

    uv run python scripts/load_db.py --ktru-only --activate catalogue-key
    uv run python scripts/load_db.py --with-spgz --activate catalogue-key

The backend store initializes migrations and owns the SQLAlchemy engine. Loading
and optional activation share one transaction; existing snapshots are never rebuilt.
"""

import argparse
import csv
from pathlib import Path
import time
from typing import cast

if __package__:
    from . import load_ktru, load_spgz
    from .dbutil import insert_missing, source_manifest
else:
    import load_ktru
    import load_spgz
    from dbutil import insert_missing, source_manifest

from psycopg import sql
from sqlalchemy import Table, text
from sqlalchemy.dialects.postgresql import insert

from backend.src.models import CatalogueImport, CatalogueSource, SourceFile
from backend.src.settings import Settings
from backend.src.storage import PostgresStore

HERE = Path(__file__).resolve().parent


def load_aliases(conn, *, schema):
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT code FROM {}").format(sql.Identifier(schema, "okei")))
        known_units = {row[0] for row in cur.fetchall()}
        with (HERE / "okei_alias.csv").open(newline="", encoding="utf-8") as aliases:
            reader = csv.reader(aliases)
            next(reader)
            insert_missing(cur, "okei_alias", ("alias", "okei"),
                           (tuple(row) for row in reader if row[1] in known_units), schema=schema)


def import_catalogue(store, xml_paths, xlsx_paths=(), *, activate=None):
    """Return the import hash; store must be initialized and expose catalogue_schema.

    All SQLAlchemy operations translate the logical catalogue schema. COPY uses
    the same transaction's underlying psycopg connection and explicit identifiers.
    """
    xml_paths = tuple(sorted(xml_paths, key=lambda path: path.name))
    xlsx_paths = tuple(sorted(xlsx_paths, key=lambda path: path.name))
    if not xml_paths:
        raise ValueError("at least one KTRU XML file is required")
    fingerprint, manifest = source_manifest(xml_paths, xlsx_paths)
    rejects = None
    imports = cast(Table, CatalogueImport.__table__)
    sources = cast(Table, CatalogueSource.__table__)
    files = cast(Table, SourceFile.__table__)
    with store.engine.begin() as connection:
        connection = connection.execution_options(schema_translate_map={"catalogue": store.catalogue_schema})
        inserted = connection.execute(
            insert(imports).values(sha256=fingerprint, metadata=manifest)
            .on_conflict_do_nothing(index_elements=[imports.c.sha256]).returning(imports.c.sha256)
        ).scalar_one_or_none()
        if inserted is not None:
            file_ids = {}
            for source in manifest["files"]:
                file_ids[source["name"]] = connection.execute(
                    insert(files).values(import_sha256=fingerprint, **source).returning(files.c.id)
                ).scalar_one()
            driver = connection.connection.driver_connection
            load_ktru.load(driver, fingerprint, file_ids, schema=store.catalogue_schema, paths=xml_paths)
            if xlsx_paths:
                rejects = load_spgz.load(driver, fingerprint, file_ids, schema=store.catalogue_schema, paths=xlsx_paths)
            load_aliases(driver, schema=store.catalogue_schema)
            # Both XML passes and workbook parsing must see the hashed content.
            if source_manifest(xml_paths, xlsx_paths)[0] != fingerprint:
                raise ValueError("source files changed during import; staged rows were rolled back")
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            connection.execute(text(
                f'REFRESH MATERIALIZED VIEW "{store.catalogue_schema}"."ktru_family_splits"'
            ))
        else:
            print(f"catalogue import {fingerprint} already loaded; skipping")
        if activate is not None:
            connection.execute(
                insert(sources).values(key=activate, import_sha256=fingerprint)
                .on_conflict_do_update(index_elements=[sources.c.key], set_={"import_sha256": fingerprint})
            )
    if rejects is not None:
        load_spgz.write_rejects(rejects)
    return fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--ktru-only", dest="ktru_only", action="store_true", help="load XML only (default)")
    mode.add_argument("--with-spgz", dest="ktru_only", action="store_false", help="also import SPGZ workbooks")
    parser.set_defaults(ktru_only=True)
    parser.add_argument("--activate", metavar="KEY", help="point this catalogue key to the import after successful validation")
    args = parser.parse_args()
    try:
        xml_paths = load_ktru.xml_paths()
        xlsx_paths = () if args.ktru_only else load_spgz.xlsx_paths()
    except FileNotFoundError as error:
        parser.error(str(error))
    started = time.monotonic()
    store = PostgresStore(Settings())
    try:
        store.initialize()
        fingerprint = import_catalogue(store, xml_paths, xlsx_paths, activate=args.activate)
    finally:
        store.close()
    print(f"catalogue import {fingerprint}; done in {time.monotonic() - started:.0f}s")


if __name__ == "__main__":
    main()
