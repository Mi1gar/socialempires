"""
PostgreSQL connection with connection pooling.
Reads DATABASE_URL from environment, falls back to local dev defaults.
Uses psycopg2 directly — no ORM needed since we store JSONB.
"""
import os
import json

from psycopg2 import pool


# Module-level pool (lazy init)
_pool = None


def _get_pool():
    """Get or create the connection pool. Singleton pattern."""
    global _pool
    if _pool is None:
        database_url = os.environ.get("DATABASE_URL", "")
        if database_url:
            _pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=4,
                dsn=database_url,
            )
        else:
            # Local dev fallback
            _pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=4,
                host=os.environ.get("DB_HOST", "localhost"),
                port=int(os.environ.get("DB_PORT", "5432")),
                dbname=os.environ.get("DB_NAME", "social_emperors"),
                user=os.environ.get("DB_USER", "postgres"),
                password=os.environ.get("DB_PASSWORD", ""),
            )
    return _pool


def query(sql, params=None):
    """Run a SELECT query and return results as list of dicts.

    Args:
        sql: SQL query string with %s placeholders
        params: List of parameter values

    Returns:
        List of dicts, each dict is one row (column_name -> value).
        JSONB columns are already decoded to Python dicts.
    """
    p = _get_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if cur.description is None:
                return []
            columns = [desc[0] for desc in cur.description]
            rows = []
            for row in cur.fetchall():
                d = {}
                for col, val in zip(columns, row):
                    # psycopg2 auto-decodes JSONB -> dict, but only if the value
                    # came from a JSONB column. If it's a plain string (text column
                    # that contains JSON), we decode it manually.
                    if isinstance(val, str) and (val.startswith('{') or val.startswith('[')):
                        try:
                            d[col] = json.loads(val)
                        except (json.JSONDecodeError, ValueError):
                            d[col] = val
                    else:
                        d[col] = val
                rows.append(d)
            return rows
    finally:
        p.putconn(conn)


def execute(sql, params=None):
    """Run an INSERT/UPDATE/DELETE and return affected row count.

    Args:
        sql: SQL query string with %s placeholders
        params: List of parameter values

    Returns:
        Number of rows affected.
    """
    p = _get_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            conn.commit()
            return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def execute_many(sql, params_list):
    """Run executemany for batch INSERT/UPDATE.

    Args:
        sql: SQL query string with %s placeholders
        params_list: List of parameter lists

    Returns:
        Number of rows affected (sum across all executions).
    """
    p = _get_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, params_list)
            conn.commit()
            return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def create_tables():
    """Create database tables if they don't exist. Idempotent."""
    execute("""
        CREATE TABLE IF NOT EXISTS player_saves (
            user_id     TEXT PRIMARY KEY,
            save_data   JSONB NOT NULL,
            created_at  TIMESTAMP DEFAULT NOW(),
            updated_at  TIMESTAMP DEFAULT NOW()
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS static_villages (
            pid   TEXT PRIMARY KEY,
            data  JSONB NOT NULL
        )
    """)
