import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from . import config

def now_utc_dt() -> datetime:
    return datetime.now(timezone.utc)

def now_utc_str() -> str:
    return now_utc_dt().strftime("%Y-%m-%d %H:%M:%S")

@asynccontextmanager
async def get_db():
    conn = await aiosqlite.connect(config.DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode = WAL;")
    try:
        yield conn
    finally:
        await conn.close()

@asynccontextmanager
async def get_write_db():
    conn = await aiosqlite.connect(config.DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode = WAL;")
    await conn.execute("PRAGMA busy_timeout = 5000;")
    try:
        yield conn
    finally:
        await conn.close()

async def init_db():
    async with get_write_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE NOT NULL,
                email TEXT,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                sub_plan TEXT DEFAULT 'none',
                sub_expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_user_bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                web_user_id INTEGER NOT NULL,
                bot_token TEXT NOT NULL,
                bot_id INTEGER,
                bot_username TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                web_user_id INTEGER NOT NULL,
                nft_name TEXT NOT NULL,
                nft_number TEXT NOT NULL,
                stars_amount INTEGER NOT NULL,
                recipient TEXT,
                deal_link TEXT,
                status TEXT DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()

async def web_register_user(login: str, password_hash: str, email: Optional[str] = None) -> tuple[bool, Optional[Dict[str, Any]], str]:
    clean_login = login.strip().lower()
    async with get_write_db() as db:
        async with db.execute("SELECT id FROM web_users WHERE LOWER(login) = ?", (clean_login,)) as cur:
            if await cur.fetchone():
                return False, None, "Пользователь с таким логином уже существует"

        cur = await db.execute("""
            INSERT INTO web_users (login, password_hash, email, role)
            VALUES (?, ?, ?, 'user')
        """, (clean_login, password_hash, email))
        user_id = cur.lastrowid
        await db.commit()

        async with db.execute("SELECT * FROM web_users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return True, dict(row), ""

async def web_authenticate_user(login: str, password_hash: str) -> Optional[Dict[str, Any]]:
    clean_login = login.strip().lower()
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM web_users WHERE LOWER(login) = ? AND password_hash = ?",
            (clean_login, password_hash)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def web_get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute("SELECT * FROM web_users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def web_update_subscription(user_id: int, plan: str, days: int = 30) -> str:
    now = now_utc_dt()
    user = await web_get_user_by_id(user_id)
    if user and user.get("sub_expires_at"):
        try:
            curr_exp = datetime.strptime(user["sub_expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            curr_exp = now
        new_exp = (curr_exp if curr_exp > now else now) + timedelta(days=days)
    else:
        new_exp = now + timedelta(days=days)

    exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")
    async with get_write_db() as db:
        await db.execute("""
            UPDATE web_users SET sub_plan = ?, sub_expires_at = ? WHERE id = ?
        """, (plan, exp_str, user_id))
        await db.commit()
    return exp_str

async def web_is_subscription_active(user_id: int) -> bool:
    user = await web_get_user_by_id(user_id)
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    exp_str = user.get("sub_expires_at")
    if not exp_str:
        return False
    try:
        exp_dt = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return exp_dt > now_utc_dt()
    except Exception:
        return False

async def web_save_bot(web_user_id: int, bot_token: str, bot_id: int, bot_username: str):
    async with get_write_db() as db:
        await db.execute("""
            INSERT INTO web_user_bots (web_user_id, bot_token, bot_id, bot_username, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (web_user_id, bot_token, bot_id, bot_username))
        await db.commit()

async def web_get_user_bots(web_user_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM web_user_bots WHERE web_user_id = ? ORDER BY id DESC",
            (web_user_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def web_delete_bot(web_user_id: int, bot_id: int):
    async with get_write_db() as db:
        await db.execute(
            "DELETE FROM web_user_bots WHERE web_user_id = ? AND id = ?",
            (web_user_id, bot_id)
        )
        await db.commit()

async def web_save_deal(web_user_id: int, nft_name: str, nft_number: str, stars_amount: int, recipient: str, deal_link: str) -> int:
    async with get_write_db() as db:
        cur = await db.execute("""
            INSERT INTO web_deals (web_user_id, nft_name, nft_number, stars_amount, recipient, deal_link, status)
            VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
        """, (web_user_id, nft_name, nft_number, stars_amount, recipient, deal_link))
        new_id = cur.lastrowid
        await db.commit()
        return new_id

async def web_get_user_deals(web_user_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM web_deals WHERE web_user_id = ? ORDER BY id DESC LIMIT 50",
            (web_user_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def web_get_admin_metrics() -> Dict[str, Any]:
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) as c FROM web_users") as cur:
            total_users = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) as c FROM web_user_bots") as cur:
            total_bots = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) as c FROM web_deals") as cur:
            total_deals = (await cur.fetchone())["c"]
        now_str = now_utc_str()
        async with db.execute("SELECT COUNT(*) as c FROM web_users WHERE sub_expires_at > ?", (now_str,)) as cur:
            active_subs = (await cur.fetchone())["c"]

        return {
            "total_users": total_users,
            "total_bots": total_bots,
            "total_deals": total_deals,
            "active_subs": active_subs
        }
