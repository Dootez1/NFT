import asyncio
from contextlib import asynccontextmanager
import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
import config
from config import DB_PATH, OFFER_DURATION_HOURS, ADMIN_IDS

_write_lock = asyncio.Lock()

def now_utc_dt() -> datetime:
    return datetime.now(timezone.utc)

def now_utc_str() -> str:
    return now_utc_dt().strftime("%Y-%m-%d %H:%M:%S")

def get_db():
    return aiosqlite.connect(DB_PATH, timeout=60.0)

@asynccontextmanager
async def get_write_db():
    async with _write_lock:
        async with get_db() as db:
            yield db

async def init_db():
    async with get_write_db() as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA busy_timeout=60000;")
        await db.execute("PRAGMA cache_size=-64000;")
        await db.execute("PRAGMA temp_store=MEMORY;")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                deal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_id INTEGER NOT NULL,
                buyer_username TEXT,
                buyer_first_name TEXT,
                seller_id INTEGER,
                seller_username TEXT,
                nft_name TEXT NOT NULL,
                nft_number TEXT NOT NULL,
                nft_url TEXT NOT NULL,
                image_url TEXT,
                stars_amount INTEGER NOT NULL,
                chat_id INTEGER,
                message_id INTEGER,
                business_connection_id TEXT,
                inline_message_id TEXT,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS business_connections (
                connection_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                user_username TEXT,
                can_reply BOOLEAN NOT NULL,
                is_enabled BOOLEAN NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                plan TEXT DEFAULT 'standard',
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_payment_charge_id TEXT
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments_history (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                telegram_payment_charge_id TEXT,
                payload TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_user_id INTEGER NOT NULL UNIQUE,
                reward_hours INTEGER DEFAULT 24,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Migrations for existing tables
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN plan TEXT DEFAULT 'standard';")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE deals ADD COLUMN inline_message_id TEXT;")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE deals ADD COLUMN currency TEXT DEFAULT 'STARS';")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE deals ADD COLUMN recipient TEXT DEFAULT '@DealNftOffer';")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE deals ADD COLUMN lang TEXT DEFAULT 'RU';")
        except Exception:
            pass

        # Performance Indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_deals_status_expires ON deals(status, expires_at);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_deals_buyer ON deals(buyer_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_deals_seller ON deals(seller_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_subs_expires ON subscriptions(expires_at);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_charge ON payments_history(telegram_payment_charge_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")

        await db.commit()

