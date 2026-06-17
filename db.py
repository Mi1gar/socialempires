"""
PostgreSQL connection with connection pooling.
Reads DATABASE_URL from environment, falls back to local dev defaults.
Uses psycopg2 directly — no ORM needed since we store JSONB.

When PostgreSQL is unavailable, falls back to JSON file storage
so the app works without any external database.
"""
import os
import json
import re

from psycopg2 import pool


# Module-level pool (lazy init)
_pool = None
_file_mode = False          # True when PostgreSQL is not available
_data_dir = "data"          # JSON file storage directory
_tables = {}                # In-memory tables: {table_name: [row_dict, ...]}
_next_ids = {}              # Auto-increment per table: {table_name: int}


def _init_file_store():
    """Load all tables from JSON files into memory. Create dir if needed."""
    global _tables, _file_mode
    if not os.path.exists(_data_dir):
        os.makedirs(_data_dir)
    for fname in os.listdir(_data_dir):
        if fname.endswith(".json"):
            tname = fname[:-5]  # remove .json
            try:
                with open(os.path.join(_data_dir, fname), "r", encoding="utf-8") as f:
                    rows = json.load(f)
                _tables[tname] = rows
                if rows:
                    # Restore auto-increment from max id
                    max_id = max((r.get("id", 0) for r in rows), default=0)
                    _next_ids[tname] = max_id + 1
            except Exception:
                _tables[tname] = []
            if tname not in _next_ids:
                _next_ids[tname] = 1
    _file_mode = True


def _save_table(table_name: str):
    """Persist a single table to its JSON file."""
    if not os.path.exists(_data_dir):
        os.makedirs(_data_dir)
    rows = _tables.get(table_name, [])
    fpath = os.path.join(_data_dir, f"{table_name}.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def _file_query(sql: str, params=None) -> list:
    """Minimal SQL parser for SELECT queries used in this app."""
    params = params or []

    # COUNT(*)
    m = re.match(r"SELECT\s+COUNT\(\*\)\s+AS\s+(\w+)\s+FROM\s+(\w+)", sql, re.IGNORECASE)
    if m:
        alias = m.group(1)
        table_name = m.group(2).lower()
        rows = _tables.get(table_name, [])
        return [{alias: len(rows)}]

    # Simple SELECT with WHERE col = %s
    m = re.match(
        r"SELECT\s+(.+?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(\w+)\s*=\s*%s)?(?:\s+ORDER BY.*)?$",
        sql, re.IGNORECASE | re.DOTALL,
    )
    if m:
        cols_str = m.group(1).strip()
        table_name = m.group(2).lower()
        where_col = m.group(3)
        rows = _tables.get(table_name, [])

        if where_col and params:
            param_val = str(params[0])
            rows = [r for r in rows if str(r.get(where_col, "")) == param_val]
        elif not where_col and params:
            # SELECT ... FROM users WHERE username != %s (exclude pattern)
            # Peek at the raw SQL
            if "!=" in sql or "<>" in sql:
                # Find the WHERE column with !=
                m2 = re.match(
                    r"SELECT\s+(.+?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(\w+)\s*!=\s*%s)(.*)$",
                    sql, re.IGNORECASE | re.DOTALL,
                )
                if m2:
                    where_col = m2.group(3)
                    param_val = str(params[0])
                    rows = [r for r in rows if str(r.get(where_col, "")) != param_val]

        # Expand * to all columns
        if cols_str == "*":
            return rows
        cols = [c.strip() for c in cols_str.split(",")]
        result = []
        for r in rows:
            out = {}
            for c in cols:
                if c in r:
                    out[c] = r[c]
                else:
                    out[c] = None  # column not present
            result.append(out)
        return result

    # Complex query: users LEFT JOIN player_saves (for get_all_players)
    if "LEFT JOIN" in sql.upper():
        # Return users joined with player_saves — simplified
        users = _tables.get("users", [])
        saves = {s.get("user_id"): s for s in _tables.get("player_saves", [])}
        result = []
        exclude = params[0] if params else None
        for u in users:
            if exclude and u.get("username") == exclude:
                continue
            s = saves.get(u.get("user_id"), {})
            save_data = s.get("save_data", {})
            if isinstance(save_data, str):
                try:
                    save_data = json.loads(save_data)
                except Exception:
                    save_data = {}
            maps = save_data.get("maps", [{}])
            player_info = save_data.get("playerInfo", {})
            map_names = player_info.get("map_names", ["Village"])
            result.append({
                "username": u.get("username"),
                "user_id": u.get("user_id"),
                "level": str(maps[0].get("level", "1")) if maps else "1",
                "xp": str(maps[0].get("xp", "0")) if maps else "0",
                "map_name": map_names[0] if map_names else "Village",
            })
        return result

    return []


def _file_execute(sql: str, params=None) -> int:
    """Minimal SQL executor for INSERT/UPDATE/DELETE used in this app."""
    params = params or []
    sql_norm = sql.strip()

    # CREATE TABLE IF NOT EXISTS — idempotent, ensure table list exists
    m = re.match(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)",
        sql_norm, re.IGNORECASE,
    )
    if m:
        table_name = m.group(1).lower()
        if table_name not in _tables:
            _tables[table_name] = []
            _next_ids[table_name] = 1
        return 0

    # INSERT INTO table (cols) VALUES (vals)
    m = re.match(
        r"INSERT\s+INTO\s+(\w+)\s*\((.+?)\)\s*VALUES\s*\((.+?)\)(?:\s+ON\s+CONFLICT.*DO\s+UPDATE.*)?$",
        sql_norm, re.IGNORECASE | re.DOTALL,
    )
    if m:
        table_name = m.group(1).lower()
        col_names = [c.strip() for c in m.group(2).split(",")]
        val_str = m.group(3)

        if table_name not in _tables:
            _tables[table_name] = []
            _next_ids[table_name] = 1

        # Parse value entries: %s placeholders vs SQL literals (NOW(), etc.)
        val_entries = [v.strip() for v in val_str.split(",")]

        # Build row dict — only consume params for %s placeholders
        row = {}
        param_idx = 0
        for i, col in enumerate(col_names):
            col_clean = col.strip()
            if col_clean.upper() in ("ID",):
                # SERIAL PRIMARY KEY
                row[col_clean] = _next_ids.get(table_name, 1)
                _next_ids[table_name] = _next_ids.get(table_name, 1) + 1
                continue

            # Check what the VALUES entry is for this column
            if i < len(val_entries):
                entry = val_entries[i].upper()
            else:
                entry = ""

            if entry in ("NOW()", "NULL", "DEFAULT"):
                row[col_clean] = "2026-06-17T00:00:00"
                continue

            # Otherwise it's a %s placeholder — consume a param
            if param_idx < len(params):
                val = params[param_idx]
                param_idx += 1
                if isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, ValueError):
                        pass
                row[col_clean] = val
            else:
                row[col_clean] = None

        if "ON CONFLICT" in sql_norm.upper():
            # UPSERT — replace existing row by primary/unique key
            pk_col = None
            pk_val = None
            # Try user_id first
            if "user_id" in row:
                pk_col = "user_id"
                pk_val = row["user_id"]
            elif "pid" in row:
                pk_col = "pid"
                pk_val = row["pid"]
            if pk_col and pk_val is not None:
                existing = [i for i, r in enumerate(_tables[table_name]) if r.get(pk_col) == pk_val]
                if existing:
                    _tables[table_name][existing[0]].update(row)
                    _save_table(table_name)
                    return 1
            # Also check SERIAL id
            row_id = _next_ids.get(table_name, 1)
            row["id"] = row_id
            _next_ids[table_name] = row_id + 1

        _tables[table_name].append(row)
        _save_table(table_name)
        return 1

    # UPDATE table SET col = %s, ... WHERE col = %s
    m = re.match(
        r"UPDATE\s+(\w+)\s+SET\s+(.+?)\s+WHERE\s+(.+)$",
        sql_norm, re.IGNORECASE | re.DOTALL,
    )
    if m:
        table_name = m.group(1).lower()
        set_clause = m.group(2)
        where_clause = m.group(3)
        rows = _tables.get(table_name, [])

        # Parse SET: col = %s (, col = %s)*
        set_pairs = re.findall(r"(\w+)\s*=\s*%s", set_clause)
        # Parse WHERE: col = %s
        wm = re.match(r"(\w+)\s*=\s*%s", where_clause.strip())
        if not wm:
            return 0
        where_col = wm.group(1)

        # params: first N are SET values, last one is WHERE value
        if len(params) >= len(set_pairs) + 1:
            set_vals = params[:len(set_pairs)]
            where_val = str(params[-1])
        else:
            return 0

        count = 0
        for r in rows:
            if str(r.get(where_col, "")) == where_val:
                for (col, _), val in zip(set_pairs, set_vals):
                    r[col] = val
                count += 1
        if count:
            _save_table(table_name)
        return count

    return 0


