import sqlite3
from dataclasses import dataclass
from typing import List, Dict, Set
import sqlparse
import sqlglot
from sqlglot import exp
from db_engine import get_readonly_connection, get_real_schema

FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create",
    "attach", "pragma", "replace", "vacuum", "reindex", "detach",
    "load_extension", "exec", "execute"
}

FORBIDDEN_AST_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop,
    exp.Alter, exp.Create, exp.Command
)


@dataclass
class ValidationResult:
    is_valid: bool
    summary: str
    error_message: str = ""
    dry_run_plan: List[str] = None
    verified_tables: List[str] = None


def validate_sql(sql: str) -> ValidationResult:
    if not sql or not sql.strip():
        return ValidationResult(False, "Empty SQL", "Generated SQL is empty.")

    parsed_stmts = [s for s in sqlparse.parse(sql.strip()) if str(s).strip() and str(s).strip() != ";"]
    if len(parsed_stmts) != 1:
        return ValidationResult(False, "Multiple statements rejected", "Only a single SQL statement is allowed.")

    stmt = parsed_stmts[0]
    tokens = [t.value.lower() for t in stmt.flatten() if not t.is_whitespace]

    for tok in tokens:
        if tok in FORBIDDEN_KEYWORDS:
            return ValidationResult(False, f"Forbidden keyword: {tok.upper()}", f"Forbidden keyword detected: {tok.upper()}")

    if not tokens or tokens[0] not in ("select", "with"):
        return ValidationResult(False, "Non-SELECT rejected", "Query must start with SELECT or WITH ... SELECT.")

    real_schema: Dict[str, List[str]] = get_real_schema()
    real_tables_lower: Dict[str, str] = {t.lower(): t for t in real_schema.keys()}

    try:
        ast = sqlglot.parse_one(sql, read="sqlite")
    except Exception as e:
        return ValidationResult(False, "AST Parse Error", f"SQL syntax error: {str(e)}")

    for node in ast.walk():
        if isinstance(node, FORBIDDEN_AST_NODES):
            return ValidationResult(False, "Forbidden AST Node", f"Disallowed operation in AST: {type(node).__name__}")

    if not isinstance(ast, (exp.Select, exp.Union, exp.Subquery)):
        return ValidationResult(False, "Invalid Root AST", "Root statement must be a SELECT query.")

    cte_names: Set[str] = set()
    for cte in ast.find_all(exp.CTE):
        if cte.alias:
            cte_names.add(cte.alias.lower())

    used_real_tables = []
    for tbl in ast.find_all(exp.Table):
        tbl_name = tbl.name.lower()
        if not tbl_name or tbl_name in cte_names:
            continue
        if tbl_name not in real_tables_lower:
            return ValidationResult(
                False,
                "Schema Check Failed",
                f"Table or view '{tbl.name}' does not exist in schema.sql."
            )
        used_real_tables.append(real_tables_lower[tbl_name])

    conn = get_readonly_connection()
    dry_plan = []
    try:
        cursor = conn.cursor()
        cursor.execute(f"EXPLAIN QUERY PLAN {sql}")
        plan_rows = cursor.fetchall()
        dry_plan = [f"{r['detail']}" if 'detail' in r.keys() else str(tuple(r)) for r in plan_rows]
    except sqlite3.Error as e:
        return ValidationResult(
            False,
            "Dry-Run Failed",
            f"SQLite schema/dry-run error: {str(e)}",
            verified_tables=list(set(used_real_tables))
        )
    finally:
        conn.close()

    return ValidationResult(
        is_valid=True,
        summary="read-only SELECT ✓ schema check ✓ dry-run ✓",
        dry_run_plan=dry_plan,
        verified_tables=sorted(list(set(used_real_tables)))
    )