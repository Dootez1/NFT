import asyncio
import hashlib
import hmac
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import jwt
from fastapi import FastAPI, Depends, HTTPException, Request, Response, status, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import aiohttp

import config
import database as db
from worker_manager import worker_manager
import ton_payments

logger = logging.getLogger("nft_bot.web")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title="NFT Deals SaaS Platform", version="2.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

JWT_SECRET = getattr(config, "JWT_SECRET", "jwt-secret-key-nft-offer-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 30


# -------------------------------------------------------------
# Auth & Security Helpers
# -------------------------------------------------------------
def create_jwt_token(user_id: int, username: Optional[str] = None, first_name: str = "") -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "is_admin": user_id in config.ADMIN_IDS,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRATION_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def verify_telegram_hash(auth_data: dict, bot_token: str) -> bool:
    """Проверка подлинности данных от официального Telegram Login Widget"""
    check_hash = auth_data.get("hash")
    if not check_hash:
        return False
    data_check_arr = []
    for k, v in sorted(auth_data.items()):
        if k != "hash" and v is not None:
            data_check_arr.append(f"{k}={v}")
    data_check_string = "\n".join(data_check_arr)
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    hash_calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hash_calculated == check_hash


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


async def require_admin(request: Request) -> Dict[str, Any]:
    user = await require_user(request)
    if not user.get("is_admin") and user.get("user_id") not in config.ADMIN_IDS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ запрещён: только для администраторов")
    return user


# -------------------------------------------------------------
# Pydantic Request Models
# -------------------------------------------------------------
class RegisterRequest(BaseModel):
    user_id: int
    username: Optional[str] = None
    password: str


class LoginRequest(BaseModel):
    login: str  # user_id or username
    password: str


class DemoLoginRequest(BaseModel):
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = "Worker"


class ConnectBotRequest(BaseModel):
    token: str
    user_id: Optional[int] = None
    username: Optional[str] = None


class BotActionRequest(BaseModel):
    action: str  # 'restart', 'stop', 'delete'


class CreateOrderRequest(BaseModel):
    plan: str  # 'standard' | 'premium'
    payment_method: str  # 'cryptobot' | 'ton' | 'cards'
    user_id: Optional[int] = None


class CheckOrderRequest(BaseModel):
    plan: str
    payment_method: str
    order_id: Optional[str] = None
    user_id: Optional[int] = None


class PromoCodeRequest(BaseModel):
    code: str
    user_id: Optional[int] = None


class CreateDealRequest(BaseModel):
    nft_name: str
    nft_number: str
    stars_amount: int
    user_id: Optional[int] = None
    nft_url: Optional[str] = None
    image_url: Optional[str] = None
    recipient: Optional[str] = None
    currency: Optional[str] = "STARS"
    lang: Optional[str] = "RU"


class AdminGrantRequest(BaseModel):
    user_id: int
    plan: str
    days: int = 30


def hash_password(password: str) -> str:
    return hashlib.sha256(f"salt_2026_{password}".encode()).hexdigest()


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


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "bot_username": config.MAIN_BOT_USERNAME,
            "deal_bot_username": config.DEAL_BOT_USERNAME,
            "is_admin": bool(user and (user.get("is_admin") or user.get("user_id") in config.ADMIN_IDS)),
            "standard_price_stars": config.SUB_STANDARD_PRICE,
            "premium_price_stars": config.SUB_PREMIUM_PRICE,
            "standard_price_ton": config.SUB_STANDARD_PRICE_TON,
            "premium_price_ton": config.SUB_PREMIUM_PRICE_TON,
            "ton_address": config.TON_WALLET_ADDRESS,
        }
    )


# -------------------------------------------------------------
# Authentication API
# -------------------------------------------------------------
@app.post("/api/auth/register")
async def auth_register(req: RegisterRequest, response: Response):
    user_id = req.user_id
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="Telegram ID должен быть числом")
    if len(req.password.strip()) < 4:
        raise HTTPException(status_code=400, detail="Пароль должен содержать минимум 4 символа")

    username = (req.username or "").lstrip("@").strip() or f"user_{user_id}"
    pwd_hash = hash_password(req.password.strip())

    await db.register_user_with_password(user_id, username, username, pwd_hash)
    token = create_jwt_token(user_id, username, username)
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
    login_id = req.login.strip()
    pwd_hash = hash_password(req.password.strip())

    user_row = await db.verify_user_login(login_id, pwd_hash)
    if not user_row:
        raise HTTPException(status_code=400, detail="Неверный ID/юзернейм или пароль")

    user_id = user_row["user_id"]
    username = user_row.get("username") or f"user_{user_id}"
    token = create_jwt_token(user_id, username, user_row.get("first_name", username))
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=JWT_EXPIRATION_DAYS * 86400,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True, "token": token, "redirect": "/dashboard"}


