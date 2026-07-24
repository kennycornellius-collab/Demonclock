"""A tiny JSON-Schema-SUBSET validator -- not a general-purpose implementation
(no $ref, no oneOf/anyOf, no format/pattern). Every schema this project
declares is a flat-ish "object with typed properties" shape (SPEC.md §1's
structured-output requirement), so this covers exactly what's needed rather
than pulling in a third-party jsonschema dependency for a handful of keyword
checks (the project is deliberately zero third-party dependencies, per
CLAUDE.md's stack decision).

Supported keywords: type (object/string/integer/number/boolean/array/null),
properties, required, items, enum. Anything else in a schema dict is ignored
rather than rejected, so callers can still document extra hints (e.g.
"description") without this validator tripping on them.

Step 8 P6: the "integer" check accepts a whole-number float (e.g. `5.0`) as
well as a real `int` — JSON itself doesn't distinguish int/float, only
Python's parsed representation does, so a provider that serializes an
integer-typed field as `5.0` is still schema-valid, not "malformed." A
non-whole float (`5.5`) still correctly fails — this only widens what
counts as an integer, it doesn't loosen "number" into accepting non-integer
values for an "integer"-typed field. Confirmed against a real (not
monkeypatched) Gemini call — see progress.md's Step 8 P6 entry.
"""
from __future__ import annotations

def _is_integer(v: object) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and v.is_integer()


_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "string": lambda v: isinstance(v, str),
    "integer": _is_integer,
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def matches_schema(value: object, schema: dict) -> bool:
    """True if `value` structurally matches `schema`. Never raises -- a
    malformed schema or an unexpected value both simply fail the match,
    since the only thing a caller does with the result is decide "retry or
    discard" (SPEC.md §1)."""
    try:
        return _matches(value, schema)
    except (TypeError, KeyError):
        return False


def _matches(value: object, schema: dict) -> bool:
    expected_type = schema.get("type")
    if expected_type is not None:
        check = _TYPE_CHECKS.get(expected_type)
        if check is None or not check(value):
            return False

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        return False

    if expected_type == "object" or (expected_type is None and isinstance(value, dict)):
        if not isinstance(value, dict):
            return False
        for required_key in schema.get("required", []):
            if required_key not in value:
                return False
        properties = schema.get("properties", {})
        for key, sub_schema in properties.items():
            if key in value and not _matches(value[key], sub_schema):
                return False

    if expected_type == "array" or (expected_type is None and isinstance(value, list)):
        if not isinstance(value, list):
            return False
        item_schema = schema.get("items")
        if item_schema is not None:
            for item in value:
                if not _matches(item, item_schema):
                    return False

    return True
