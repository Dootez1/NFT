import logging
import aiohttp
import asyncio
from typing import Tuple, Optional, Dict, Any
from config import (
    TON_WALLET_ADDRESS,
    TONCENTER_API_KEY,
    SUB_STANDARD_PRICE_TON,
    SUB_PRO_PRICE_TON,
    SUB_PREMIUM_PRICE_TON
)
import database as db

logger = logging.getLogger("nft_bot.ton")

def get_plan_ton_price(plan: str) -> float:
    if plan == "premium":
        return SUB_PREMIUM_PRICE_TON
    elif plan == "pro":
        return SUB_PRO_PRICE_TON
    return SUB_STANDARD_PRICE_TON

def get_ton_invoice_data(user_id: int, plan: str) -> Dict[str, Any]:
    amount_ton = get_plan_ton_price(plan)
    nanotons = int(amount_ton * 1_000_000_000)
    comment = f"sub_{plan}_{user_id}"
    
    tonkeeper_url = f"https://app.tonkeeper.com/transfer/{TON_WALLET_ADDRESS}?amount={nanotons}&text={comment}"
    ton_uri = f"ton://transfer/{TON_WALLET_ADDRESS}?amount={nanotons}&text={comment}"
    
    return {
        "address": TON_WALLET_ADDRESS,
        "amount_ton": amount_ton,
        "nanotons": nanotons,
        "comment": comment,
        "tonkeeper_url": tonkeeper_url,
        "ton_uri": ton_uri,
        "plan": plan
    }

async def verify_ton_transaction(user_id: int, plan: str) -> Tuple[bool, Optional[str], Optional[float]]:
    """
    Проверяет блокчейн TON через Toncenter API на наличие входящей транзакции
    с нужным комментарием и суммой на кошелёк владельца.
    Возвращает: (успех, tx_hash, сумма_ton)
    """
    if not TON_WALLET_ADDRESS:
        logger.warning("TON_WALLET_ADDRESS is not configured.")
        return False, None, None

    amount_ton = get_plan_ton_price(plan)
    expected_nanotons = int(amount_ton * 1_000_000_000)
    expected_comment = f"sub_{plan}_{user_id}".strip().lower()

    url = f"https://toncenter.com/api/v2/getTransactions?address={TON_WALLET_ADDRESS}&limit=50"
    headers = {}
    if TONCENTER_API_KEY:
        headers["X-API-Key"] = TONCENTER_API_KEY

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Toncenter API returned status {resp.status}")
                    return False, None, None
                data = await resp.json()
                if not data.get("ok"):
                    logger.warning(f"Toncenter response not ok: {data}")
                    return False, None, None
                
                transactions = data.get("result", [])
                for tx in transactions:
                    in_msg = tx.get("in_msg", {})
                    if not in_msg:
                        continue
                    
                    # Проверяем комментарий к переводу (строгое совпадение!)
                    msg_text = str(in_msg.get("message", "")).strip().lower()
                    if not msg_text and in_msg.get("msg_data"):
                        import base64
                        try:
                            raw_b64 = in_msg["msg_data"].get("text", "")
                            if raw_b64:
                                msg_text = base64.b64decode(raw_b64).decode("utf-8", errors="ignore").strip().lower()
                        except Exception:
                            pass

                    if msg_text != expected_comment:
                        continue
                    
                    # Проверяем сумму (допускаем 98% от нужной на случай мелких комиссий сети)
                    try:
                        val = int(in_msg.get("value", 0))
                    except (ValueError, TypeError):
                        val = 0
                        
                    if val < int(expected_nanotons * 0.98):
                        continue
                    
                    tx_hash = tx.get("transaction_id", {}).get("hash", "")
                    if not tx_hash:
                        continue
                    
                    # Проверяем, не была ли эта транзакция уже использована ранее
                    already_used = await db.is_charge_id_used(tx_hash)
                    if already_used:
                        continue
                    
                    return True, tx_hash, (val / 1_000_000_000)
                    
    except Exception as e:
        logger.error(f"Error checking TON transactions: {e}")
        return False, None, None

    return False, None, None


def _format_date_display(dt_str: str) -> str:
    try:
        from datetime import datetime
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m.%Y в %H:%M")
    except Exception:
        return dt_str


