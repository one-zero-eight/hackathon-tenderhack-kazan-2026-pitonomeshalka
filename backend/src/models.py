"""Typed catalogue snapshots; translate the logical ``catalogue`` schema per store."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey,
    ForeignKeyConstraint, Identity, Index, Integer, MetaData, SmallInteger,
    Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, NUMRANGE, Range
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql.functions import FunctionElement


class Base(DeclarativeBase):
    metadata = MetaData(schema="catalogue")



class _Norm(FunctionElement):
    type = Text()
    inherit_cache = True


@compiles(_Norm, "postgresql")
def _compile_norm(element, compiler, **kwargs):
    column = next(iter(element.clauses))
    schema = compiler.preparer.quote_schema(compiler.preparer.schema_for_object(column.table))
    return f"{schema}.norm({compiler.process(element.clauses, **kwargs)})"


KTRU_STATUS = Enum("ACTIVE", "INACTIVE", "TERMINATED", name="ktru_status", schema="catalogue")
VALUE_CHOICE = Enum("fixed", "one_of", "many_of", name="value_choice", schema="catalogue")
SPGZ_ROLE = Enum("base", "reference", "category", name="spgz_role", schema="catalogue")
SPGZ_VTYPE = Enum("text", "dict", "flag", "int", "decimal", "range", name="spgz_vtype", schema="catalogue")


class CatalogueImport(Base):
    __tablename__ = "catalogue_imports"

    sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))


class CatalogueSource(Base):
    __tablename__ = "catalogue_sources"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    import_sha256: Mapped[str] = mapped_column(ForeignKey("catalogue.catalogue_imports.sha256"))


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (
        UniqueConstraint("import_sha256", "name"),
        UniqueConstraint("import_sha256", "id"),
        CheckConstraint("kind IN ('xml', 'xlsx')"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    import_sha256: Mapped[str] = mapped_column(ForeignKey("catalogue.catalogue_imports.sha256"))
    name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)


class EmbeddingConfig(Base):
    __tablename__ = "embedding_configs"
    __table_args__ = (CheckConstraint("dimensions = 768"),)

    fingerprint: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text)
    dimensions: Mapped[int] = mapped_column(Integer)
    document_prompt: Mapped[str] = mapped_column(Text)
    query_prompt: Mapped[str] = mapped_column(Text)
    document_format: Mapped[str] = mapped_column(Text)


class Okei(Base):
    __tablename__ = "okei"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class OkeiAlias(Base):
    __tablename__ = "okei_alias"

    alias: Mapped[str] = mapped_column(Text, primary_key=True)
    okei: Mapped[str] = mapped_column(ForeignKey("catalogue.okei.code", deferrable=True, initially="DEFERRED"))


class Okpd2(Base):
    __tablename__ = "okpd2"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class KtruPosition(Base):
    __tablename__ = "ktru_position"
    __table_args__ = (
        ForeignKeyConstraint(
            ["import_sha256", "source_file_id"], ["catalogue.source_files.import_sha256", "catalogue.source_files.id"],
            deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("parent_version IS NULL OR parent_code IS NOT NULL"),
        CheckConstraint("(embedding IS NULL) = (embedding_config IS NULL)"),
    )

    import_sha256: Mapped[str] = mapped_column(ForeignKey("catalogue.catalogue_imports.sha256"), primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    xml_id: Mapped[str | None] = mapped_column(Text)
    version_code: Mapped[str | None] = mapped_column(Text)
    external_code: Mapped[str | None] = mapped_column(Text)
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    name: Mapped[str] = mapped_column(Text)
    okpd2: Mapped[str] = mapped_column(ForeignKey("catalogue.okpd2.code", deferrable=True, initially="DEFERRED"))
    status: Mapped[str] = mapped_column(KTRU_STATUS)
    terminated_on: Mapped[date | None] = mapped_column(Date)
    is_template: Mapped[bool] = mapped_column(Boolean)
    parent_code: Mapped[str | None] = mapped_column(Text)
    parent_version: Mapped[int | None] = mapped_column(Integer)
    applies_from: Mapped[date] = mapped_column(Date)
    applies_to: Mapped[date | None] = mapped_column(Date)
    no_new_features: Mapped[bool | None] = mapped_column(Boolean)
    no_new_features_reason: Mapped[str | None] = mapped_column(Text)
    units: Mapped[list[str]] = mapped_column(ARRAY(Text))
    rubrics: Mapped[list[str | None]] = mapped_column(ARRAY(Text))
    rubric_codes: Mapped[list[str | None]] = mapped_column(ARRAY(Text))
    description: Mapped[str | None] = mapped_column(Text)
    source_file_id: Mapped[int] = mapped_column(BigInteger)
    source_line: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    embedding_config: Mapped[str | None] = mapped_column(ForeignKey("catalogue.embedding_configs.fingerprint"))

    characteristics: Mapped[list[KtruCharacteristic]] = relationship(
        back_populates="position", lazy="selectin", cascade="all, delete-orphan", passive_deletes=True,
    )


class KtruCharacteristic(Base):
    __tablename__ = "ktru_characteristic"
    __table_args__ = (
        ForeignKeyConstraint(
            ["import_sha256", "position_code"], ["catalogue.ktru_position.import_sha256", "catalogue.ktru_position.code"],
            ondelete="CASCADE", deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("(embedding IS NULL) = (embedding_config IS NULL)"),
    )

    import_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    position_code: Mapped[str] = mapped_column(Text, primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    is_numeric: Mapped[bool] = mapped_column(Boolean)
    choice: Mapped[str] = mapped_column(VALUE_CHOICE)
    required: Mapped[bool] = mapped_column(Boolean)
    actual: Mapped[bool] = mapped_column(Boolean)
    choice_type: Mapped[int | None] = mapped_column(SmallInteger)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    embedding_config: Mapped[str | None] = mapped_column(ForeignKey("catalogue.embedding_configs.fingerprint"))

    position: Mapped[KtruPosition] = relationship(back_populates="characteristics")
    values: Mapped[list[KtruValue]] = relationship(
        back_populates="characteristic", lazy="selectin", cascade="all, delete-orphan", passive_deletes=True,
        order_by="KtruValue.ordinal",
    )


class KtruValue(Base):
    __tablename__ = "ktru_value"
    __table_args__ = (
        UniqueConstraint("import_sha256", "position_code", "characteristic_code", "ordinal"),
        ForeignKeyConstraint(
            ["import_sha256", "position_code", "characteristic_code"],
            ["catalogue.ktru_characteristic.import_sha256", "catalogue.ktru_characteristic.position_code", "catalogue.ktru_characteristic.code"],
            ondelete="CASCADE", deferrable=True, initially="DEFERRED",
        ),
        CheckConstraint("ordinal >= 0"),
        CheckConstraint("text IS NULL OR spans IS NULL"),
        CheckConstraint("text IS NOT NULL OR spans IS NOT NULL OR issue IS NOT NULL"),
        CheckConstraint("spans IS NULL OR (array_ndims(spans) = 1 AND cardinality(spans) > 0 "
                        "AND array_position(spans, NULL) IS NULL AND NOT ('empty'::numrange = ANY(spans)))"),
        CheckConstraint("(embedding IS NULL) = (embedding_config IS NULL)"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    import_sha256: Mapped[str] = mapped_column(Text)
    position_code: Mapped[str] = mapped_column(Text)
    characteristic_code: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    code: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    spans: Mapped[list[Range] | None] = mapped_column(ARRAY(NUMRANGE))
    okei: Mapped[str | None] = mapped_column(ForeignKey("catalogue.okei.code", deferrable=True, initially="DEFERRED"))
    issue: Mapped[str | None] = mapped_column(Text)
    value_format: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    embedding_config: Mapped[str | None] = mapped_column(ForeignKey("catalogue.embedding_configs.fingerprint"))

    characteristic: Mapped[KtruCharacteristic] = relationship(back_populates="values")


class Workbook(Base):
    __tablename__ = "workbook"
    __table_args__ = (
        UniqueConstraint("import_sha256", "name"),
        ForeignKeyConstraint(
            ["import_sha256", "source_file_id"], ["catalogue.source_files.import_sha256", "catalogue.source_files.id"],
            deferrable=True, initially="DEFERRED",
        ),
    )

    import_sha256: Mapped[str] = mapped_column(ForeignKey("catalogue.catalogue_imports.sha256"), primary_key=True)
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    source_file_id: Mapped[int] = mapped_column(BigInteger)


class Kpgz(Base):
    __tablename__ = "kpgz"

    import_sha256: Mapped[str] = mapped_column(ForeignKey("catalogue.catalogue_imports.sha256"), primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)


class KpgzCharacteristic(Base):
    __tablename__ = "kpgz_characteristic"
    __table_args__ = (
        ForeignKeyConstraint(
            ["import_sha256", "kpgz_code"], ["catalogue.kpgz.import_sha256", "catalogue.kpgz.code"],
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["import_sha256", "src_workbook"], ["catalogue.workbook.import_sha256", "catalogue.workbook.id"],
            deferrable=True, initially="DEFERRED",
        ),
    )

    import_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kpgz_code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(SPGZ_ROLE)
    value_type: Mapped[str] = mapped_column(SPGZ_VTYPE)
    unit: Mapped[str | None] = mapped_column(Text)
    src_workbook: Mapped[int] = mapped_column(SmallInteger)
    src_row: Mapped[int] = mapped_column(Integer)


class KpgzValue(Base):
    __tablename__ = "kpgz_value"
    __table_args__ = (ForeignKeyConstraint(
        ["import_sha256", "characteristic_id"], ["catalogue.kpgz_characteristic.import_sha256", "catalogue.kpgz_characteristic.id"],
        deferrable=True, initially="DEFERRED",
    ),)

    import_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    characteristic_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, primary_key=True)


class SpgzRef(Base):
    __tablename__ = "spgz_ref"

    import_sha256: Mapped[str] = mapped_column(ForeignKey("catalogue.catalogue_imports.sha256"), primary_key=True)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class SpgzRefValue(Base):
    __tablename__ = "spgz_ref_value"
    __table_args__ = (ForeignKeyConstraint(
        ["import_sha256", "ref_id"], ["catalogue.spgz_ref.import_sha256", "catalogue.spgz_ref.id"],
        deferrable=True, initially="DEFERRED",
    ),)

    import_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    ref_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    text: Mapped[str] = mapped_column(Text, primary_key=True)


class KpgzCharacteristicRef(Base):
    __tablename__ = "kpgz_characteristic_ref"
    __table_args__ = (
        ForeignKeyConstraint(
            ["import_sha256", "characteristic_id"], ["catalogue.kpgz_characteristic.import_sha256", "catalogue.kpgz_characteristic.id"],
            deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["import_sha256", "ref_id"], ["catalogue.spgz_ref.import_sha256", "catalogue.spgz_ref.id"],
            deferrable=True, initially="DEFERRED",
        ),
    )

    import_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    characteristic_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class Ste(Base):
    __tablename__ = "ste"
    __table_args__ = (ForeignKeyConstraint(
        ["import_sha256", "src_workbook"], ["catalogue.workbook.import_sha256", "catalogue.workbook.id"],
        deferrable=True, initially="DEFERRED",
    ),)

    import_sha256: Mapped[str] = mapped_column(ForeignKey("catalogue.catalogue_imports.sha256"), primary_key=True)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    manufacturer: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[list[str]] = mapped_column(ARRAY(Text))
    src_workbook: Mapped[int] = mapped_column(SmallInteger)
    src_row: Mapped[int] = mapped_column(Integer)


Index("ktru_position_okpd2", KtruPosition.okpd2)
Index("ktru_position_parent_code", KtruPosition.parent_code)
Index("ktru_value_characteristic", KtruValue.import_sha256, KtruValue.position_code, KtruValue.characteristic_code)
for _model, _column in ((KtruPosition, "name"), (KtruCharacteristic, "name"), (KtruValue, "text")):
    Index(f"{_model.__tablename__}_trgm", _Norm(getattr(_model, _column)).label("normalized"),
          postgresql_using="gin", postgresql_ops={"normalized": "public.gin_trgm_ops"})
    Index(f"{_model.__tablename__}_embedding_hnsw", _model.embedding,
          postgresql_using="hnsw", postgresql_ops={"embedding": "public.vector_cosine_ops"})
Index("kpgz_characteristic_kpgz_code", KpgzCharacteristic.import_sha256, KpgzCharacteristic.kpgz_code)
Index("kpgz_characteristic_name", KpgzCharacteristic.name)
