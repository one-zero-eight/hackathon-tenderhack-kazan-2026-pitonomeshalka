-- Snapshot-only domains; eligibility is evaluated by the reader, not cached.
CREATE MATERIALIZED VIEW {catalogue_schema}.ktru_family_splits AS
WITH siblings AS (
    SELECT child.import_sha256, child.code, parent.code AS parent_code,
           parent.version AS parent_version, parent.name AS parent_name,
           count(*) OVER (PARTITION BY child.import_sha256, parent.code, parent.version) AS child_count
    FROM {catalogue_schema}.ktru_position child
    JOIN {catalogue_schema}.ktru_position parent
      ON parent.import_sha256 = child.import_sha256 AND parent.code = child.parent_code
     AND parent.version = child.parent_version AND parent.is_template
    WHERE NOT child.is_template
), characteristics AS (
    SELECT sibling.*, c.code AS characteristic_code, c.name,
           {catalogue_schema}.norm(c.name) AS name_key, c.is_numeric, c.choice, c.required,
           coalesce(pc.required, false) AS parent_required
    FROM siblings sibling
    JOIN {catalogue_schema}.ktru_characteristic c
      ON c.import_sha256 = sibling.import_sha256 AND c.position_code = sibling.code AND c.actual
    LEFT JOIN {catalogue_schema}.ktru_characteristic pc
      ON pc.import_sha256 = sibling.import_sha256 AND pc.position_code = sibling.parent_code
     AND pc.code = c.code AND {catalogue_schema}.norm(pc.name) = {catalogue_schema}.norm(c.name)
     AND pc.actual
), value_rows AS (
    SELECT c.import_sha256, c.code, c.characteristic_code,
           jsonb_build_object(
               'text', {catalogue_schema}.norm(v.text), 'spans', union_ranges.spans, 'okei', v.okei,
               'invalid', v.issue IS NOT NULL OR
                   CASE WHEN c.is_numeric THEN coalesce(cardinality(v.spans), 0) = 0
                        ELSE coalesce({catalogue_schema}.norm(v.text), '') = '' END
           ) AS signature,
           jsonb_build_object('text', v.text, 'spans', ranges.display_spans,
                              'okei', v.okei, 'issue', v.issue) AS value
    FROM characteristics c
    JOIN {catalogue_schema}.ktru_value v
      ON v.import_sha256 = c.import_sha256 AND v.position_code = c.code
     AND v.characteristic_code = c.characteristic_code
    CROSS JOIN LATERAL (
        SELECT array_agg(canonical ORDER BY canonical) AS spans,
               jsonb_agg(jsonb_build_object(
                   'lower', lower(canonical)::text, 'upper', upper(canonical)::text,
                   'bounds', (CASE WHEN lower_inc(canonical) THEN '[' ELSE '(' END) ||
                             (CASE WHEN upper_inc(canonical) THEN ']' ELSE ')' END),
                   'empty', isempty(canonical)
               ) ORDER BY canonical) AS display_spans
        FROM (
            SELECT DISTINCT numrange(trim_scale(lower(span)), trim_scale(upper(span)),
                (CASE WHEN lower_inc(span) THEN '[' ELSE '(' END) ||
                (CASE WHEN upper_inc(span) THEN ']' ELSE ')' END)) AS canonical
            FROM unnest(v.spans) span
        ) ordered
    ) ranges
    CROSS JOIN LATERAL (
        -- Union only within this XML value group; choice boundaries stay intact.
        SELECT array_agg(span::text ORDER BY span) AS spans
        FROM unnest((SELECT range_agg(span) FROM unnest(ranges.spans) span)) span
    ) union_ranges
), distinct_values AS (
    -- Raw wording is retained for display; duplicate normalized values are not constraints.
    SELECT DISTINCT ON (import_sha256, code, characteristic_code, signature) *
    FROM value_rows
    ORDER BY import_sha256, code, characteristic_code, signature, value::text
), domains AS (
    SELECT c.import_sha256, c.parent_code, c.parent_version, c.parent_name, c.child_count,
           c.code, c.characteristic_code, c.name, c.name_key, c.is_numeric, c.choice,
           c.required, c.parent_required,
           coalesce(jsonb_agg(v.value ORDER BY v.signature)
                    FILTER (WHERE v.signature IS NOT NULL), '[]'::jsonb) AS values,
           jsonb_build_object('choice', c.choice, 'is_numeric', c.is_numeric,
               'values', coalesce(jsonb_agg(v.signature ORDER BY v.signature)
                                 FILTER (WHERE v.signature IS NOT NULL), '[]'::jsonb)) AS domain
    FROM characteristics c
    LEFT JOIN distinct_values v
      ON v.import_sha256 = c.import_sha256 AND v.code = c.code
     AND v.characteristic_code = c.characteristic_code
    GROUP BY c.import_sha256, c.parent_code, c.parent_version, c.parent_name, c.child_count,
             c.code, c.characteristic_code, c.name, c.name_key, c.is_numeric, c.choice,
             c.required, c.parent_required
), variants AS (
    SELECT import_sha256, parent_code, parent_version, parent_name, child_count,
           characteristic_code, name_key, min(name) AS name, is_numeric, choice, required,
           bool_or(parent_required) AS parent_required, domain, count(*) AS member_count,
           jsonb_build_object('children', jsonb_agg(code ORDER BY code),
                              'values', min(values::text)::jsonb, 'choice', choice,
                              'required', required, 'is_numeric', is_numeric) AS variant
    FROM domains
    GROUP BY import_sha256, parent_code, parent_version, parent_name, child_count,
             characteristic_code, name_key, is_numeric, choice, required, domain
)
SELECT import_sha256, parent_code, parent_version, parent_name, characteristic_code, name_key,
       min(name) AS name, bool_or(is_numeric) AS is_numeric,
       bool_or(required OR parent_required) AS required, bool_or(parent_required) AS parent_required,
       jsonb_agg(variant ORDER BY domain, required) AS variants,
       jsonb_agg(domain ORDER BY domain, required) AS domain_signatures
FROM variants
GROUP BY import_sha256, parent_code, parent_version, parent_name, child_count,
         characteristic_code, name_key
HAVING count(DISTINCT domain) > 1 OR sum(member_count) < child_count
WITH DATA;

CREATE UNIQUE INDEX ktru_family_splits_family_characteristic
    ON {catalogue_schema}.ktru_family_splits
       (import_sha256, parent_code, parent_version, characteristic_code, name_key);

CREATE INDEX ktru_position_family
    ON {catalogue_schema}.ktru_position (import_sha256, parent_code, parent_version, code);

COMMENT ON COLUMN {catalogue_schema}.ktru_family_splits.domain_signatures IS
    'Normalized constraint signatures aligned with variants; required is not a domain difference.';
