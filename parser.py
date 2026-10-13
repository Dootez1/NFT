import re
import aiohttp
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional

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
    "ducky": "Ducky"
}

NFT_CACHE: Dict[str, Dict[str, Any]] = {}

def format_number(val: str) -> str:
    cleaned = re.sub(r'[^\d]', '', str(val))
    if cleaned.isdigit():
        return f"{int(cleaned):,}"
    return str(val)

async def parse_nft_url(url: str) -> Dict[str, Any]:
    clean_url = url.strip()
    if not clean_url.startswith("http"):
        clean_url = "https://" + clean_url

    if clean_url in NFT_CACHE:
        return NFT_CACHE[clean_url]

    # Fast slug extraction
    slug = clean_url.rstrip("/").split("/")[-1].lower()
    slug_match = re.search(r'([a-z\-]+)-(\d+)', slug)
    
    # Instant lookup if known gift
    if slug_match:
        name_key = slug_match.group(1).replace("-", "")
        number = slug_match.group(2)
        if name_key in KNOWN_GIFTS:
            result = {
                "name": KNOWN_GIFTS[name_key],
                "number": number,
                "image_url": None,
                "url": clean_url
            }
            NFT_CACHE[clean_url] = result
            return result

    # Fallback to network scraping if not in known list
    nft_name = "Telegram Gift"
    nft_number = "1"
    image_url = None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(clean_url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
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
    except Exception:
        pass

    if nft_name == "Telegram Gift" and slug_match:
        nft_name = slug_match.group(1).replace("-", " ").title()
        nft_number = slug_match.group(2)

    result = {
        "name": nft_name,
        "number": nft_number,
        "image_url": image_url,
        "url": clean_url
    }
    NFT_CACHE[clean_url] = result
    return result

def extract_buy_args(text: str) -> Optional[tuple[str, int]]:
    parts = text.split()
    if not parts:
        return None

    found_url = None
    found_stars = None

    for arg in parts:
        cleaned_arg = arg.strip()
        if cleaned_arg.lower() in [".buy", "/buy", "buy"]:
            continue
        if cleaned_arg.startswith("@") and cleaned_arg.lower().endswith("bot"):
            continue
        if any(d in cleaned_arg.lower() for d in ["t.me/", "telegram.me/", "http://", "https://", "fragment.com"]):
            found_url = cleaned_arg
        else:
            cleaned_num = re.sub(r'[^\d]', '', cleaned_arg)
            if cleaned_num.isdigit() and int(cleaned_num) > 0:
                found_stars = int(cleaned_num)

    if found_url and found_stars:
        return found_url, found_stars
    return None