async def register_user(user_id: int, username: Optional[str], first_name: str) -> bool:
    async with get_write_db() as db:
        await db.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = COALESCE(excluded.username, users.username),
                first_name = COALESCE(excluded.first_name, users.first_name),
                last_seen = CURRENT_TIMESTAMP
        """, (user_id, username, first_name))
        await db.commit()
        return True

async def register_referral(referrer_id: int, new_user_id: int) -> bool:
    if referrer_id == new_user_id:
        return False

    async with get_write_db() as db:
        try:
            await db.execute("""
                INSERT INTO referrals (referrer_id, referred_user_id, reward_hours)
                VALUES (?, ?, 6)
            """, (referrer_id, new_user_id))
            await db.commit()
            return True
        except Exception:
            return False

async def get_referral_count(user_id: int) -> int:
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def add_or_extend_subscription_hours(
    user_id: int,
    username: Optional[str] = None,
    first_name: str = "User",
    hours: int = 6
) -> str:
    now = now_utc_dt()
    existing = await get_subscription(user_id)

    if existing:
        try:
            current_exp = datetime.strptime(existing["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            current_exp = now

        if current_exp > now:
            new_exp = current_exp + timedelta(hours=hours)
        else:
            new_exp = now + timedelta(hours=hours)
        plan = existing.get("plan", "standard")
    else:
        new_exp = now + timedelta(hours=hours)
        plan = "standard"

    new_exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")

    async with get_write_db() as db:
        await db.execute("""
            INSERT INTO subscriptions (user_id, username, first_name, plan, expires_at, last_payment_charge_id)
            VALUES (?, ?, ?, ?, ?, 'REFERRAL_REWARD')
            ON CONFLICT(user_id) DO UPDATE SET
                expires_at = excluded.expires_at,
                last_payment_charge_id = 'REFERRAL_REWARD'
        """, (user_id, username, first_name, plan, new_exp_str))
        await db.commit()

    return new_exp_str

async def save_business_connection(connection_id: str, user_id: int, user_username: Optional[str], can_reply: bool, is_enabled: bool):
    async with get_write_db() as db:
        await db.execute("""
            INSERT INTO business_connections (connection_id, user_id, user_username, can_reply, is_enabled)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(connection_id) DO UPDATE SET
                can_reply = excluded.can_reply,
                is_enabled = excluded.is_enabled,
                updated_at = CURRENT_TIMESTAMP
        """, (connection_id, user_id, user_username, can_reply, is_enabled))
        await db.commit()

async def get_business_connection_by_user(user_identifier: str | int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        clean_user = str(user_identifier).replace("@", "").strip()
        if clean_user.isdigit():
            query = "SELECT * FROM business_connections WHERE user_id = ? AND is_enabled = 1 AND can_reply = 1 ORDER BY updated_at DESC LIMIT 1"
            params = (int(clean_user),)
        else:
            query = "SELECT * FROM business_connections WHERE LOWER(user_username) = LOWER(?) AND is_enabled = 1 AND can_reply = 1 ORDER BY updated_at DESC LIMIT 1"
            params = (clean_user,)
        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
            return None

async def get_any_active_business_connection() -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM business_connections WHERE is_enabled = 1 AND can_reply = 1 ORDER BY updated_at DESC LIMIT 1"
        async with db.execute(query) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
            return None

async def is_subscription_active(user_id: int, required_plan: str = "standard") -> bool:
    if user_id in ADMIN_IDS:
        return True

    now_str = now_utc_str()
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM subscriptions WHERE user_id = ? AND expires_at > ?",
            (user_id, now_str)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
            if required_plan in ("pro", "premium"):
                return row["plan"] in ("pro", "premium")
            return True

async def get_subscription(user_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM subscriptions WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def add_or_extend_subscription(
    user_id: int,
    username: Optional[str],
    first_name: str,
    days: int = 30,
    plan: str = "standard",
    charge_id: Optional[str] = None
) -> str:
    now = now_utc_dt()
    existing = await get_subscription(user_id)
    
    if existing:
        try:
            current_exp = datetime.strptime(existing["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            current_exp = now

        if charge_id == "ADMIN_GRANT":
            new_exp = now + timedelta(days=days)
            effective_plan = plan
        else:
            if current_exp > now:
                new_exp = current_exp + timedelta(days=days)
            else:
                new_exp = now + timedelta(days=days)

            if plan == "premium" or existing.get("plan") == "premium":
                effective_plan = "premium"
            elif plan == "pro" or existing.get("plan") == "pro":
                effective_plan = "pro"
            else:
                effective_plan = plan
    else:
        new_exp = now + timedelta(days=days)
        effective_plan = plan

    new_exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")

    async with get_write_db() as db:
        await db.execute("""
            INSERT INTO subscriptions (user_id, username, first_name, plan, expires_at, last_payment_charge_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                plan = excluded.plan,
                expires_at = excluded.expires_at,
                last_payment_charge_id = excluded.last_payment_charge_id
        """, (user_id, username, first_name, effective_plan, new_exp_str, charge_id))
        await db.commit()
    
    return new_exp_str

async def revoke_subscription(user_id: int):
    now_str = now_utc_str()
    async with get_write_db() as db:
        await db.execute(
            "UPDATE subscriptions SET expires_at = ? WHERE user_id = ?",
            (now_str, user_id)
        )
        await db.commit()

async def record_payment(
    user_id: int,
    amount: float | int,
    currency: str,
    charge_id: str,
    payload: str
):
    async with get_write_db() as db:
        await db.execute("""
            INSERT INTO payments_history (user_id, amount, currency, telegram_payment_charge_id, payload)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, amount, currency, charge_id, payload))
        await db.commit()

async def is_charge_id_used(charge_id: str) -> bool:
    async with get_db() as db:
        async with db.execute(
            "SELECT payment_id FROM payments_history WHERE telegram_payment_charge_id = ?",
            (charge_id,)
        ) as cur:
            return (await cur.fetchone()) is not None

async def get_successful_deals(limit: int = 10) -> List[Dict[str, Any]]:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM deals 
            WHERE status = 'COMPLETED'
            ORDER BY deal_id DESC 
            LIMIT ?
        """, (limit,)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def get_admin_stats() -> Dict[str, Any]:
    now_str = now_utc_str()
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total_users = (await cur.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM subscriptions WHERE expires_at > ?", (now_str,)) as cur:
            active_subs = (await cur.fetchone())[0]

        async with db.execute("SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM payments_history WHERE currency = 'XTR'") as cur:
            row = await cur.fetchone()
            total_stars = int(row[0])
            total_payments = row[1]

        async with db.execute("SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM payments_history WHERE currency = 'TON'") as cur:
            row_ton = await cur.fetchone()
            total_ton = round(float(row_ton[0]), 2)
            total_ton_payments = row_ton[1]

        async with db.execute("SELECT COUNT(*) FROM deals") as cur:
            total_deals = (await cur.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM deals WHERE status = 'COMPLETED'") as cur:
            completed_deals = (await cur.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM referrals") as cur:
            total_referrals = (await cur.fetchone())[0]

        return {
            "total_users": total_users,
            "active_subs": active_subs,
            "total_stars": total_stars,
            "total_payments": total_payments,
            "total_ton": total_ton,
            "total_ton_payments": total_ton_payments,
            "total_deals": total_deals,
            "completed_deals": completed_deals,
            "total_referrals": total_referrals
        }

async def get_all_user_ids() -> List[int]:
    async with get_db() as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]

async def find_user(identifier: str) -> Optional[Dict[str, Any]]:
    clean = identifier.strip().lstrip("@")
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        if clean.isdigit():
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (int(clean),)) as cur:
                row = await cur.fetchone()
                if row:
                    return dict(row)
        async with db.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (clean,)) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
        return None

async def get_user_by_username(identifier: str) -> Optional[Dict[str, Any]]:
    return await find_user(identifier)

async def create_deal(
    buyer_id: int,
    buyer_username: Optional[str],
    buyer_first_name: str,
    seller_id: Optional[int],
    nft_name: str,
    nft_number: str,
    nft_url: str,
    image_url: Optional[str],
    stars_amount: int,
    chat_id: Optional[int] = None,
    business_connection_id: Optional[str] = None,
    inline_message_id: Optional[str] = None,
    currency: str = "STARS",
    seller_username: Optional[str] = None,
    recipient: Optional[str] = None,
    lang: str = "RU"
) -> int:
    expires_at = now_utc_dt() + timedelta(hours=OFFER_DURATION_HOURS)
    recip = recipient or config.GIFT_RECIPIENT
    async with get_write_db() as db:
        # Cancel older pending/confirming deals for the same gift to avoid ghost duplicates
        await db.execute("""
            UPDATE deals
            SET status = 'CANCELLED'
            WHERE status IN ('PENDING', 'CONFIRMING')
              AND buyer_id = ?
              AND nft_url = ?
        """, (buyer_id, nft_url))

        cursor = await db.execute("""
            INSERT INTO deals (
                buyer_id, buyer_username, buyer_first_name, seller_id, seller_username,
                nft_name, nft_number, nft_url, image_url,
                stars_amount, chat_id, business_connection_id, inline_message_id, expires_at, currency, recipient, lang
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            buyer_id, buyer_username, buyer_first_name, seller_id, seller_username,
            nft_name, nft_number, nft_url, image_url,
            stars_amount, chat_id, business_connection_id, inline_message_id, expires_at.strftime("%Y-%m-%d %H:%M:%S"), currency, recip, lang
        ))
        await db.commit()
        return cursor.lastrowid

