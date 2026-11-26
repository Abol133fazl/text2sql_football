import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple
from config import DB_PATH, MAX_ROWS, QUERY_TIMEOUT_SEC


def get_readonly_connection() -> sqlite3.Connection:
    
    db_uri = Path(DB_PATH).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def execute_query(sql: str, row_limit: int = MAX_ROWS, timeout_sec: float = QUERY_TIMEOUT_SEC) -> Tuple[List[str], List[Dict[str, Any]], int, float]:
    
    conn = get_readonly_connection()
    start_time = time.perf_counter()

    def progress_handler() -> int:
        if (time.perf_counter() - start_time) > timeout_sec:
            return 1
        return 0

    try:
        conn.set_progress_handler(progress_handler, 10000)
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(row_limit)
        dict_rows = [dict(row) for row in rows]
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return columns, dict_rows, len(dict_rows), elapsed_ms
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


def get_real_schema() -> Dict[str, List[str]]:
    
    schema_map: Dict[str, List[str]] = {}
    conn = get_readonly_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'")
        objects = [row[0] for row in cursor.fetchall()]

        for obj in objects:
            try:
                cursor.execute(f'SELECT * FROM "{obj}" LIMIT 0')
                cols = [desc[0] for desc in cursor.description] if cursor.description else []
                schema_map[obj] = cols
            except sqlite3.Error:
                continue
        return schema_map
    finally:
        conn.close()


def get_team_reference_list() -> str:
    
    conn = get_readonly_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM team")
        rows = [dict(r) for r in cursor.fetchall()]
        if not rows:
            return ""
        lines = []
        for r in rows:
            parts = [f"{k}={v}" for k, v in r.items() if v is not None]
            lines.append(" | ".join(parts))
        return "\n".join(lines)
    except sqlite3.Error:
        return ""
    finally:
        conn.close()