import aiosqlite
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from config import DB_PATH, OFFER_DURATION_HOURS, ADMIN_IDS

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
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
                amount INTEGER NOT NULL,
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
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN plan TEXT DEFAULT 'standard';")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE deals ADD COLUMN inline_message_id TEXT;")
        except Exception:
            pass
        await db.commit()

async def register_user(user_id: int, username: Optional[str], first_name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cur:
            exists = await cur.fetchone()

        if not exists:
            await db.execute("""
                INSERT INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
            """, (user_id, username, first_name))
            await db.commit()
            return True
        else:
            await db.execute("""
                UPDATE users SET username = ?, first_name = ?, last_seen = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (username, first_name, user_id))
            await db.commit()
            return False

async def register_referral(referrer_id: int, new_user_id: int) -> bool:
    if referrer_id == new_user_id:
        return False

    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def add_or_extend_subscription_hours(
    user_id: int,
    username: Optional[str] = None,
    first_name: str = "User",
    hours: int = 6
) -> str:
    now = datetime.utcnow()
    existing = await get_subscription(user_id)

    if existing:
        current_exp = datetime.strptime(existing["expires_at"], "%Y-%m-%d %H:%M:%S")
        if current_exp > now:
            new_exp = current_exp + timedelta(hours=hours)
        else:
            new_exp = now + timedelta(hours=hours)
        plan = existing.get("plan", "standard")
    else:
        new_exp = now + timedelta(hours=hours)
        plan = "standard"

    new_exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(DB_PATH) as db:
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO business_connections (connection_id, user_id, user_username, can_reply, is_enabled)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(connection_id) DO UPDATE SET
                can_reply = excluded.can_reply,
                is_enabled = excluded.is_enabled,
                updated_at = CURRENT_TIMESTAMP
        """, (connection_id, user_id, user_username, can_reply, is_enabled))
        await db.commit()

async def is_subscription_active(user_id: int, required_plan: str = "standard") -> bool:
    if user_id in ADMIN_IDS:
        return True

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM subscriptions WHERE user_id = ? AND expires_at > ?",
            (user_id, now_str)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
            if required_plan == "pro":
                return row["plan"] == "pro"
            return True

async def get_subscription(user_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
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
    now = datetime.utcnow()
    existing = await get_subscription(user_id)
    
    if existing:
        current_exp = datetime.strptime(existing["expires_at"], "%Y-%m-%d %H:%M:%S")
        if charge_id == "ADMIN_GRANT":
            # При ручной выдаче админом устанавливаем ровно N дней от текущего момента
            new_exp = now + timedelta(days=days)
            effective_plan = plan
        else:
            if current_exp > now:
                new_exp = current_exp + timedelta(days=days)
            else:
                new_exp = now + timedelta(days=days)

            if plan == "pro" or existing.get("plan") == "pro":
                effective_plan = "pro"
            else:
                effective_plan = plan
    else:
        new_exp = now + timedelta(days=days)
        effective_plan = plan

    new_exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(DB_PATH) as db:
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
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE subscriptions SET expires_at = ? WHERE user_id = ?",
            (now_str, user_id)
        )
        await db.commit()

async def record_payment(
    user_id: int,
    amount: int,
    currency: str,
    charge_id: str,
    payload: str
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO payments_history (user_id, amount, currency, telegram_payment_charge_id, payload)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, amount, currency, charge_id, payload))
        await db.commit()

async def get_successful_deals(limit: int = 10) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
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
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total_users = (await cur.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM subscriptions WHERE expires_at > ?", (now_str,)) as cur:
            active_subs = (await cur.fetchone())[0]

        async with db.execute("SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM payments_history WHERE currency = 'XTR'") as cur:
            row = await cur.fetchone()
            total_stars = row[0]
            total_payments = row[1]

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
            "total_deals": total_deals,
            "completed_deals": completed_deals,
            "total_referrals": total_referrals
        }

async def get_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]

async def find_user(identifier: str) -> Optional[Dict[str, Any]]:
    clean = identifier.strip().lstrip("@")
    async with aiosqlite.connect(DB_PATH) as db:
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
    inline_message_id: Optional[str] = None
) -> int:
    expires_at = datetime.utcnow() + timedelta(hours=OFFER_DURATION_HOURS)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO deals (
                buyer_id, buyer_username, buyer_first_name, seller_id,
                nft_name, nft_number, nft_url, image_url,
                stars_amount, chat_id, business_connection_id, inline_message_id, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            buyer_id, buyer_username, buyer_first_name, seller_id,
            nft_name, nft_number, nft_url, image_url,
            stars_amount, chat_id, business_connection_id, inline_message_id, expires_at.strftime("%Y-%m-%d %H:%M:%S")
        ))
        await db.commit()
        return cursor.lastrowid

async def set_deal_message_id(deal_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE deals SET message_id = ? WHERE deal_id = ?",
            (message_id, deal_id)
        )
        await db.commit()

async def set_deal_inline_message_id(deal_id: int, inline_message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE deals SET inline_message_id = ? WHERE deal_id = ?",
            (inline_message_id, deal_id)
        )
        await db.commit()

async def get_deal(deal_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM deals WHERE deal_id = ?", (deal_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def accept_deal(deal_id: int, seller_id: int, seller_username: Optional[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE deals 
            SET status = 'ACCEPTED', seller_id = ?, seller_username = ?
            WHERE deal_id = ?
        """, (seller_id, seller_username, deal_id))
        await db.commit()

async def set_deal_status(deal_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE deals SET status = ? WHERE deal_id = ?", (status, deal_id))
        await db.commit()

async def get_pending_expired_deals() -> list:
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM deals WHERE status = 'PENDING' AND expires_at <= ?",
            (now_str,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
