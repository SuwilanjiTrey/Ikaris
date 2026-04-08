"""
firestoreUtil.py — Hybrid SQL ↔ Firestore query translator.

Supports:
  • Native Firestore path syntax  (e.g. "users", "users/abc123", "users/abc123/orders")
  • SQL-style SELECT / INSERT / UPDATE / DELETE / COUNT with full WHERE / ORDER BY / LIMIT
  • Optional parameters passed as a dict alongside the query string

SQL syntax reference
────────────────────
SELECT  * | field1, field2  FROM collection [WHERE …] [ORDER BY field [ASC|DESC]] [LIMIT n]
COUNT(*)                    FROM collection [WHERE …]
INSERT  INTO collection (f1, f2, …) VALUES (v1, v2, …)
UPDATE  collection SET f1=v1, f2=v2 WHERE …
DELETE  FROM collection WHERE …

Native Firestore path examples
───────────────────────────────
  users                         → list all docs in collection "users"
  users/abc123                  → fetch single document  users/abc123
  users/abc123/orders           → list sub-collection
  users/abc123/orders/ord99     → fetch single sub-document

WHERE operator support
───────────────────────
  =  ==  !=  >  <  >=  <=  IN  NOT IN  LIKE  ARRAY_CONTAINS  ARRAY_CONTAINS_ANY
"""

from __future__ import annotations
import re
from typing import Any


# ── Operator mapping ──────────────────────────────────────────────────────────

_SQL_TO_FS: dict[str, str] = {
    "=":                  "==",
    "==":                 "==",
    "!=":                 "!=",
    ">":                  ">",
    "<":                  "<",
    ">=":                 ">=",
    "<=":                 "<=",
    "IN":                 "in",
    "NOTIN":              "not-in",
    "NOT_IN":             "not-in",
    "LIKE":               "array-contains",
    "ARRAY_CONTAINS":     "array-contains",
    "ARRAY_CONTAINS_ANY": "array-contains-any",
}


def _cast_value(raw: str) -> Any:
    """Cast a raw string token to an appropriate Python type."""
    if raw is None:
        return None
    stripped = raw.strip()
    low = stripped.lower()
    if low == "null":
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if re.match(r"^-?\d+$", stripped):
        return int(stripped)
    if re.match(r"^-?\d+\.\d+$", stripped):
        return float(stripped)
    return stripped


def _parse_value_token(token: str) -> Any:
    """Strip surrounding quotes then cast."""
    t = token.strip()
    if (t.startswith('"') and t.endswith('"')) or \
       (t.startswith("'") and t.endswith("'")):
        return t[1:-1]
    return _cast_value(t)


def _parse_value_list(raw: str) -> list:
    """Parse  (val1, val2, 'val3')  into a list of values."""
    inner = raw.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    return [_parse_value_token(v) for v in _csv_split(inner)]


def _csv_split(s: str) -> list:
    """Split by comma, respecting single/double quotes."""
    parts, current, in_q, q_char = [], [], False, None
    for ch in s:
        if in_q:
            current.append(ch)
            if ch == q_char:
                in_q = False
        elif ch in ('"', "'"):
            in_q, q_char = True, ch
            current.append(ch)
        elif ch == ",":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return parts


def _parse_where(where_str: str):
    """
    Parse a WHERE clause into [(field, fs_operator, value), …].
    Returns a list on success, or a dict with 'error' key on failure.
    Supports AND-chained conditions (Firestore does not support OR).
    """
    conditions = []
    parts = re.split(r"\bAND\b", where_str, flags=re.IGNORECASE)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Multi-value: field IN (...) / NOT IN (...) / ARRAY_CONTAINS_ANY (...)
        m = re.match(
            r"(\w+)\s+(NOT\s+IN|IN|ARRAY_CONTAINS_ANY)\s*(\(.*?\))",
            part, re.IGNORECASE | re.DOTALL
        )
        if m:
            field, op, val_raw = m.groups()
            op_key = re.sub(r"\s+", "_", op.upper().strip())
            fs_op = _SQL_TO_FS.get(op_key, "in")
            value = _parse_value_list(val_raw)
            conditions.append((field, fs_op, value))
            continue

        # Single-value operators
        m = re.match(
            r"(\w+)\s*(==|!=|>=|<=|>|<|=|LIKE|ARRAY_CONTAINS)\s*"
            r"(?:\"([^\"]*)\"|'([^']*)'|(\S+))",
            part, re.IGNORECASE
        )
        if m:
            field, op, dq_val, sq_val, raw_val = m.groups()
            value = dq_val if dq_val is not None else (sq_val if sq_val is not None else raw_val)
            op_key = op.upper().strip()
            fs_op = _SQL_TO_FS.get(op_key, op)
            conditions.append((field, fs_op, _cast_value(value)))
            continue

        return {"error": f"Unrecognised WHERE condition: '{part}'"}

    return conditions


def _parse_order_by(order_str: str) -> list:
    order_by = []
    for part in order_str.split(","):
        part = part.strip()
        if " " in part:
            field, direction = part.rsplit(" ", 1)
            direction = direction.upper() if direction.upper() in ("ASC", "DESC") else "ASC"
        else:
            field, direction = part, "ASC"
        order_by.append((field.strip(), direction))
    return order_by


