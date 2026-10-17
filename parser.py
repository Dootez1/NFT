import re
import logging
from urllib.parse import urlparse
import aiohttp
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional

logger = logging.getLogger("nft_bot.parser")

KNOWN_GIFTS = {
    "libertyfigure": "Liberty Figure",
    "instantramen": "Instant Ramen",
    "lootbox": "Loot Box",
    "plushpepe": "Plush Pepe",
    "partysparkler": "Party Sparkler",
    "sweetheart": "Sweet Heart",
    "candycane": "Candy Cane",
    "sharpblade": "Sharp Blade",
    "magicpotion": "Magic Potion",
    "crystalball": "Crystal Ball",
    "spookyghost": "Spooky Ghost",
    "madpumpkin": "Mad Pumpkin",
    "santahat": "Santa Hat",
    "snowglobe": "Snow Globe",
    "gingercookie": "Ginger Cookie",
    "bdaycandle": "B-Day Candle",
    "gemstone": "Gem Stone",
    "jellybunny": "Jelly Bunny",
    "tophat": "Top Hat",
    "swisswatch": "Swiss Watch",
    "perfumebottle": "Perfume Bottle",
    "vintagecigar": "Vintage Cigar",
    "electricguitar": "Electric Guitar",
    "travelemerald": "Travel Emerald",
    "holidaytree": "Holiday Tree",
    "cloverleaf": "Clover Leaf",
    "redheart": "Red Heart",
    "ducky": "Ducky",
    "bigyear": "Big Year",
    "snake": "Snake",
    "telegramium": "Telegramium"
}

ALLOWED_DOMAINS = ("t.me", "telegram.me", "fragment.com")
NFT_CACHE: Dict[str, Dict[str, Any]] = {}
MAX_CACHE_SIZE = 2000

_SESSION: Optional[aiohttp.ClientSession] = None

def get_http_session() -> aiohttp.ClientSession:
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        connector = aiohttp.TCPConnector(limit=50, keepalive_timeout=75)
        _SESSION = aiohttp.ClientSession(
            connector=connector,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
        )
    return _SESSION

async def close_http_session():
    global _SESSION
    if _SESSION and not _SESSION.closed:
        await _SESSION.close()

def format_number(val: str) -> str:
    cleaned = re.sub(r'[^\d]', '', str(val))
    if cleaned.isdigit():
        return f"{int(cleaned):,}"
    return str(val)

def format_offer_timer(expires_at, lang: str = "RU") -> str:
    """
    Форматирует оставшееся время действия оффера (например: '5 ч. 59 мин.' или '5 h. 59 min.')
    """
    from datetime import datetime, timezone
    is_eng = (lang == "ENG")
    default_ret = "5 h. 59 min." if is_eng else "5 ч. 59 мин."
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except Exception:
            return default_ret
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    diff = expires_at - now
    total_seconds = int(diff.total_seconds())
    if total_seconds <= 0:
        return "0 min." if is_eng else "0 мин."
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if is_eng:
        if hours > 0:
            return f"{hours} h. {minutes} min."
        return f"{minutes} min."
    else:
        if hours > 0:
            return f"{hours} ч. {minutes} мин."
        return f"{minutes} мин."

def _is_allowed_domain(url: str) -> bool:
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        return any(hostname == d or hostname.endswith("." + d) for d in ALLOWED_DOMAINS)
    except Exception:
        return False

async def parse_nft_url(url: str) -> Dict[str, Any]:
    clean_url = url.strip()
    if not clean_url.startswith("http"):
        clean_url = "https://" + clean_url

    if not _is_allowed_domain(clean_url):
        logger.warning(f"Rejected unallowed domain URL: {clean_url}")
        return {
            "name": "Telegram Gift",
            "number": "1",
            "image_url": None,
            "url": clean_url
        }

    if clean_url in NFT_CACHE:
        return NFT_CACHE[clean_url]

    # Fallback info from slug if scraping fails
    slug = clean_url.rstrip("/").split("/")[-1]
    slug_match = re.search(r'([A-Za-z0-9\-_]+?)-(\d+)$', slug)
    if slug_match:
        raw_name = slug_match.group(1)
        name_key = re.sub(r'[^a-zA-Z0-9]', '', raw_name).lower()
        default_number = slug_match.group(2)
        default_name = KNOWN_GIFTS.get(name_key) or raw_name.replace("-", " ").replace("_", " ").title()
    else:
        name_key = re.sub(r'[^a-zA-Z0-9]', '', slug).lower()
        default_number = "1"
        default_name = KNOWN_GIFTS.get(name_key) or slug.replace("-", " ").replace("_", " ").title()

    nft_name = default_name
    nft_number = default_number
    image_url = None
    owner_username = None
    owner_name = None
    owner_url = None
    try:
        session = get_http_session()
        async with session.get(clean_url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")

                    og_title = soup.find("meta", property="og:title")
                    og_image = soup.find("meta", property="og:image")

                    if og_title and og_title.get("content"):
                        title = og_title["content"].strip()
                        match = re.search(r'^(.*?)\s*#?([0-9,]+)$', title)
                        if match:
                            nft_name = match.group(1).strip()
                            nft_number = match.group(2).strip()
                        else:
                            nft_name = title

                    if og_image and og_image.get("content"):
                        image_url = og_image["content"].strip()

                    for tr in soup.find_all("tr"):
                        th = tr.find("th")
                        td = tr.find("td")
                        if th and td and "Owner" in th.get_text():
                            a = td.find("a")
                            if a:
                                href = a.get("href", "")
                                owner_url = href
                                u_match = re.search(r't\.me/([^/?#]+)', href)
                                if u_match:
                                    owner_username = "@" + u_match.group(1)
                                owner_name = a.get_text().strip()
                            else:
                                owner_name = td.get_text().strip()
    except Exception as e:
        logger.debug(f"Could not scrape {clean_url}: {e}")

    result = {
        "name": nft_name,
        "number": nft_number,
        "image_url": image_url,
        "url": clean_url,
        "owner_username": owner_username,
        "owner_name": owner_name,
        "owner_url": owner_url
    }
    if len(NFT_CACHE) >= MAX_CACHE_SIZE:
        NFT_CACHE.clear()
    NFT_CACHE[clean_url] = result
    return result

def extract_buy_args(text: str) -> Optional[tuple[str, int, str]]:
    parts = text.split()
    if not parts:
        return None

    found_url = None
    found_stars = None
    currency = "STARS"

    for arg in parts:
        cleaned_arg = arg.strip()
        low = cleaned_arg.lower()
        if low in [".buy", "/buy", "buy"]:
            continue
        if cleaned_arg.startswith("@") and low.endswith("bot"):
            continue
        if low in ["gram", "ton"]:
            currency = "GRAM"
            continue
        if low in ["stars", "star", "звезд", "звезды", "звёзд", "звёзды"]:
            currency = "STARS"
            continue
        if any(d in low for d in ["t.me/", "telegram.me/", "http://", "https://", "fragment.com"]):
            found_url = cleaned_arg
        else:
            cleaned_num = re.sub(r'[^\d]', '', cleaned_arg)
            if cleaned_num.isdigit() and int(cleaned_num) > 0:
                found_stars = int(cleaned_num)

    if found_url and found_stars:
        return found_url, found_stars, currency
    return None