def _get_pool():
    """Get or create the connection pool. Singleton pattern.
    Falls back to file-based storage when PostgreSQL is unavailable.
    """
    global _pool, _file_mode
    if _file_mode:
        return None  # File mode, no pool needed
    if _pool is not None:
        return _pool

    database_url = os.environ.get("DATABASE_URL", "")
    try:
        if database_url:
            _pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=4,
                dsn=database_url,
            )
        else:
            _pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=4,
                host=os.environ.get("DB_HOST", "localhost"),
                port=int(os.environ.get("DB_PORT", "5432")),
                dbname=os.environ.get("DB_NAME", "social_emperors"),
                user=os.environ.get("DB_USER", "postgres"),
                password=os.environ.get("DB_PASSWORD", ""),
            )
        # Test connection
        conn = _pool.getconn()
        _pool.putconn(conn)
        return _pool
    except Exception as e:
        print(f"[db] PostgreSQL unavailable ({e}), switching to file-based storage.")
        _pool = None
        _file_mode = True
        _init_file_store()
        return None


def query(sql, params=None):
    """Run a SELECT query and return results as list of dicts."""
    if _file_mode or _pool is None:
        p = _get_pool()
        if _file_mode:
            return _file_query(sql, params)

    p = _get_pool()
    if p is None:
        return _file_query(sql, params)

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
    """Run an INSERT/UPDATE/DELETE and return affected row count."""
    if _file_mode or _pool is None:
        p = _get_pool()
        if _file_mode:
            return _file_execute(sql, params)

    p = _get_pool()
    if p is None:
        return _file_execute(sql, params)

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
    """Run executemany for batch INSERT/UPDATE."""
    if _file_mode or _pool is None:
        # Fallback: run execute one at a time
        total = 0
        for p in params_list:
            total += _file_execute(sql, p)
        return total

    p = _get_pool()
    if p is None:
        total = 0
        for pm in params_list:
            total += _file_execute(sql, pm)
        return total

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
