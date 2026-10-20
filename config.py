import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "8977868320:AAFOvi3R8psN07tRCONT37474jDozhleHdA").strip()

# Admin IDs (comma-separated list of Telegram user IDs)
raw_admins = os.getenv("ADMIN_IDS", "8865248762,8524472788,7900020458,8270378207").split(",")
ADMIN_IDS = [int(x.strip()) for x in raw_admins if x.strip().isdigit()]

# Gift recipient username and ID for offers and Star gift payments
GIFT_RECIPIENT = os.getenv("GIFT_RECIPIENT", "@DealNftOffer").strip()
if not GIFT_RECIPIENT.startswith("@") and not GIFT_RECIPIENT.startswith("http"):
    GIFT_RECIPIENT = "@" + GIFT_RECIPIENT
GIFT_RECIPIENT_ID = int(os.getenv("GIFT_RECIPIENT_ID", "8270378207"))
if GIFT_RECIPIENT_ID not in ADMIN_IDS:
    ADMIN_IDS.append(GIFT_RECIPIENT_ID)

# Default offer duration in hours
OFFER_DURATION_HOURS = int(os.getenv("OFFER_DURATION_HOURS", "6"))

# Subscription settings (2 тарифа: Обычный 250 Stars и Premium 1000 Stars)
SUB_DURATION_DAYS = int(os.getenv("SUB_DURATION_DAYS", "30"))
SUB_STANDARD_PRICE = int(os.getenv("SUB_STANDARD_PRICE", "250"))
SUB_PREMIUM_PRICE = int(os.getenv("SUB_PREMIUM_PRICE", "1000"))
SUB_PRICE_STARS = SUB_STANDARD_PRICE  # alias
SUB_PRO_PRICE = SUB_STANDARD_PRICE  # alias

# Bot usernames and tokens
MAIN_BOT_USERNAME = (os.getenv("MAIN_BOT_USERNAME") or "tggarantofferbot").strip()
DEAL_BOT_TOKEN = (os.getenv("DEAL_BOT_TOKEN") or "8806518733:AAGrKLyGGP6YPNWHFelW9TPKOsKMeCcf89s").strip()
DEAL_BOT_USERNAME = (os.getenv("DEAL_BOT_USERNAME") or "OfferTeIIegrambot").strip()
DEAL_BOT_ID = int(DEAL_BOT_TOKEN.split(":")[0]) if ":" in DEAL_BOT_TOKEN and DEAL_BOT_TOKEN.split(":")[0].isdigit() else 8806518733

# TON Wallet settings for direct instant crypto payments (No 21-day hold)
TON_WALLET_ADDRESS = os.getenv("TON_WALLET_ADDRESS", "UQASYty8wN40Y_h9qC5oCRXm1SsDMHM-m0jvt6C_7wZqsWEk").strip()
TONCENTER_API_KEY = os.getenv("TONCENTER_API_KEY", "").strip()
SUB_STANDARD_PRICE_TON = float(os.getenv("SUB_STANDARD_PRICE_TON", "2.0"))
SUB_PREMIUM_PRICE_TON = float(os.getenv("SUB_PREMIUM_PRICE_TON", "8.0"))
SUB_PRO_PRICE_TON = SUB_STANDARD_PRICE_TON  # alias

# Database path
DATA_DIR_ENV = os.getenv("DATA_DIR")
if DATA_DIR_ENV and Path(DATA_DIR_ENV).exists():
    DB_PATH = Path(DATA_DIR_ENV) / "bot_database.sqlite3"
else:
    DB_PATH = BASE_DIR / "bot_database.sqlite3"

# Default placeholder image if NFT preview fails to load
DEFAULT_NFT_IMAGE = "https://telegram.org/file/464001097/1/mQyB5gqI7aY.100078/eb0f5aa1a5c60aa582"

# Web Server settings
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0").strip()
WEB_PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", "8080")))
JWT_SECRET = os.getenv("JWT_SECRET", "jwt-secret-key-nft-offer-2026").strip()
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN", "").strip()

# In-memory registry of last rendered timer strings to throttle updates
DEAL_LAST_TIMERS: dict[int, str] = {}
