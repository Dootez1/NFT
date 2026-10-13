import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Admin IDs (comma-separated list of Telegram user IDs)
raw_admins = os.getenv("ADMIN_IDS", "8524472788,7900020458").split(",")
ADMIN_IDS = [int(x.strip()) for x in raw_admins if x.strip().isdigit()]

# Gift recipient username for offers
GIFT_RECIPIENT = os.getenv("GIFT_RECIPIENT", "@DealNftOffer").strip()
if not GIFT_RECIPIENT.startswith("@") and not GIFT_RECIPIENT.startswith("http"):
    GIFT_RECIPIENT = "@" + GIFT_RECIPIENT

# Default offer duration in hours
OFFER_DURATION_HOURS = int(os.getenv("OFFER_DURATION_HOURS", "6"))

# Subscription settings
SUB_DURATION_DAYS = int(os.getenv("SUB_DURATION_DAYS", "30"))
SUB_STANDARD_PRICE = int(os.getenv("SUB_STANDARD_PRICE", "100"))
SUB_PRO_PRICE = int(os.getenv("SUB_PRO_PRICE", "150"))
SUB_PRICE_STARS = SUB_STANDARD_PRICE  # alias

# Database path
DB_PATH = BASE_DIR / "bot_database.sqlite3"

# Default placeholder image if NFT preview fails to load
DEFAULT_NFT_IMAGE = "https://telegram.org/file/464001097/1/mQyB5gqI7aY.100078/eb0f5aa1a5c60aa582"