# ── Main translator class ─────────────────────────────────────────────────────

class SQLToFirestoreTranslator:
    """
    Translates SQL-like queries OR native Firestore path strings into a
    unified parameter dict consumed by FirestoreConnectionManager.

    Return schema
    ─────────────
    {
        'collection':       str,
        'document_id':      str | None,   # targets a specific document
        'subcollection':    str | None,
        'sub_document_id':  str | None,
        'operation':        str,          # select|insert|update|delete|count
        'fields':           list[str],    # SELECT fields (empty = all)
        'values':           list,         # INSERT values
        'multi_insert':     list[list],   # multi-row INSERT
        'set_conditions':   dict,         # UPDATE SET payload
        'where_conditions': list[tuple],  # [(field, op, value), …]
        'limit':            int,
        'order_by':         list[tuple],  # [(field, 'ASC'|'DESC'), …]
        'error':            str,          # only on failure
    }
    """

    def translate(self, query: str, params: dict = None) -> dict:
        """
        Translate *query* and merge optional *params*.

        params keys (all optional):
          collection, document_id, subcollection, sub_document_id,
          where (list of tuples), order_by (list of tuples),
          limit (int), fields (list), set_conditions (dict), values (list)
        """
        query = (query or "").strip()
        params = params or {}

        if not query and not params:
            return {"error": "Empty query"}

        base = {
            "collection":      params.get("collection", ""),
            "document_id":     params.get("document_id"),
            "subcollection":   params.get("subcollection"),
            "sub_document_id": params.get("sub_document_id"),
            "operation":       "select",
            "fields":          list(params.get("fields") or []),
            "values":          list(params.get("values") or []),
            "multi_insert":    [],
            "set_conditions":  dict(params.get("set_conditions") or {}),
            "where_conditions": list(params.get("where") or []),
            "limit":           int(params.get("limit", 100)),
            "order_by":        list(params.get("order_by") or []),
        }

        # Native Firestore path (no SQL keyword at the start)
        if query and not re.match(
            r"^\s*(SELECT|INSERT|UPDATE|DELETE|COUNT)\b", query, re.IGNORECASE
        ):
            return self._parse_native_path(query, base)

        # SQL path
        if query:
            parsed = self._parse_sql(query)
            if "error" in parsed:
                return parsed
            # SQL fields win over params for overlapping keys
            for k, v in parsed.items():
                if v or k in ("operation", "limit"):
                    base[k] = v

        return base

    # ── Native path ───────────────────────────────────────────────────────────

    def _parse_native_path(self, path: str, base: dict) -> dict:
        """
        Parse a Firestore-style path up to 4 segments deep:
          users                      collection=users
          users/abc123               + document_id=abc123
          users/abc123/orders        + subcollection=orders
          users/abc123/orders/ord99  + sub_document_id=ord99
        """
        segments = [s for s in path.strip("/").split("/") if s]
        result = dict(base)
        result["operation"] = "select"

        n = len(segments)
        if n == 1:
            result["collection"] = segments[0]
        elif n == 2:
            result["collection"]  = segments[0]
            result["document_id"] = segments[1]
        elif n == 3:
            result["collection"]    = segments[0]
            result["document_id"]   = segments[1]
            result["subcollection"] = segments[2]
        elif n == 4:
            result["collection"]      = segments[0]
            result["document_id"]     = segments[1]
            result["subcollection"]   = segments[2]
            result["sub_document_id"] = segments[3]
        else:
            result["error"] = f"Path too deep (max 4 segments): '{path}'"

        return result

    # ── SQL dispatcher ────────────────────────────────────────────────────────

    def _parse_sql(self, query: str) -> dict:
        upper = query.upper().lstrip()
        if upper.startswith("SELECT"):
            return self._parse_select(query)
        if upper.startswith("COUNT"):
            return self._parse_count(query)
        if upper.startswith("INSERT"):
            return self._parse_insert(query)
        if upper.startswith("UPDATE"):
            return self._parse_update(query)
        if upper.startswith("DELETE"):
            return self._parse_delete(query)
        return {"error": "Unsupported operation. Use SELECT, COUNT, INSERT, UPDATE, or DELETE."}

    # ── SELECT ────────────────────────────────────────────────────────────────

    def _parse_select(self, query: str) -> dict:
        pattern = (
            r"SELECT\s+(.*?)\s+FROM\s+(\w+)"
            r"(?:\s+WHERE\s+(.*?))?"
            r"(?:\s+ORDER\s+BY\s+(.*?))?"
            r"(?:\s+LIMIT\s+(\d+))?"
            r"\s*;?\s*$"
        )
        m = re.match(pattern, query, re.IGNORECASE | re.DOTALL)
        if not m:
            return {"error": "Invalid SELECT. Use: SELECT * FROM table [WHERE …] [ORDER BY …] [LIMIT n]"}

        sel_raw, table, where_raw, order_raw, limit_raw = m.groups()
        fields = [] if sel_raw.strip() == "*" else [f.strip() for f in sel_raw.split(",") if f.strip()]

        where_conditions = []
        if where_raw:
            result = _parse_where(where_raw.strip())
            if isinstance(result, dict):
                return result
            where_conditions = result

        return {
            "collection":      table,
            "document_id":     None,
            "subcollection":   None,
            "sub_document_id": None,
            "operation":       "select",
            "fields":          fields,
            "values":          [],
            "multi_insert":    [],
            "set_conditions":  {},
            "where_conditions": where_conditions,
            "limit":           int(limit_raw) if limit_raw else 100,
            "order_by":        _parse_order_by(order_raw.strip()) if order_raw else [],
        }

    # ── COUNT ─────────────────────────────────────────────────────────────────

    def _parse_count(self, query: str) -> dict:
        pattern = r"COUNT\s*\(\s*\*\s*\)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.*?))?\s*;?\s*$"
        m = re.match(pattern, query, re.IGNORECASE | re.DOTALL)
        if not m:
            return {"error": "Invalid COUNT. Use: COUNT(*) FROM table [WHERE …]"}

        table, where_raw = m.groups()
        where_conditions = []
        if where_raw:
            result = _parse_where(where_raw.strip())
            if isinstance(result, dict):
                return result
            where_conditions = result

        return {
            "collection":      table,
            "document_id":     None,
            "subcollection":   None,
            "sub_document_id": None,
            "operation":       "count",
            "fields":          [],
            "values":          [],
            "multi_insert":    [],
            "set_conditions":  {},
            "where_conditions": where_conditions,
            "limit":           0,
            "order_by":        [],
        }

    # ── INSERT ────────────────────────────────────────────────────────────────

    def _parse_insert(self, query: str) -> dict:
        pattern = (
            r"INSERT\s+INTO\s+(\w+)\s*"
            r"\((.*?)\)\s*VALUES\s*((?:\s*\(.*?\)\s*,?\s*)+)"
        )
        m = re.match(pattern, query, re.IGNORECASE | re.DOTALL)
        if not m:
            return {"error": "Invalid INSERT. Use: INSERT INTO table (f1, f2) VALUES (v1, v2)"}

        table, fields_raw, values_block = m.groups()
        fields = [f.strip() for f in _csv_split(fields_raw)]

        value_groups = re.findall(r"\((.*?)\)", values_block, re.DOTALL)
        all_rows = []
        for grp in value_groups:
            row = [_parse_value_token(v) for v in _csv_split(grp)]
            if len(row) != len(fields):
                return {"error": f"Field/value count mismatch: {len(fields)} fields vs {len(row)} values."}
            all_rows.append(row)

        if not all_rows:
            return {"error": "No VALUES found in INSERT statement."}

        return {
            "collection":      table,
            "document_id":     None,
            "subcollection":   None,
            "sub_document_id": None,
            "operation":       "insert",
            "fields":          fields,
            "values":          all_rows[0] if len(all_rows) == 1 else all_rows,
            "multi_insert":    all_rows,
            "set_conditions":  {},
            "where_conditions": [],
            "limit":           0,
            "order_by":        [],
        }

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def _parse_update(self, query: str) -> dict:
        pattern = r"UPDATE\s+(\w+)\s+SET\s+(.*?)\s+WHERE\s+(.*?)\s*;?\s*$"
        m = re.match(pattern, query, re.IGNORECASE | re.DOTALL)
        if not m:
            return {"error": "Invalid UPDATE. Use: UPDATE table SET f1=v1 WHERE condition"}

        table, set_raw, where_raw = m.groups()

        set_conditions = {}
        for part in _csv_split(set_raw):
            if "=" not in part:
                return {"error": f"Invalid SET clause: '{part}'"}
            key, _, val_raw = part.partition("=")
            set_conditions[key.strip()] = _parse_value_token(val_raw.strip())

        result = _parse_where(where_raw.strip())
        if isinstance(result, dict):
            return result

        return {
            "collection":      table,
            "document_id":     None,
            "subcollection":   None,
            "sub_document_id": None,
            "operation":       "update",
            "fields":          [],
            "values":          [],
            "multi_insert":    [],
            "set_conditions":  set_conditions,
            "where_conditions": result,
            "limit":           0,
            "order_by":        [],
        }

    # ── DELETE ────────────────────────────────────────────────────────────────

    def _parse_delete(self, query: str) -> dict:
        pattern = r"DELETE\s+FROM\s+(\w+)\s+WHERE\s+(.*?)\s*;?\s*$"
        m = re.match(pattern, query, re.IGNORECASE | re.DOTALL)
        if not m:
            return {"error": "Invalid DELETE. Use: DELETE FROM table WHERE condition"}

        table, where_raw = m.groups()
        result = _parse_where(where_raw.strip())
        if isinstance(result, dict):
            return result

        return {
            "collection":      table,
            "document_id":     None,
            "subcollection":   None,
            "sub_document_id": None,
            "operation":       "delete",
            "fields":          [],
            "values":          [],
            "multi_insert":    [],
            "set_conditions":  {},
            "where_conditions": result,
            "limit":           0,
            "order_by":        [],
        }
