import asyncio
import hashlib
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import jwt
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import config
from . import database as db

logger = logging.getLogger("website")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

JWT_SECRET = getattr(config, "JWT_SECRET", "jwt-secret-website-standalone-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 30

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    logger.info("Website database initialized.")
    yield

app = FastAPI(title="NFT Deals Web Platform", version="3.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# -------------------------------------------------------------
# Auth & Security Helpers
# -------------------------------------------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(f"salt_2026_{password}".encode()).hexdigest()

def create_jwt_token(user_id: int, login: str, role: str = "user") -> str:
    payload = {
        "user_id": user_id,
        "login": login,
        "role": role,
        "is_admin": role == "admin" or login.lower() in ("admin", "root") or user_id in config.ADMIN_IDS,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRATION_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None

async def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    if not token:
        return None
    return decode_jwt_token(token)

async def require_user(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация")
    return user


# -------------------------------------------------------------
# Pydantic Request Models
# -------------------------------------------------------------
class RegisterRequest(BaseModel):
    login: str
    password: str
    email: Optional[str] = None

class LoginRequest(BaseModel):
    login: str
    password: str

class ConnectBotRequest(BaseModel):
    token: str

class PromoCodeRequest(BaseModel):
    code: str

class CreateDealRequest(BaseModel):
    nft_name: str
    nft_number: str
    stars_amount: int
    recipient: Optional[str] = "@DealNftOffer"
    lang: Optional[str] = "RU"

class AdminGrantRequest(BaseModel):
    user_id: int
    plan: str
    days: int = 30


# -------------------------------------------------------------
# Frontend Routes (HTML)
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
async def login_gateway(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={}
    )

@app.get("/landing", response_class=HTMLResponse)
async def landing_page(request: Request):
    user = await get_current_user(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"user": user}
    )

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    web_user = await db.web_get_user_by_id(user["user_id"])
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": {
                "id": user["user_id"],
                "login": web_user["login"] if web_user else user["login"],
                "role": web_user.get("role", "user") if web_user else "user"
            },
            "bot_username": config.MAIN_BOT_USERNAME,
            "deal_bot_username": config.DEAL_BOT_USERNAME,
            "is_admin": bool(user.get("is_admin")),
            "standard_price_stars": config.SUB_STANDARD_PRICE,
            "premium_price_stars": config.SUB_PREMIUM_PRICE,
            "standard_price_ton": config.SUB_STANDARD_PRICE_TON,
            "premium_price_ton": config.SUB_PREMIUM_PRICE_TON,
            "ton_address": config.TON_WALLET_ADDRESS,
        }
    )


# -------------------------------------------------------------
# Standalone Web Authentication API
# -------------------------------------------------------------
@app.post("/api/auth/register")
async def auth_register(req: RegisterRequest, response: Response):
    login = req.login.strip().lower()
    if len(login) < 3:
        raise HTTPException(status_code=400, detail="Логин должен содержать не менее 3 символов")
    if len(req.password.strip()) < 4:
        raise HTTPException(status_code=400, detail="Пароль должен содержать не менее 4 символов")

    pwd_hash = hash_password(req.password.strip())
    ok, user_row, err_msg = await db.web_register_user(login, pwd_hash, req.email)
    if not ok:
        raise HTTPException(status_code=400, detail=err_msg)

    user_id = user_row["id"]
    token = create_jwt_token(user_id, login, user_row.get("role", "user"))
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=JWT_EXPIRATION_DAYS * 86400,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True, "token": token, "redirect": "/dashboard"}

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest, response: Response):
    login = req.login.strip().lower()
    pwd_hash = hash_password(req.password.strip())

    user_row = await db.web_authenticate_user(login, pwd_hash)
    if not user_row:
        raise HTTPException(status_code=400, detail="Неверный логин или пароль")

    user_id = user_row["id"]
    token = create_jwt_token(user_id, login, user_row.get("role", "user"))
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=JWT_EXPIRATION_DAYS * 86400,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True, "token": token, "redirect": "/dashboard"}

@app.post("/api/auth/demo")
async def auth_demo(response: Response):
    demo_login = f"demo_{int(time.time()) % 10000}"
    pwd_hash = hash_password("demo123")
    ok, user_row, _ = await db.web_register_user(demo_login, pwd_hash)
    if not ok or not user_row:
        user_row = await db.web_authenticate_user(demo_login, pwd_hash)

    user_id = user_row["id"] if user_row else 999
    token = create_jwt_token(user_id, demo_login, "user")
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=86400,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True, "token": token, "redirect": "/dashboard"}

@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"ok": True}