# -------------------------------------------------------------
# Authentication API
# -------------------------------------------------------------
@app.post("/api/auth/telegram")
async def auth_telegram(data: dict, response: Response):
    """Авторизация через официальный Telegram Login Widget"""
    if not verify_telegram_hash(data, config.BOT_TOKEN):
        raise HTTPException(status_code=400, detail="Неверная подпись данных Telegram")

    user_id = int(data["id"])
    username = data.get("username")
    first_name = data.get("first_name", "User")

    await db.register_user(user_id, username, first_name)
    token = create_jwt_token(user_id, username, first_name)
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=JWT_EXPIRATION_DAYS * 86400,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True, "token": token, "user": {"id": user_id, "username": username, "first_name": first_name}}


@app.post("/api/auth/demo")
async def auth_demo(req: DemoLoginRequest, response: Response):
    """Быстрый вход по Telegram ID (для тестирования и прямого входа воркеров)"""
    user_id = req.user_id
    username = (req.username or "").lstrip("@")
    first_name = req.first_name or "Worker"

    await db.register_user(user_id, username, first_name)
    token = create_jwt_token(user_id, username, first_name)
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=JWT_EXPIRATION_DAYS * 86400,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True, "token": token, "user": {"id": user_id, "username": username, "first_name": first_name}}


@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"ok": True}