async def check_all_incoming_ton_transactions(bot):
    """
    Сканирует входящие транзакции на кошельке TON_WALLET_ADDRESS.
    Ищет комментарии вида sub_<plan>_<user_id>, автоматически зачисляет подписку
    и отправляет уведомление пользователю в Telegram.
    """
    import re
    from config import SUB_DURATION_DAYS
    from keyboards import get_main_menu_keyboard

    if not TON_WALLET_ADDRESS:
        return

    url = f"https://toncenter.com/api/v2/getTransactions?address={TON_WALLET_ADDRESS}&limit=50"
    headers = {}
    if TONCENTER_API_KEY:
        headers["X-API-Key"] = TONCENTER_API_KEY

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
                if not data.get("ok"):
                    return

                transactions = data.get("result", [])
                for tx in transactions:
                    in_msg = tx.get("in_msg", {})
                    if not in_msg:
                        continue

                    msg_text = str(in_msg.get("message", "")).strip().lower()
                    if not msg_text and in_msg.get("msg_data"):
                        import base64
                        try:
                            raw_b64 = in_msg["msg_data"].get("text", "")
                            if raw_b64:
                                msg_text = base64.b64decode(raw_b64).decode("utf-8", errors="ignore").strip().lower()
                        except Exception:
                            pass

                    # Проверяем формат комментария: sub_<plan>_<user_id>
                    match = re.search(r'sub_(standard|pro|premium)_(\d+)', msg_text)
                    if not match:
                        continue

                    plan = match.group(1)
                    user_id = int(match.group(2))

                    tx_hash = tx.get("transaction_id", {}).get("hash", "")
                    if not tx_hash:
                        continue

                    # Проверяем, не была ли транзакция уже зачислена
                    already_used = await db.is_charge_id_used(tx_hash)
                    if already_used:
                        continue

                    # Проверяем сумму (допускаем 98% от нужной на случай мелких комиссий сети)
                    amount_ton = get_plan_ton_price(plan)
                    expected_nanotons = int(amount_ton * 1_000_000_000)
                    try:
                        val = int(in_msg.get("value", 0))
                    except (ValueError, TypeError):
                        val = 0

                    if val < int(expected_nanotons * 0.98):
                        logger.warning(f"TON payment received for user {user_id}, but amount {val} < expected {expected_nanotons}")
                        continue

                    # Получаем информацию о пользователе из базы (если есть)
                    user_row = await db.find_user(str(user_id))
                    username = user_row.get("username") if user_row else None
                    first_name = user_row.get("first_name", "User") if user_row else "User"

                    # 1. Записываем платёж в базу
                    actual_ton = val / 1_000_000_000
                    await db.record_payment(
                        user_id=user_id,
                        amount=actual_ton,
                        currency="TON",
                        charge_id=tx_hash,
                        payload=f"ton_auto_{plan}_{user_id}"
                    )

                    # 2. Активируем / продлеваем подписку
                    new_expires_at = await db.add_or_extend_subscription(
                        user_id=user_id,
                        username=username,
                        first_name=first_name,
                        days=SUB_DURATION_DAYS,
                        plan=plan,
                        charge_id=tx_hash
                    )

                    if plan == "premium":
                        plan_name = "👑 Premium (100% профита)"
                    elif plan == "pro":
                        plan_name = "💎 PRO (Инлайн + Business)"
                    else:
                        plan_name = "⭐️ Стандарт"

                    date_str = _format_date_display(new_expires_at)
                    logger.info(f"Auto-activated TON subscription for user {user_id}: {plan_name} (tx: {tx_hash})")

                    # 3. Отправляем уведомление пользователю в личку бота
                    try:
                        notify_text = (
                            "🎉 <b>Оплата через TON автоматически подтверждена!</b>\n\n"
                            f"• Тариф: <b>{plan_name}</b>\n"
                            f"• Получено: <b>{actual_ton:.2f} TON</b>\n"
                            f"• Хеш транзакции: <code>{tx_hash[:16]}...</code>\n"
                            f"• Срок действия: до <b>{date_str}</b>\n\n"
                            "🚀 Все возможности вашего тарифа уже активны и готовы к использованию!"
                        )
                        await bot.send_message(
                            chat_id=user_id,
                            text=notify_text,
                            reply_markup=get_main_menu_keyboard(),
                            parse_mode="HTML"
                        )
                    except Exception as e_notify:
                        logger.debug(f"Could not notify user {user_id} of auto TON payment: {e_notify}")

    except Exception as e:
        logger.error(f"Error in check_all_incoming_ton_transactions: {e}")


async def ton_background_checker(bot):
    """
    Фоновый воркер: каждые 45 секунд проверяет новые входящие платежи TON на кошельке.
    """
    logger.info("TON background payment checker worker started.")
    while True:
        try:
            await asyncio.sleep(45)
            await check_all_incoming_ton_transactions(bot)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in ton_background_checker: {e}")