# -------------------------------------------------------------
# Profile & Subscriptions API
# -------------------------------------------------------------
@app.get("/api/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Требуется авторизация")

    user_id = user["user_id"]
    web_user = await db.web_get_user_by_id(user_id)
    if not web_user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    is_active = await db.web_is_subscription_active(user_id)
    bots = await db.web_get_user_bots(user_id)
    deals = await db.web_get_user_deals(user_id)

    time_left_str = "Истекла"
    if web_user.get("sub_expires_at"):
        try:
            exp_dt = datetime.strptime(web_user["sub_expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            now = db.now_utc_dt()
            if exp_dt > now:
                diff = exp_dt - now
                days = diff.days
                hours = diff.seconds // 3600
                time_left_str = f"{days} дн. {hours} ч."
            else:
                time_left_str = "Истекла"
        except Exception:
            time_left_str = web_user.get("sub_expires_at", "")

    return {
        "ok": True,
        "user": {
            "id": user_id,
            "login": web_user["login"],
            "role": web_user.get("role", "user"),
            "is_admin": bool(user.get("is_admin"))
        },
        "subscription": {
            "is_active": is_active,
            "plan": web_user.get("sub_plan", "none"),
            "expires_at": web_user.get("sub_expires_at"),
            "time_left": time_left_str,
        },
        "bots": bots,
        "deals_count": len(deals)
    }


# -------------------------------------------------------------
# Bot Management API
# -------------------------------------------------------------
@app.get("/api/bots")
async def list_bots(request: Request):
    user = await require_user(request)
    bots = await db.web_get_user_bots(user["user_id"])
    return {"ok": True, "bots": bots}

@app.post("/api/bots/connect")
async def connect_bot(req: ConnectBotRequest, request: Request):
    user = await require_user(request)
    user_id = user["user_id"]

    is_active = await db.web_is_subscription_active(user_id)
    if not is_active:
        raise HTTPException(
            status_code=403,
            detail="У вас пока нет активной подписки! Перейдите во вкладку «Тарифы» и активируйте тариф."
        )

    token = req.token.strip()
    bot_id = 12345
    bot_uname = "connected_bot"
    if ":" in token and token.split(":")[0].isdigit():
        bot_id = int(token.split(":")[0])

    await db.web_save_bot(user_id, token, bot_id, bot_uname)

    return {
        "ok": True,
        "message": f"Бот успешно сохранён в панели!",
        "bot_username": bot_uname
    }

@app.post("/api/bots/delete")
async def delete_bot(data: dict, request: Request):
    user = await require_user(request)
    bot_id = int(data.get("bot_id", 0))
    await db.web_delete_bot(user["user_id"], bot_id)
    return {"ok": True, "message": "Бот удален из панели"}


# -------------------------------------------------------------
# Deals API
# -------------------------------------------------------------
@app.get("/api/deals")
async def list_deals(request: Request):
    user = await require_user(request)
    deals = await db.web_get_user_deals(user["user_id"])
    return {"ok": True, "deals": deals}

@app.post("/api/deals/create")
async def create_deal(req: CreateDealRequest, request: Request):
    user = await require_user(request)
    user_id = user["user_id"]

    is_active = await db.web_is_subscription_active(user_id)
    if not is_active:
        raise HTTPException(status_code=403, detail="Создание офферов доступно только при активной подписке")

    deal_bot = getattr(config, "DEAL_BOT_USERNAME", "OfferTeIIegrambot")
    fake_time = int(time.time())
    deal_link = f"https://t.me/{deal_bot}?start=deal_{fake_time}"

    deal_id = await db.web_save_deal(
        web_user_id=user_id,
        nft_name=req.nft_name.strip(),
        nft_number=req.nft_number.strip(),
        stars_amount=req.stars_amount,
        recipient=req.recipient or "@DealNftOffer",
        deal_link=deal_link
    )
    final_link = f"https://t.me/{deal_bot}?start=deal_{deal_id}"

    return {
        "ok": True,
        "deal_id": deal_id,
        "deal_link": final_link,
        "message": f"Оффер #{deal_id} успешно сгенерирован!"
    }


# -------------------------------------------------------------
# Payments & Promo Codes API
# -------------------------------------------------------------
@app.post("/api/subscription/activate_code")
async def activate_promo_code(req: PromoCodeRequest, request: Request):
    user = await require_user(request)
    code = req.code.strip().upper()

    valid_codes = {
        "START2026": ("standard", 7),
        "PREMIUM2026": ("premium", 14),
        "DEVTEST": ("premium", 30),
        "ADMINFREE": ("premium", 365),
    }

    if code in valid_codes:
        plan, days = valid_codes[code]
        new_exp = await db.web_update_subscription(user["user_id"], plan, days)
        return {"ok": True, "message": f"Промокод активирован! Вам начислен тариф {plan.upper()} на {days} дней (до {new_exp})."}

    raise HTTPException(status_code=400, detail="Неверный или устаревший промокод")

@app.post("/api/subscription/create_order")
async def create_order(data: dict, request: Request):
    user = await require_user(request)
    plan = data.get("plan", "standard")
    method = data.get("payment_method", "ton")

    price_ton = config.SUB_PREMIUM_PRICE_TON if plan == "premium" else config.SUB_STANDARD_PRICE_TON
    comment = f"sub_{plan}_{user['user_id']}"
    ton_address = config.TON_WALLET_ADDRESS
    tonkeeper_url = f"https://app.tonkeeper.com/transfer/{ton_address}?amount={int(price_ton * 1e9)}&text={comment}"

    invoice = {
        "address": ton_address,
        "amount_ton": price_ton,
        "comment": comment,
        "tonkeeper_url": tonkeeper_url
    }

    return {
        "ok": True,
        "invoice": invoice,
        "plan": plan,
        "method": method
    }


# -------------------------------------------------------------
# Admin API
# -------------------------------------------------------------
@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    user = await require_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    metrics = await db.web_get_admin_metrics()
    return {"ok": True, "stats": metrics}

@app.post("/api/admin/grant")
async def admin_grant(req: AdminGrantRequest, request: Request):
    user = await require_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    new_exp = await db.web_update_subscription(req.user_id, req.plan, req.days)
    return {"ok": True, "message": f"Тариф {req.plan.upper()} выдан аккаунту #{req.user_id} на {req.days} дней (до {new_exp})."}


# -------------------------------------------------------------
# Standalone Runner
# -------------------------------------------------------------
def run_server():
    import uvicorn
    host = getattr(config, "WEB_HOST", "0.0.0.0")
    port = getattr(config, "WEB_PORT", 8080)
    print(f"\n" + "=" * 60)
    print(f" 🚀 Standalone Web Platform запущен на http://{host}:{port}")
    print(f" Откройте в браузере: http://localhost:{port}")
    print("=" * 60 + "\n")
    uvicorn.run("website.server:app", host=host, port=port, reload=True)

if __name__ == "__main__":
    run_server()
