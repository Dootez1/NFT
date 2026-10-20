import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Web Server Settings
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0").strip()
WEB_PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", "8080")))
JWT_SECRET = os.getenv("JWT_SECRET", "jwt-secret-website-standalone-2026").strip()

# Database Path
DB_PATH = BASE_DIR / "web_database.sqlite3"

# Telegram Bot Links for cards (optional display)
MAIN_BOT_USERNAME = os.getenv("MAIN_BOT_USERNAME", "tggarantofferbot").strip()
DEAL_BOT_USERNAME = os.getenv("DEAL_BOT_USERNAME", "OfferTeIIegrambot").strip()

# Subscriptions & Payments
SUB_STANDARD_PRICE = int(os.getenv("SUB_STANDARD_PRICE", "250"))
SUB_PREMIUM_PRICE = int(os.getenv("SUB_PREMIUM_PRICE", "1000"))
SUB_STANDARD_PRICE_TON = float(os.getenv("SUB_STANDARD_PRICE_TON", "2.0"))
SUB_PREMIUM_PRICE_TON = float(os.getenv("SUB_PREMIUM_PRICE_TON", "8.0"))
TON_WALLET_ADDRESS = os.getenv("TON_WALLET_ADDRESS", "UQASYty8wN40Y_h9qC5oCRXm1SsDMHM-m0jvt6C_7wZqsWEk").strip()

# Admin IDs
raw_admins = os.getenv("ADMIN_IDS", "8865248762,8524472788,7900020458").split(",")
ADMIN_IDS = [int(x.strip()) for x in raw_admins if x.strip().isdigit()]