# -------------------------------------------------------------
# User Profile & Subscription API
# -------------------------------------------------------------
@app.get("/api/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    if not user:
        return {
            "ok": True,
            "authenticated": False,
            "user": None,
            "subscription": {
                "is_active": False,
                "plan": "none",
                "expires_at": None,
                "time_left": "ID не указан"
            },
            "worker_bot": None,
            "stats": {"total_deals": 0, "pending_deals": 0, "accepted_deals": 0}
        }

    user_id = user["user_id"]
    sub = await db.get_subscription(user_id)
    is_active = await db.is_subscription_active(user_id)
    worker_bot = await db.get_worker_bot(user_id)
    deals = await db.get_deals_by_buyer(user_id, limit=50)

    # Статус поллинга бота воркера
    bot_is_running = False
    if worker_bot:
        task = worker_manager.active_tasks.get(user_id)
        bot_is_running = bool(task and not task.done())

    # Вычисление оставшегося времени подписки
    time_left_str = "Истекла"
    if sub and sub.get("expires_at"):
        try:
            exp_dt = datetime.strptime(sub["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            now = db.now_utc_dt()
            if exp_dt > now:
                diff = exp_dt - now
                days = diff.days
                hours = diff.seconds // 3600
                minutes = (diff.seconds % 3600) // 60
                time_left_str = f"{days} дн. {hours} ч. {minutes} мин."
            else:
                time_left_str = "Истекла"
        except Exception:
            time_left_str = sub.get("expires_at", "")

    return {
        "ok": True,
        "authenticated": True,
        "user": {
            "id": user_id,
            "username": user.get("username"),
            "first_name": user.get("first_name"),
            "is_admin": user_id in config.ADMIN_IDS,
        },
        "subscription": {
            "is_active": is_active,
            "plan": (sub.get("plan") if sub else "none") or "none",
            "expires_at": sub.get("expires_at") if sub else None,
            "time_left": time_left_str,
        },
        "worker_bot": {
            "connected": bool(worker_bot),
            "username": worker_bot.get("bot_username") if worker_bot else None,
            "bot_id": worker_bot.get("bot_id") if worker_bot else None,
            "is_active": bool(worker_bot.get("is_active")) if worker_bot else False,
            "is_running": bot_is_running,
        } if worker_bot else None,
        "stats": {
            "total_deals": len(deals),
            "pending_deals": sum(1 for d in deals if d.get("status") == "PENDING"),
            "accepted_deals": sum(1 for d in deals if d.get("status") in ("ACCEPTED", "SENT", "COMPLETED")),
        }
    }


# -------------------------------------------------------------
# Worker Bots API (Создание и управление ботами воркеров)
# -------------------------------------------------------------
@app.get("/api/bots")
async def get_my_bot(request: Request):
    user = await get_current_user(request)
    if not user:
        return {"ok": True, "bot": None}

    user_id = user["user_id"]
    bot_record = await db.get_worker_bot(user_id)
    if not bot_record:
        return {"ok": True, "bot": None}

    task = worker_manager.active_tasks.get(user_id)
    is_running = bool(task and not task.done())

    return {
        "ok": True,
        "bot": {
            "bot_id": bot_record["bot_id"],
            "username": bot_record["bot_username"],
            "is_active": bool(bot_record["is_active"]),
            "is_running": is_running,
            "updated_at": bot_record.get("updated_at"),
            "link": f"https://t.me/{bot_record['bot_username']}"
        }
    }


@app.post("/api/bots/connect")
async def connect_worker_bot(req: ConnectBotRequest, request: Request, response: Response):
    """Подключение и запуск бота воркера по токену от @BotFather"""
    user = await get_current_user(request)
    user_id = user["user_id"] if user else req.user_id
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="Пожалуйста, укажите ваш Telegram ID (число) для привязки бота"
        )

    # Если воркер ещё не авторизован, автоматически создаём сессию
    if not user:
        uname = req.username or f"user_{user_id}"
        await db.register_user(user_id, uname, uname)
        token_jwt = create_jwt_token(user_id, uname, uname)
        response.set_cookie(key="access_token", value=token_jwt, max_age=JWT_EXPIRATION_DAYS * 86400, httponly=True, samesite="lax")

    # Проверка подписки
    is_active = await db.is_subscription_active(user_id)
    if not is_active:
        raise HTTPException(
            status_code=403,
            detail="У вас пока нет активной подписки! Перейдите во вкладку «Тарифы» и активируйте Standard/Premium или введите промокод."
        )

    token = req.token.strip()
    if not worker_manager.is_valid_token(token):
        raise HTTPException(
            status_code=400,
            detail="Неверный формат токена Telegram! Пример правильного токена: 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
        )

    # Запускаем воркера через менеджер
    ok, res = await worker_manager.start_worker(user_id, token)
    if not ok:
        raise HTTPException(status_code=400, detail=res)

    return {
        "ok": True,
        "message": f"Бот @{res} успешно подключен и запущен!",
        "bot_username": res,
        "link": f"https://t.me/{res}"
    }


@app.post("/api/bots/action")
async def bot_action(req: BotActionRequest, user: Dict[str, Any] = Depends(require_user)):
    """Управление ботом: restart, stop, delete"""
    user_id = user["user_id"]
    bot_record = await db.get_worker_bot(user_id)
    if not bot_record:
        raise HTTPException(status_code=404, detail="У вас нет подключенного бота")

    action = req.action.lower()
    if action == "stop":
        await worker_manager.stop_worker(user_id, remove_from_db=False)
        return {"ok": True, "message": "Бот остановлен"}
    elif action == "restart":
        is_active = await db.is_subscription_active(user_id)
        if not is_active:
            raise HTTPException(status_code=403, detail="Подписка истекла, перезапуск невозможен")
        ok, res = await worker_manager.start_worker(user_id, bot_record["bot_token"])
        if not ok:
            raise HTTPException(status_code=400, detail=res)
        return {"ok": True, "message": f"Бот @{res} успешно перезапущен"}
    elif action == "delete":
        await worker_manager.stop_worker(user_id, remove_from_db=True)
        return {"ok": True, "message": "Бот удален из системы"}
    else:
        raise HTTPException(status_code=400, detail="Неизвестное действие")


# -------------------------------------------------------------
# Payments & Subscriptions API
# -------------------------------------------------------------
@app.post("/api/subscription/create_order")
async def create_subscription_order(req: CreateOrderRequest, user: Dict[str, Any] = Depends(require_user)):
    """Создание счёта на оплату тарифа через CryptoBot, TON или Карты"""
    user_id = user["user_id"]
    plan = req.plan.lower()
    if plan not in ("standard", "premium"):
        plan = "standard"

    method = req.payment_method.lower()

    # 1. Оплата через прямой перевод TON / Tonkeeper
    if method == "ton":
        invoice = ton_payments.get_ton_invoice_data(user_id, plan)
        return {
            "ok": True,
            "method": "ton",
            "invoice": invoice,
            "message": f"Переведите {invoice['amount_ton']} TON на указанный адрес с обязательным комментарием {invoice['comment']}"
        }

    # 2. Оплата через @CryptoBot API (если токен настроен)
    if method == "cryptobot" and getattr(config, "CRYPTO_BOT_TOKEN", None):
        amount_usd = 5.0 if plan == "standard" else 18.0
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://pay.crypt.bot/api/createInvoice"
                headers = {"Crypto-Pay-API-Token": config.CRYPTO_BOT_TOKEN}
                payload = {
                    "asset": "USDT",
                    "amount": str(amount_usd),
                    "description": f"Подписка {plan.capitalize()} (30 дней)",
                    "payload": f"sub:{user_id}:{plan}:30",
                    "paid_btn_name": "callback",
                    "paid_btn_url": "https://t.me/" + config.MAIN_BOT_USERNAME
                }
                async with session.post(url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        inv = data["result"]
                        return {
                            "ok": True,
                            "method": "cryptobot",
                            "pay_url": inv["pay_url"],
                            "invoice_id": inv["invoice_id"],
                            "amount": str(amount_usd),
                            "asset": "USDT"
                        }
        except Exception as e:
            logger.error(f"CryptoBot createInvoice error: {e}")

    # 3. Резервный / Банковские карты / Тестовый режим
    stars_price = config.SUB_STANDARD_PRICE if plan == "standard" else config.SUB_PREMIUM_PRICE
    ton_price = config.SUB_STANDARD_PRICE_TON if plan == "standard" else config.SUB_PREMIUM_PRICE_TON

    return {
        "ok": True,
        "method": method,
        "plan": plan,
        "price_stars": stars_price,
        "price_ton": ton_price,
        "ton_invoice": ton_payments.get_ton_invoice_data(user_id, plan),
        "message": "Для оплаты выберите перевод TON или используйте промокод / звездные подарки в боте."
    }


@app.post("/api/subscription/check_order")
async def check_subscription_order(req: CheckOrderRequest, user: Dict[str, Any] = Depends(require_user)):
    """Проверка поступления оплаты (TON блокчейн или CryptoBot)"""
    user_id = user["user_id"]
    plan = req.plan.lower()

    if req.payment_method == "ton":
        success, tx_hash, amount = await ton_payments.verify_ton_transaction(user_id, plan)
        if success:
            await db.add_or_extend_subscription(
                user_id=user_id,
                username=user.get("username"),
                first_name=user.get("first_name", "User"),
                days=30,
                plan=plan,
                charge_id=f"TON_{tx_hash[:16]}"
            )
            return {"ok": True, "paid": True, "message": f"Оплата {amount} TON подтверждена! Тариф {plan.upper()} активирован на 30 дней."}
        else:
            return {"ok": True, "paid": False, "message": "Платёж в блокчейне TON пока не обнаружен. Подождите 1-2 минуты и проверьте снова."}

    # CryptoBot check
    if req.payment_method == "cryptobot" and req.order_id and getattr(config, "CRYPTO_BOT_TOKEN", None):
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://pay.crypt.bot/api/getInvoices"
                headers = {"Crypto-Pay-API-Token": config.CRYPTO_BOT_TOKEN}
                params = {"invoice_ids": req.order_id}
                async with session.get(url, params=params, headers=headers) as resp:
                    data = await resp.json()
                    if data.get("ok") and data["result"]["items"]:
                        inv = data["result"]["items"][0]
                        if inv.get("status") == "paid":
                            await db.add_or_extend_subscription(
                                user_id=user_id,
                                username=user.get("username"),
                                first_name=user.get("first_name", "User"),
                                days=30,
                                plan=plan,
                                charge_id=f"CRYPTO_{req.order_id}"
                            )
                            return {"ok": True, "paid": True, "message": f"Оплата подтверждена! Тариф {plan.upper()} активирован на 30 дней."}
        except Exception as e:
            logger.error(f"Error checking cryptobot invoice: {e}")

    return {"ok": True, "paid": False, "message": "Оплата ещё не поступила."}


@app.post("/api/subscription/activate_code")
async def activate_promo_code(req: PromoCodeRequest, user: Dict[str, Any] = Depends(require_user)):
    """Активация промокода или тестовой подписки"""
    code = req.code.strip().upper()
    user_id = user["user_id"]

    valid_codes = {
        "START2026": ("standard", 7),
        "PREMIUM2026": ("premium", 14),
        "DEVTEST": ("premium", 30),
        "ADMINFREE": ("premium", 365),
    }

    if code in valid_codes:
        plan, days = valid_codes[code]
        new_exp = await db.add_or_extend_subscription(
            user_id=user_id,
            username=user.get("username"),
            first_name=user.get("first_name", "User"),
            days=days,
            plan=plan,
            charge_id=f"PROMO_{code}"
        )
        return {"ok": True, "message": f"Промокод активирован! Вам начислен тариф {plan.upper()} на {days} дней (до {new_exp})."}

    raise HTTPException(status_code=400, detail="Неверный или устаревший промокод")


# -------------------------------------------------------------
# Deals Management API (Создание сделок прямо с сайта)
# -------------------------------------------------------------
@app.get("/api/deals")
async def list_user_deals(user: Dict[str, Any] = Depends(require_user)):
    user_id = user["user_id"]
    deals = await db.get_deals_by_buyer(user_id, limit=50)
    deal_bot = getattr(config, "DEAL_BOT_USERNAME", "OfferTeIIegrambot")

    formatted = []
    for d in deals:
        d_id = d["deal_id"]
        formatted.append({
            "deal_id": d_id,
            "nft_name": d["nft_name"],
            "nft_number": d["nft_number"],
            "stars_amount": d["stars_amount"],
            "status": d["status"],
            "recipient": d.get("recipient", config.GIFT_RECIPIENT),
            "created_at": d.get("created_at"),
            "expires_at": d.get("expires_at"),
            "deal_link": f"https://t.me/{deal_bot}?start=deal_{d_id}"
        })

    return {"ok": True, "deals": formatted}


@app.post("/api/deals/create")
async def create_deal_from_web(req: CreateDealRequest, user: Dict[str, Any] = Depends(require_user)):
    user_id = user["user_id"]
    is_active = await db.is_subscription_active(user_id)
    if not is_active:
        raise HTTPException(status_code=403, detail="Создание сделок доступно только при активной подписке")

    nft_name = req.nft_name.strip()
    nft_number = req.nft_number.strip()
    stars = int(req.stars_amount)
    if stars <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше 0")

    nft_url = req.nft_url or f"https://t.me/nft/{nft_name.replace(' ', '_')}-{nft_number.lstrip('#')}"
    img_url = req.image_url or config.DEFAULT_NFT_IMAGE
    recip = req.recipient or config.GIFT_RECIPIENT

    deal_id = await db.create_deal(
        buyer_id=user_id,
        buyer_username=user.get("username"),
        buyer_first_name=user.get("first_name", "User"),
        seller_id=None,
        nft_name=nft_name,
        nft_number=nft_number,
        nft_url=nft_url,
        image_url=img_url,
        stars_amount=stars,
        currency=req.currency or "STARS",
        recipient=recip,
        lang=req.lang or "RU"
    )

    deal_bot = getattr(config, "DEAL_BOT_USERNAME", "OfferTeIIegrambot")
    deal_link = f"https://t.me/{deal_bot}?start=deal_{deal_id}"

    return {
        "ok": True,
        "deal_id": deal_id,
        "deal_link": deal_link,
        "message": f"Сделка #{deal_id} успешно создана!"
    }


# -------------------------------------------------------------
# Admin API
# -------------------------------------------------------------
@app.get("/api/admin/stats")
async def admin_get_stats(admin: Dict[str, Any] = Depends(require_admin)):
    stats = await db.get_admin_stats()
    all_bots = await db.get_all_worker_bots_full()
    active_memory_bots = len([t for t in worker_manager.active_tasks.values() if not t.done()])

    return {
        "ok": True,
        "stats": stats,
        "total_worker_bots_db": len(all_bots),
        "running_worker_bots_memory": active_memory_bots,
        "bots": all_bots
    }


@app.get("/api/admin/users")
async def admin_get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    admin: Dict[str, Any] = Depends(require_admin)
):
    offset = (page - 1) * limit
    users = await db.get_all_users_paged(limit=limit, offset=offset)
    return {"ok": True, "users": users, "page": page}


@app.post("/api/admin/grant")
async def admin_grant_sub(req: AdminGrantRequest, admin: Dict[str, Any] = Depends(require_admin)):
    new_exp = await db.add_or_extend_subscription(
        user_id=req.user_id,
        username=None,
        first_name="User",
        days=req.days,
        plan=req.plan,
        charge_id="ADMIN_MANUAL"
    )
    return {"ok": True, "message": f"Подписка {req.plan.upper()} выдана пользователю {req.user_id} на {req.days} дней (до {new_exp})."}


@app.post("/api/admin/revoke")
async def admin_revoke_sub(data: dict, admin: Dict[str, Any] = Depends(require_admin)):
    user_id = int(data["user_id"])
    await db.revoke_subscription(user_id)
    await worker_manager.stop_worker(user_id, remove_from_db=False)
    return {"ok": True, "message": f"Подписка пользователя {user_id} аннулирована, бот остановлен."}


# -------------------------------------------------------------
# Standalone Runner
# -------------------------------------------------------------
def run_server():
    import uvicorn
    host = getattr(config, "WEB_HOST", "0.0.0.0")
    port = getattr(config, "WEB_PORT", 8080)
    print(f"\n" + "=" * 60)
    print(f" 🚀 NFT Deals SaaS Web Server запущен на http://{host}:{port}")
    print(f" Откройте браузер по адресу: http://localhost:{port}")
    print("=" * 60 + "\n")
    uvicorn.run("web_server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run_server()