async def cleanup_user_pending_inline_drafts(buyer_id: int):
    """
    Удаляет предыдущие неотправленные инлайн-черновики пользователя во избежание захламления базы
    """
    async with get_write_db() as db:
        await db.execute("""
            DELETE FROM deals 
            WHERE buyer_id = ? 
              AND status = 'PENDING' 
              AND inline_message_id IS NULL 
              AND chat_id IS NULL
        """, (buyer_id,))
        await db.commit()

async def cleanup_orphan_deals(older_than_minutes: int = 15):
    """
    Удаляет брошенные черновики инлайн-запросов
    """
    cutoff = (now_utc_dt() - timedelta(minutes=older_than_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    async with get_write_db() as db:
        await db.execute("""
            DELETE FROM deals 
            WHERE status = 'PENDING' 
              AND inline_message_id IS NULL 
              AND chat_id IS NULL 
              AND created_at <= ?
        """, (cutoff,))
        await db.commit()

async def set_deal_message_id(deal_id: int, message_id: int):
    async with get_write_db() as db:
        await db.execute(
            "UPDATE deals SET message_id = ? WHERE deal_id = ?",
            (message_id, deal_id)
        )
        await db.commit()

async def set_deal_inline_message_id(deal_id: int, inline_message_id: str):
    async with get_write_db() as db:
        await db.execute(
            "UPDATE deals SET inline_message_id = ? WHERE deal_id = ?",
            (inline_message_id, deal_id)
        )
        await db.commit()

async def update_deal_target(deal_id: int, chat_id: int, message_id: int, business_connection_id: Optional[str] = None):
    async with get_write_db() as db:
        await db.execute(
            "UPDATE deals SET chat_id = ?, message_id = ?, business_connection_id = ? WHERE deal_id = ?",
            (chat_id, message_id, business_connection_id, deal_id)
        )
        await db.commit()

async def get_deal(deal_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM deals WHERE deal_id = ?", (deal_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def accept_deal(deal_id: int, seller_id: int, seller_username: Optional[str]):
    async with get_write_db() as db:
        await db.execute("""
            UPDATE deals 
            SET status = 'ACCEPTED', seller_id = ?, seller_username = ?
            WHERE deal_id = ?
        """, (seller_id, seller_username, deal_id))
        await db.commit()

async def set_deal_status(deal_id: int, status: str):
    async with get_write_db() as db:
        await db.execute("UPDATE deals SET status = ? WHERE deal_id = ?", (status, deal_id))
        await db.commit()

async def get_pending_expired_deals() -> list:
    now_str = now_utc_str()
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM deals WHERE status = 'PENDING' AND expires_at <= ?",
            (now_str,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_active_pending_deals() -> list:
    """
    Возвращает все активные офферы со статусом PENDING, для которых нужно обновлять таймер
    """
    now_str = now_utc_str()
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM deals 
               WHERE status = 'PENDING'
                 AND expires_at > ?
                 AND (message_id IS NOT NULL OR inline_message_id IS NOT NULL)""",
            (now_str,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_accepted_deals() -> list:
    """
    Возвращает недавние офферы со статусом ACCEPTED или SENT, ожидающие поступления подарка гаранту
    """
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM deals 
            WHERE status IN ('ACCEPTED', 'SENT')
            ORDER BY deal_id DESC
            LIMIT 5
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


