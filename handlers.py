import asyncio
import re
import random
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Union, Tuple
from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    LinkPreviewOptions,
    BusinessConnection,
    PreCheckoutQuery,
    LabeledPrice,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultPhoto,
    InputTextMessageContent,
    ChosenInlineResult,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile
)
import aiohttp
import urllib.parse
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

import database as db
import config
from config import (
    SUB_STANDARD_PRICE,
    SUB_PRO_PRICE,
    SUB_PREMIUM_PRICE,
    SUB_DURATION_DAYS,
    SUB_STANDARD_PRICE_TON,
    SUB_PRO_PRICE_TON,
    SUB_PREMIUM_PRICE_TON,
    TON_WALLET_ADDRESS
)
from parser import parse_nft_url, extract_buy_args, format_number, format_offer_timer, get_http_session
from keyboards import (
    get_screen1_keyboard,
    get_confirm_accept_keyboard,
    get_screen2_keyboard,
    get_screen3_buyer_keyboard,
    get_main_menu_keyboard,
    get_profile_keyboard,
    get_sub_menu_keyboard,
    get_back_to_menu_keyboard,
    get_buy_sub_keyboard,
    get_deals_keyboard,
    get_ton_payment_keyboard,
    get_star_invoice_keyboard,
    get_gift_admin_confirm_keyboard,
    get_plan_payment_method_keyboard,
    get_stargift_payment_keyboard,
    get_create_price_keyboard,
    get_create_confirm_keyboard
)
from ton_payments import get_ton_invoice_data, verify_ton_transaction

router = Router()
logger = logging.getLogger("nft_bot.handlers")

async def safe_answer(callback: CallbackQuery, text: str | None = None, show_alert: bool = False, url: str | None = None):
    try:
        await callback.answer(text=text, show_alert=show_alert, url=url)
    except Exception:
        pass

def format_date_display(dt_str: str) -> str:
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m.%Y в %H:%M")
    except Exception:
        return dt_str

def get_buyer_display(deal: dict) -> str:
    if deal.get("buyer_username"):
        return f"@{deal['buyer_username']}"
    return f"<a href='tg://user?id={deal['buyer_id']}'>{deal.get('buyer_first_name', 'Покупатель')}</a>"

def get_welcome_text() -> str:
    return (
        "👋 <b>Добро пожаловать в сервис безопасных P2P сделок на Telegram подарки!</b>\n\n"
        "Надёжный сервис для моментального создания и безопасного проведения офферов на покупку и продажу NFT-подарков.\n\n"
        "🚀 <b>Возможности:</b>\n"
        "• <b>Создание офферов</b> — моментальное формирование карточки с авто-таймером\n"
        "• <b>Инлайн-режим</b> — отправка оффера в любые чаты прямо через кнопку\n"
        "• <b>Telegram Business</b> — прямая доставка оффера в личные диалоги с продавцами\n"
        "• <b>P2P Эскроу</b> — безопасная передача предметов и верификация подарков\n"
        "• <b>Мгновенные выплаты</b> — Telegram Stars и TON\n\n"
        "👇 <i>Выберите действие в меню:</i>"
    )

class CreateOfferStates(StatesGroup):
    waiting_gift_url = State()
    waiting_price = State()
    confirm_send = State()
    waiting_recipient = State()

def build_randomized_offer_text(nft_name: str, nft_number: str, nft_url: str, stars_txt: str, timer_str: str, lang: str = "RU") -> Tuple[str, str]:
    """
    Генерирует рандомизированный текст оффера для защиты от спам-фильтров и блокировок Telegram.
    Возвращает (offer_text_html, clean_offer_text_plain).
    """
    if lang == "ENG":
        headers = [
            f"A user offers you <b>{stars_txt}</b> for gift <a href=\"{nft_url}\"><b>{nft_name} #{nft_number}</b></a>.",
            f"You received an offer of <b>{stars_txt}</b> for gift <a href=\"{nft_url}\"><b>{nft_name} #{nft_number}</b></a>.",
            f"New purchase offer for <a href=\"{nft_url}\"><b>{nft_name} #{nft_number}</b></a>: <b>{stars_txt}</b>.",
            f"A buyer wants to purchase <a href=\"{nft_url}\"><b>{nft_name} #{nft_number}</b></a> for <b>{stars_txt}</b>."
        ]
        clean_headers = [
            f"A user offers you {stars_txt} for gift {nft_name} #{nft_number}.",
            f"You received an offer of {stars_txt} for gift {nft_name} #{nft_number}.",
            f"New purchase offer for {nft_name} #{nft_number}: {stars_txt}.",
            f"A buyer wants to purchase {nft_name} #{nft_number} for {stars_txt}."
        ]
        footers = [
            f"Expires in {timer_str}.",
            f"Offer valid for {timer_str}.",
            f"Active for {timer_str}."
        ]
    else:
        headers = [
            f"Пользователь предлагает Вам <b>{stars_txt}</b> за подарок <a href=\"{nft_url}\"><b>{nft_name} #{nft_number}</b></a>.",
            f"Вам поступило предложение: <b>{stars_txt}</b> за подарок <a href=\"{nft_url}\"><b>{nft_name} #{nft_number}</b></a>.",
            f"Новый оффер на покупку подарка <a href=\"{nft_url}\"><b>{nft_name} #{nft_number}</b></a> на сумму <b>{stars_txt}</b>.",
            f"Покупатель готов приобрести <a href=\"{nft_url}\"><b>{nft_name} #{nft_number}</b></a> за <b>{stars_txt}</b>."
        ]
        clean_headers = [
            f"Пользователь предлагает Вам {stars_txt} за подарок {nft_name} #{nft_number}.",
            f"Вам поступило предложение: {stars_txt} за подарок {nft_name} #{nft_number}.",
            f"Новый оффер на покупку подарка {nft_name} #{nft_number} на сумму {stars_txt}.",
            f"Покупатель готов приобрести {nft_name} #{nft_number} за {stars_txt}."
        ]
        footers = [
            f"Истекает через {timer_str}.",
            f"Срок действия: {timer_str}.",
            f"Действительно ещё {timer_str}.",
            f"Осталось времени: {timer_str}."
        ]

    idx = random.randint(0, len(headers) - 1)
    footer = random.choice(footers)
    offer_html = f"{headers[idx]}\n\n{footer}"
    offer_plain = f"{clean_headers[idx]}\n\n{footer}"
    return offer_html, offer_plain

def build_confirm_card_text(nft_data: dict, price: int, currency: str, lang: str, recipient: str = None) -> str:
    formatted_number = format_number(nft_data.get("number", "1"))
    guarantor = recipient or config.GIFT_RECIPIENT or "@DealNftOffer"
    if lang == "ENG":
        currency_word = "Stars" if currency == "STARS" else "GRAM"
        return (
            '📄 <b>Confirm sending:</b>\n\n'
            f'🎁 Gift: <a href="{nft_data.get("url", "")}"><b>{nft_data.get("name", "Telegram Gift")} #{formatted_number}</b></a>\n'
            f'⭐️ Price: <b>{price} {currency_word}</b>\n'
            f'🌐 Offer language: <b>English</b>\n'
            f'👤 Recipient: <b>{guarantor}</b>\n\n'
            'Send?'
        )
    else:
        currency_word = "звезд" if currency == "STARS" else "GRAM"
        return (
            '📄 <b>Подтверди отправку:</b>\n\n'
            f'🎁 Подарок: <a href="{nft_data.get("url", "")}"><b>{nft_data.get("name", "Telegram Gift")} #{formatted_number}</b></a>\n'
            f'⭐️ Цена: <b>{price} {currency_word}</b>\n'
            f'🌐 Язык оффера: <b>Русский</b>\n'
            f'👤 Получатель: <b>{guarantor}</b>\n\n'
            'Отправить?'
        )

async def build_profile_text(user, bot: Bot) -> str:
    user_id = user.id
    is_admin = user_id in config.ADMIN_IDS
    sub = await db.get_subscription(user_id)

    if is_admin:
        sub_status = "👑 <b>Администратор</b> (Бессрочный доступ)"
        plan_desc = "Тариф: <b>👑 Premium (Полный доступ)</b>"
        time_desc = "Срок: <b>Не ограничен</b>"
    elif sub:
        now = datetime.now(timezone.utc)
        try:
            exp_dt = datetime.strptime(sub["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            exp_dt = now

        p_name = "👑 <b>Premium (1000 ⭐️)</b>" if sub.get("plan") == "premium" else "⭐️ <b>Обычный (250 ⭐️)</b>"
        if exp_dt > now:
            sub_status = "🟢 <b>Активна</b>"
            plan_desc = f"Тариф: {p_name}"
            time_desc = f"Действует до: <b>{format_date_display(sub['expires_at'])}</b>"
        else:
            sub_status = "🔴 <b>Истекла</b>"
            plan_desc = f"Тариф: {p_name}"
            time_desc = f"Закончилась: <b>{format_date_display(sub['expires_at'])}</b>"
    else:
        sub_status = "⚪️ <b>Не активна</b>"
        plan_desc = "Тариф: <i>Отсутствует</i>"
        time_desc = f"<i>Оформите тариф Обычный (250 ⭐️) или Premium (1000 ⭐️)</i>"

    username_str = f"@{user.username}" if user.username else "—"
    first_name_str = user.first_name or "Пользователь"

    return (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
        f"👤 <b>Имя:</b> {first_name_str}\n"
        f"🏷 <b>Юзернейм:</b> {username_str}\n\n"
        f"⭐️ <b>Статус подписки:</b> {sub_status}\n"
        f"• {plan_desc}\n"
        f"• {time_desc}"
    )

@router.message(Command("profile"))
async def handle_profile_command(message: Message, bot: Bot):
    text = await build_profile_text(message.from_user, bot)
    await message.answer(text, reply_markup=get_profile_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "menu_profile")
async def handle_menu_profile(callback: CallbackQuery, bot: Bot):
    text = await build_profile_text(callback.from_user, bot)
    try:
        await callback.message.edit_text(text, reply_markup=get_profile_keyboard(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=get_profile_keyboard(), parse_mode="HTML")
    await safe_answer(callback)

# --- DEAL START DIRECT HANDLER (/start deal_123) ---

async def handle_deal_start_direct(message: Message, deal_id: int, bot: Bot):
    """
    Обрабатывает прямой переход продавца по кнопке «✅ Принять»: /start deal_123
    """
    deal = await db.get_deal(deal_id)
    if not deal:
        await message.answer(
            "❌ <b>Оффер не найден или срок его действия истёк.</b>",
            parse_mode="HTML"
        )
        return

    if deal.get("status") == "COMPLETED":
        await message.answer(
            "✅ <b>Эта сделка уже успешно завершена.</b>",
            parse_mode="HTML"
        )
        return

    if deal.get("status") in ("CANCELLED", "EXPIRED", "DECLINED"):
        await message.answer(
            "❌ <b>Срок действия этого оффера истёк или он был отменён.</b>",
            parse_mode="HTML"
        )
        return

    user = message.from_user
    if deal.get("status") in ("PENDING", "CONFIRMING"):
        await db.accept_deal(deal_id, seller_id=user.id, seller_username=user.username)
        await db.set_deal_status(deal_id, "ACCEPTED")
        config.DEAL_LAST_TIMERS.pop(deal_id, None)
        deal = await db.get_deal(deal_id)

        # Notify buyer
        try:
            buyer_display, _, _ = await get_deal_buyer_info(deal)
            formatted_num = format_number(deal["nft_number"])
            curr_name = "GRAM" if deal.get("currency") == "GRAM" else "Stars"
            seller_name = f"@{user.username}" if user.username else f"ID {user.id}"
            notify_text = (
                f"⚡️ <b>Продавец принял ваш оффер!</b>\n\n"
                f"🎁 <b>Подарок:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_num}</b></a>\n"
                f"⭐ <b>Сумма сделки:</b> <b>{deal['stars_amount']} {curr_name}</b>\n"
                f"👤 <b>Продавец:</b> {seller_name}\n"
                f"📍 <b>Статус:</b> Ожидается передача подарка получателю ({buyer_display})...\n\n"
                f"<i>Как только подарок поступит, сделка завершится автоматически!</i>"
            )
            await bot.send_message(
                chat_id=deal["buyer_id"],
                text=notify_text,
                parse_mode="HTML"
            )
        except Exception as e_notify:
            logger.debug(f"Could not notify buyer about accept: {e_notify}")

    buyer_display, target_url, is_premium = await get_deal_buyer_info(deal)
    formatted_number = format_number(deal["nft_number"])
    currency_name = "GRAM" if deal.get("currency") == "GRAM" else "Stars"
    deal_lang = deal.get("lang", "RU")

    if deal_lang == "ENG":
        screen2_text = (
            f"<b>Gift:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>\n"
            f"<b>Deal amount:</b> <b>{deal['stars_amount']} {currency_name}</b>\n"
            f"<b>Recipient:</b> {buyer_display}\n"
            f"<b>Status:</b> <b>Awaiting gift transfer</b>\n\n"
            f"<blockquote><b>Please transfer the gift to recipient ({buyer_display}) to complete the deal.</b></blockquote>\n\n"
            f"<b>Instructions:</b>\n"
            f"1. Tap <b>«Send gift... ↗»</b> to open chat with {buyer_display}.\n"
            f"2. In profile, select gift <b>{deal['nft_name']} #{formatted_number}</b> and confirm transfer.\n"
            f"3. Return to this chat and tap <b>«Gift sent»</b>.\n\n"
            f"<i>Funds will be credited once the transfer is confirmed.</i>"
        )
    else:
        screen2_text = (
            f"<b>Подарок:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>\n"
            f"<b>Сумма сделки:</b> <b>{deal['stars_amount']} {currency_name}</b>\n"
            f"<b>Получатель:</b> {buyer_display}\n"
            f"<b>Статус:</b> <b>Ожидание передачи подарка</b>\n\n"
            f"<blockquote><b>Для завершения сделки передайте подарок получателю ({buyer_display}).</b></blockquote>\n\n"
            f"<b>Порядок передачи:</b>\n"
            f"1. Нажмите <b>«Отправить подарок... ↗»</b>, чтобы открыть диалог с {buyer_display}.\n"
            f"2. В профиле выберите подарок <b>{deal['nft_name']} #{formatted_number}</b> и подтвердите передачу.\n"
            f"3. Вернитесь в этот диалог и нажмите <b>«Подарок отправлен»</b>.\n\n"
            f"<i>После подтверждения передачи подарка баланс будет пополнен.</i>"
        )

    screen2_kb = get_screen2_keyboard(target_url=target_url, deal_id=deal_id, lang=deal_lang)
    link_opts = LinkPreviewOptions(
        url=deal["nft_url"],
        prefer_large_media=True,
        show_above_text=True
    )

    await message.answer(
        screen2_text,
        reply_markup=screen2_kb,
        link_preview_options=link_opts,
        parse_mode="HTML"
    )

# --- MENU & START NAVIGATION ---

@router.message(CommandStart())
async def handle_start(message: Message, command: CommandObject, bot: Bot):
    user_id = message.from_user.id
    await db.register_user(user_id, message.from_user.username, message.from_user.first_name)

    # Check for deal deep-link: /start deal_123 or /start accept_123
    arg = (command.args or "").strip()
    if arg:
        deal_id = None
        for prefix in ("deal_", "accept_", "offer_"):
            if arg.startswith(prefix):
                clean_id = arg.replace(prefix, "").strip()
                if clean_id.isdigit():
                    deal_id = int(clean_id)
                    break
        if deal_id:
            await handle_deal_start_direct(message, deal_id, bot)
            return

    is_admin = user_id in config.ADMIN_IDS
    await message.answer(get_welcome_text(), reply_markup=get_main_menu_keyboard(is_admin=is_admin), parse_mode="HTML")

@router.callback_query(F.data == "menu_main")
async def handle_menu_main(callback: CallbackQuery):
    is_admin = callback.from_user.id in config.ADMIN_IDS
    try:
        await callback.message.edit_text(get_welcome_text(), reply_markup=get_main_menu_keyboard(is_admin=is_admin), parse_mode="HTML")
    except Exception:
        await callback.message.answer(get_welcome_text(), reply_markup=get_main_menu_keyboard(is_admin=is_admin), parse_mode="HTML")
    await safe_answer(callback)

# --- OFFER CREATION WIZARD (DIRECT IN 1 BOT) ---

@router.message(Command("create"))
async def handle_cmd_create(message: Message, state: FSMContext):
    user_id = message.from_user.id
    is_active = await db.is_subscription_active(user_id)
    if not is_active:
        await message.answer(
            "❌ <b>Для создания офферов требуется активная подписка.</b>\n\n"
            "Оформите подписку в меню ниже, чтобы создавать официальные офферы:",
            reply_markup=get_buy_sub_keyboard(),
            parse_mode="HTML"
        )
        return

    await state.clear()
    await state.set_state(CreateOfferStates.waiting_gift_url)
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="create_cancel")]
    ])
    await message.answer(
        "🔗 <b>Введи ссылку на подарок:</b>\n\n"
        "<i>Пример:</i> <code>https://t.me/nft/BigYear-70698</code>\n\n"
        "💡 <i>Также можно отправить ссылку сразу с ценой:\n<code>https://t.me/nft/BigYear-70698 500</code></i>",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "menu_create")
async def handle_menu_create(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    is_active = await db.is_subscription_active(user_id)
    if not is_active:
        await safe_answer(callback, "Для создания офферов требуется активная подписка!", show_alert=True)
        try:
            await callback.message.answer(
                "❌ <b>Для создания офферов требуется активная подписка.</b>\n\n"
                "Оформите подписку в меню ниже, чтобы создавать официальные офферы:",
                reply_markup=get_buy_sub_keyboard(),
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    await state.clear()
    await state.set_state(CreateOfferStates.waiting_gift_url)
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="create_cancel")]
    ])
    await callback.message.answer(
        "🔗 <b>Введи ссылку на подарок:</b>\n\n"
        "<i>Пример:</i> <code>https://t.me/nft/BigYear-70698</code>\n\n"
        "💡 <i>Также можно отправить ссылку сразу с ценой:\n<code>https://t.me/nft/BigYear-70698 500</code></i>",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await safe_answer(callback)

async def process_gift_url(message: Message, state: FSMContext, input_text: str, price: Optional[int] = None):
    text = (input_text or "").strip()
    url_match = re.search(r'https?://\S+', text)
    if url_match:
        url = url_match.group(0)
    elif "t.me/nft/" in text or "fragment.com" in text:
        url = f"https://{text}" if not text.startswith("http") else text
    else:
        await message.answer(
            "❌ Пожалуйста, отправьте корректную ссылку на подарок (например, <code>https://t.me/nft/BigYear-70698</code>):",
            parse_mode="HTML"
        )
        return

    status_msg = await message.answer("🔎 <i>Определяю подарок...</i>", parse_mode="HTML")

    nft_data = await parse_nft_url(url)
    formatted_number = format_number(nft_data["number"])
    real_owner = nft_data.get("owner_username") or "Владелец"
    recipient = config.GIFT_RECIPIENT

    await state.update_data(
        nft_data=nft_data,
        currency="STARS",
        recipient=recipient,
        real_owner=real_owner,
        lang="RU",
        status_msg_id=status_msg.message_id
    )

    if price and price > 0:
        await state.update_data(price=price)
        card_text = build_confirm_card_text(nft_data, price, "STARS", "RU", recipient)
        link_opts = LinkPreviewOptions(
            url=nft_data.get("url"),
            prefer_large_media=True,
            show_above_text=True
        )
        await state.set_state(CreateOfferStates.confirm_send)
        try:
            await status_msg.delete()
        except Exception:
            pass
        is_premium = await db.is_subscription_active(message.from_user.id, required_plan="premium")
        await message.answer(
            card_text,
            reply_markup=get_create_confirm_keyboard("RU", is_premium=is_premium),
            link_preview_options=link_opts,
            parse_mode="HTML"
        )
        return

    await state.set_state(CreateOfferStates.waiting_price)
    resp_text = (
        f'✅ Подарок: <b>{nft_data["name"]} #{formatted_number}</b>\n'
        f'👤 Владелец: {real_owner}\n\n'
        f'⭐️ Введи цену в звёздах (число):'
    )
    try:
        await status_msg.edit_text(
            resp_text,
            reply_markup=get_create_price_keyboard("STARS"),
            parse_mode="HTML"
        )
    except Exception:
        await message.answer(
            resp_text,
            reply_markup=get_create_price_keyboard("STARS"),
            parse_mode="HTML"
        )

@router.message(CreateOfferStates.waiting_gift_url)
async def handle_create_gift_url(message: Message, state: FSMContext):
    await process_gift_url(message, state, message.text or "")

@router.message(F.text.regexp(r'(https?://)?(t\.me/nft/|fragment\.com/)\S+'))
async def handle_direct_nft_link(message: Message, state: FSMContext):
    user_id = message.from_user.id
    is_active = await db.is_subscription_active(user_id)
    if not is_active:
        return

    text = (message.text or "").strip()
    parts = text.split()
    url = None
    price = None
    for p in parts:
        if "t.me/nft/" in p or "fragment.com" in p:
            url = p
        elif re.sub(r'[^\d]', '', p).isdigit() and int(re.sub(r'[^\d]', '', p)) > 0:
            price = int(re.sub(r'[^\d]', '', p))

    await state.clear()
    await process_gift_url(message, state, url or text, price=price)

@router.callback_query(F.data == "create_toggle_currency", CreateOfferStates.waiting_price)
async def handle_create_toggle_currency(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_currency = data.get("currency", "STARS")
    new_currency = "GRAM" if current_currency == "STARS" else "STARS"
    await state.update_data(currency=new_currency)

    nft_data = data.get("nft_data", {"name": "Telegram Gift", "number": "1"})
    formatted_number = format_number(nft_data.get("number", "1"))
    real_owner = data.get("real_owner") or nft_data.get("owner_username") or "Владелец"

    price_prompt = '💎 Введи цену в GRAM (число):' if new_currency == "GRAM" else '⭐️ Введи цену в звёздах (число):'

    resp_text = (
        f'✅ Подарок: <b>{nft_data.get("name", "Telegram Gift")} #{formatted_number}</b>\n'
        f'👤 Владелец: {real_owner}\n\n'
        f'{price_prompt}'
    )
    try:
        await callback.message.edit_text(
            resp_text,
            reply_markup=get_create_price_keyboard(new_currency),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await safe_answer(callback)

@router.message(CreateOfferStates.waiting_price)
async def handle_create_price_input(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    clean_val = re.sub(r'[^\d]', '', text)
    if not clean_val.isdigit() or int(clean_val) <= 0:
        await message.answer("❌ Пожалуйста, введите положительное число:")
        return

    price = int(clean_val)
    if price > 5000000:
        await message.answer("❌ Сумма слишком велика. Укажите до 5 000 000:")
        return

    await state.update_data(price=price)
    data = await state.get_data()
    nft_data = data.get("nft_data", {"name": "Telegram Gift", "number": "1"})
    currency = data.get("currency", "STARS")
    lang = data.get("lang", "RU")
    recipient = data.get("recipient")

    card_text = build_confirm_card_text(nft_data, price, currency, lang, recipient)
    link_opts = LinkPreviewOptions(
        url=nft_data.get("url"),
        prefer_large_media=True,
        show_above_text=True
    )
    await state.set_state(CreateOfferStates.confirm_send)
    is_premium = await db.is_subscription_active(message.from_user.id, required_plan="premium")
    await message.answer(
        card_text,
        reply_markup=get_create_confirm_keyboard(lang, is_premium=is_premium),
        link_preview_options=link_opts,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "create_toggle_lang")
async def handle_create_toggle_lang(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    curr_lang = data.get("lang", "RU")
    new_lang = "ENG" if curr_lang == "RU" else "RU"
    await state.update_data(lang=new_lang)

    nft_data = data.get("nft_data", {"name": "Telegram Gift", "number": "1"})
    price = data.get("price", 0)
    currency = data.get("currency", "STARS")
    recipient = data.get("recipient")

    card_text = build_confirm_card_text(nft_data, price, currency, new_lang, recipient)
    link_opts = LinkPreviewOptions(
        url=nft_data.get("url"),
        prefer_large_media=True,
        show_above_text=True
    )
    is_premium = await db.is_subscription_active(callback.from_user.id, required_plan="premium")
    try:
        await callback.message.edit_text(
            card_text,
            reply_markup=get_create_confirm_keyboard(new_lang, is_premium=is_premium),
            link_preview_options=link_opts,
            parse_mode="HTML"
        )
    except Exception:
        pass
    await safe_answer(callback)

@router.callback_query(F.data == "create_change_recipient")
async def handle_create_change_recipient(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    is_premium = await db.is_subscription_active(user_id, required_plan="premium")
    if not is_premium:
        await safe_answer(callback, "Указание другого получателя доступно только на тарифе Premium!", show_alert=True)
        return

    await state.set_state(CreateOfferStates.waiting_recipient)
    await callback.message.answer("👤 <b>Введите @username или ID нового получателя:</b>", parse_mode="HTML")
    await safe_answer(callback)

@router.message(CreateOfferStates.waiting_recipient)
async def handle_create_recipient_input(message: Message, state: FSMContext):
    new_rec = (message.text or "").strip()
    if not new_rec.startswith("@") and not new_rec.isdigit():
        new_rec = "@" + new_rec

    await state.update_data(recipient=new_rec)
    data = await state.get_data()
    nft_data = data.get("nft_data", {"name": "Telegram Gift", "number": "1"})
    price = data.get("price", 0)
    currency = data.get("currency", "STARS")
    lang = data.get("lang", "RU")

    card_text = build_confirm_card_text(nft_data, price, currency, lang, new_rec)
    link_opts = LinkPreviewOptions(
        url=nft_data.get("url"),
        prefer_large_media=True,
        show_above_text=True
    )
    await state.set_state(CreateOfferStates.confirm_send)
    await message.answer(
        card_text,
        reply_markup=get_create_confirm_keyboard(lang, is_premium=True),
        link_preview_options=link_opts,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "create_cancel")
async def handle_create_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id in config.ADMIN_IDS
    await callback.message.answer("❌ Создание оффера отменено.", reply_markup=get_main_menu_keyboard(is_admin=is_admin))
    await safe_answer(callback, "Отменено")

@router.callback_query(F.data == "create_send")
async def handle_create_send(callback: CallbackQuery, state: FSMContext, bot: Bot):
    try:
        user = callback.from_user
        data = await state.get_data()
        nft_data = data.get("nft_data")
        if not nft_data:
            await safe_answer(callback, "Данные оффера устарели. Пожалуйста, создайте заново через /create", show_alert=True)
            return

        price = data.get("price", 0)
        currency = data.get("currency", "STARS")
        recipient = data.get("recipient") or config.GIFT_RECIPIENT
        target_seller = data.get("real_owner", "Владелец")
        clean_seller = target_seller.lstrip("@").strip()
        lang = data.get("lang", "RU")

        deal_id = await db.create_deal(
            buyer_id=user.id,
            buyer_username=user.username,
            buyer_first_name=user.first_name,
            seller_id=None,
            seller_username=target_seller,
            nft_name=nft_data["name"],
            nft_number=nft_data["number"],
            nft_url=nft_data["url"],
            image_url=nft_data.get("image_url"),
            stars_amount=price,
            chat_id=callback.message.chat.id,
            currency=currency,
            recipient=recipient,
            lang=lang
        )
        timer_str = "5 h. 59 min." if lang == "ENG" else "5 ч. 59 мин."
        config.DEAL_LAST_TIMERS[deal_id] = timer_str

        formatted_number = format_number(nft_data["number"])
        curr_symbol = "GRAM" if currency == "GRAM" else "⭐️"
        stars_txt = f"{price} {curr_symbol}" if curr_symbol == "GRAM" else f"{price} ⭐️"

        bot_info = await bot.get_me()
        bot_username = bot_info.username or "bot"

        offer_text, clean_offer_text = build_randomized_offer_text(
            nft_name=nft_data["name"],
            nft_number=formatted_number,
            nft_url=nft_data["url"],
            stars_txt=stars_txt,
            timer_str=timer_str,
            lang=lang
        )

        business_keyboard = get_screen1_keyboard(deal_id=deal_id, lang=lang, bot_username=bot_username, is_business=True)
        pm_keyboard = get_screen1_keyboard(deal_id=deal_id, lang=lang, bot_username=bot_username, is_business=False)

        link_opts = LinkPreviewOptions(
            is_disabled=False,
            url=nft_data["url"],
            prefer_large_media=True,
            show_above_text=True
        )

        target_chat_id = None
        target_business_conn_id = None

        if clean_seller.isdigit():
            target_chat_id = int(clean_seller)
        else:
            user_row = await db.find_user(clean_seller)
            if user_row:
                target_chat_id = user_row["user_id"]

        buyer_conn = await db.get_business_connection_by_user(user.id)
        has_own_biz = bool(buyer_conn and buyer_conn.get("is_enabled") and buyer_conn.get("can_reply"))
        if has_own_biz:
            target_business_conn_id = buyer_conn.get("connection_id")

        sent_to_owner = False
        sent_via_biz = False
        sent_msg = None

        if target_chat_id and target_business_conn_id:
            try:
                sent_msg = await bot.send_message(
                    business_connection_id=target_business_conn_id,
                    chat_id=target_chat_id,
                    text=offer_text,
                    reply_markup=business_keyboard,
                    link_preview_options=link_opts,
                    parse_mode="HTML"
                )
                sent_to_owner = True
                sent_via_biz = True
                await db.update_deal_target(deal_id, target_chat_id, sent_msg.message_id, target_business_conn_id)
            except Exception as e_biz:
                logger.warning(f"Business send failed: {e_biz}")

        if not sent_to_owner and target_chat_id:
            try:
                sent_msg = await bot.send_message(
                    chat_id=target_chat_id,
                    text=offer_text,
                    reply_markup=pm_keyboard,
                    link_preview_options=link_opts,
                    parse_mode="HTML"
                )
                sent_to_owner = True
                await db.update_deal_target(deal_id, target_chat_id, sent_msg.message_id, None)
            except Exception:
                pass

        try:
            await callback.message.delete()
        except Exception:
            pass

        chat_id = callback.message.chat.id

        share_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="↗️ Отправить оффер",
                    switch_inline_query=f"deal_{deal_id}"
                )
            ],
            [
                InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
            ]
        ])

        if has_own_biz and sent_via_biz:
            extra_msg = f"✅ <b>Оффер успешно доставлен продавцу ({target_seller}) через ваш Telegram Business!</b>"
        elif sent_to_owner:
            extra_msg = f"⚡ <i>Оффер отправлен ботом в диалог с {target_seller}.</i>\n\n👉 <b>Также вы можете переслать карточку кнопкой ниже:</b>"
        else:
            extra_msg = f"👉 <b>Нажмите кнопку ниже, чтобы отправить карточку оффера в чат продавцу:</b>"

        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ <b>Оффер #{deal_id} успешно сформирован!</b>\n\n"
                f"🎁 <b>Подарок:</b> <b>{nft_data['name']} #{formatted_number}</b>\n"
                f"⭐ <b>Сумма:</b> <b>{stars_txt}</b>\n"
                f"👤 <b>Получатель:</b> <b>{recipient}</b>\n\n"
                f"{extra_msg}"
            ),
            reply_markup=share_kb,
            parse_mode="HTML"
        )

        await state.clear()
        await safe_answer(callback, "Оффер создан!")
    except Exception as e:
        logger.exception(f"Error in handle_create_send: {e}")
        await safe_answer(callback, f"Ошибка при отправке: {e}", show_alert=True)

# --- INLINE QUERY & BUSINESS HANDLERS (IN 1 BOT) ---

@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery, bot: Bot):
    user = inline_query.from_user
    is_active = await db.is_subscription_active(user.id)
    if not is_active:
        article = InlineQueryResultArticle(
            id="sub_required",
            title="🔒 Требуется подписка",
            description="Оформите подписку в боте для использования инлайн-режима.",
            input_message_content=InputTextMessageContent(
                message_text="Для отправки офферов оформите подписку в сервисе."
            )
        )
        await inline_query.answer([article], cache_time=1, is_personal=True)
        return

    query_text = (inline_query.query or "").strip()
    bot_info = await bot.get_me()
    bot_uname = bot_info.username or "bot"

    if query_text.startswith("deal_"):
        clean_deal_id = query_text.replace("deal_", "").strip()
        if clean_deal_id.isdigit():
            deal_id = int(clean_deal_id)
            deal = await db.get_deal(deal_id)
            if deal and deal["status"] in ("PENDING", "CONFIRMING"):
                formatted_number = format_number(deal["nft_number"])
                curr_symbol = "GRAM" if deal.get("currency") == "GRAM" else "⭐️"
                price_txt = f"{deal['stars_amount']} {curr_symbol}"
                deal_lang = deal.get("lang", "RU")
                timer_str = "5 h. 59 min." if deal_lang == "ENG" else "5 ч. 59 мин."

                offer_html, _ = build_randomized_offer_text(
                    nft_name=deal["nft_name"],
                    nft_number=formatted_number,
                    nft_url=deal["nft_url"],
                    stars_txt=price_txt,
                    timer_str=timer_str,
                    lang=deal_lang
                )
                link_opts = LinkPreviewOptions(
                    is_disabled=False,
                    url=deal["nft_url"],
                    prefer_large_media=True
                )
                article = InlineQueryResultArticle(
                    id=f"deal_{deal_id}",
                    title=f"🎁 Оффер: {deal['nft_name']} #{formatted_number}",
                    description=f"Предложить {price_txt} за подарок",
                    input_message_content=InputTextMessageContent(
                        message_text=offer_html,
                        parse_mode="HTML",
                        link_preview_options=link_opts
                    ),
                    reply_markup=get_screen1_keyboard(deal_id=deal_id, lang=deal_lang, bot_username=bot_uname)
                )
                await inline_query.answer([article], cache_time=1, is_personal=True)
                return

    hint = InlineQueryResultArticle(
        id="hint",
        title="💡 Отправка оффера",
        description="Создайте оффер через /create в боте и нажмите «Отправить оффер»",
        input_message_content=InputTextMessageContent(
            message_text=f"Создайте оффер в диалоге с @{bot_uname} через команду /create.",
            parse_mode="HTML"
        )
    )
    await inline_query.answer([hint], cache_time=1, is_personal=True)

@router.chosen_inline_result()
async def handle_chosen_inline_result(result: ChosenInlineResult):
    if result.result_id.startswith("deal_"):
        clean_id = result.result_id.replace("deal_", "").strip()
        if clean_id.isdigit():
            deal_id = int(clean_id)
            if result.inline_message_id:
                await db.set_deal_inline_message_id(deal_id, result.inline_message_id)

@router.business_connection()
async def handle_business_connection(conn: BusinessConnection, bot: Bot):
    await db.save_business_connection(
        connection_id=conn.id,
        user_id=conn.user.id,
        user_username=conn.user.username,
        can_reply=conn.can_reply,
        is_enabled=conn.is_enabled
    )
    if conn.is_enabled and conn.can_reply:
        try:
            await bot.send_message(
                chat_id=conn.user.id,
                text="✅ <b>Telegram Business подключён успешно!</b>\nТеперь бот может автоматически отправлять карточки офферов напрямую в ваши личные диалоги с продавцами.",
                parse_mode="HTML"
            )
        except Exception:
            pass

@router.business_message()
async def handle_business_message_tracker(message: Message):
    if message.chat and message.chat.type == "private":
        await db.register_user(
            user_id=message.chat.id,
            username=message.chat.username,
            first_name=message.chat.first_name
        )

@router.callback_query(F.data == "menu_business")
async def handle_menu_business(callback: CallbackQuery, bot: Bot):
    bot_info = await bot.get_me()
    uname = bot_info.username or "tggarantofferbot"
    conn = await db.get_business_connection_by_user(callback.from_user.id)
    is_connected = bool(conn and conn.get("is_enabled") and conn.get("can_reply"))
    status_str = "🟢 <b>Подключен</b>" if is_connected else "⚪️ <b>Не подключен</b>"

    text = (
        f"💼 <b>Telegram Business</b>\n\n"
        f"Статус: {status_str}\n\n"
        f"Подключение Telegram Business позволяет отправлять офферы напрямую в диалог продавцу от вашего лица без пересылки!\n\n"
        f"📌 <b>Как подключить:</b>\n"
        f"1️⃣ Откройте <i>Настройки Telegram</i> на телефоне или компьютере\n"
        f"2️⃣ Перейдите в раздел <b>Telegram Business ➔ Чат-боты</b>\n"
        f"3️⃣ В поиске найдите нашего бота: <b>@{uname}</b>\n"
        f"4️⃣ Включите разрешение <b>«Отвечать на сообщения»</b>\n\n"
        f"<i>После этого бот сможет автоматически отправлять созданные вами офферы в диалоги!</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await safe_answer(callback)

# --- MY DEALS HANDLERS ---

@router.callback_query(F.data.in_(["menu_my_deals", "menu_deals"]))
@router.message(Command("deals"))
async def handle_menu_my_deals(event: Message | CallbackQuery):
    user_id = event.from_user.id
    deals = await db.get_deals_by_buyer(user_id, limit=8)

    if not deals:
        text = (
            "📋 <b>Ваши сделки</b>\n\n"
            "У вас пока нет созданных офферов.\n\n"
            "Нажмите «Создать оффер», чтобы сделать ваше первое предложение на покупку подарка!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✨ Создать оффер", callback_data="menu_create")],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")]
        ])
    else:
        status_map = {
            "PENDING": "⏳ Ожидает ответа",
            "CONFIRMING": "⏳ Подтверждение",
            "ACCEPTED": "🔄 Принят продавцом",
            "SENT": "📦 Подарок отправлен",
            "COMPLETED": "✅ Успешно завершён",
            "DECLINED": "❌ Отклонён",
            "EXPIRED": "⌛️ Истёк",
            "CANCELLED": "🚫 Отменён"
        }
        lines = ["📋 <b>Ваши последние сделки:</b>\n"]
        kb_rows = []
        for d in deals:
            st = status_map.get(d.get("status"), d.get("status"))
            num = format_number(d.get("nft_number", "1"))
            cur = "GRAM" if d.get("currency") == "GRAM" else "⭐️"
            lines.append(
                f"• <b>#{d['deal_id']}</b>: {d.get('nft_name', 'Gift')} #{num} — "
                f"<b>{d['stars_amount']} {cur}</b> ({st})"
            )
            if d.get("status") in ("PENDING", "CONFIRMING"):
                kb_rows.append([
                    InlineKeyboardButton(
                        text=f"↗️ Отправить оффер #{d['deal_id']}",
                        switch_inline_query=f"deal_{d['deal_id']}"
                    )
                ])

        kb_rows.append([
            InlineKeyboardButton(text="🔄 Обновить", callback_data="menu_my_deals"),
            InlineKeyboardButton(text="✨ Создать новый", callback_data="menu_create")
        ])
        kb_rows.append([
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
        ])
        text = "\n".join(lines)
        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
        await safe_answer(event)
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")

# --- SUBSCRIPTION MENU (ЕДИНАЯ ПОДПИСКА 250 STARS) ---

@router.callback_query(F.data == "menu_sub")
@router.message(Command("subscribe", "sub"))
async def handle_subscription_view(event: Message | CallbackQuery):
    user_id = event.from_user.id
    await db.register_user(user_id, event.from_user.username, event.from_user.first_name)
    sub = await db.get_subscription(user_id)
    is_active = await db.is_subscription_active(user_id)

    if is_active and sub:
        date_str = format_date_display(sub["expires_at"])
        p_badge = "👑 <b>Premium</b>" if sub.get("plan") == "premium" else "⭐️ <b>Обычный</b>"
        status_text = (
            f"• Ваш тариф: {p_badge}\n"
            f"• Статус подписки: 🟢 <b>Активна до {date_str}</b>\n\n"
        )
    else:
        status_text = "• Статус подписки: 🔴 <b>Не активна</b>\n\n"

    text = (
        "⭐️ <b>Тарифы и подписка</b>\n\n"
        f"{status_text}"
        "<b>Выберите подходящий тариф:</b>\n\n"
        f"1. <b>⭐️ Обычный — {config.SUB_STANDARD_PRICE} ⭐️ ({config.SUB_STANDARD_PRICE_TON} TON) / {config.SUB_DURATION_DAYS} дней</b>\n"
        "• Создание официальных офферов (/create)\n"
        "• Доставка офферов через Telegram Business в личные диалоги\n"
        "• Инлайн-режим отправки в любых чатах\n"
        f"• Передача подарка строго официальному гаранту ({config.GIFT_RECIPIENT})\n\n"
        f"2. <b>👑 Premium — {config.SUB_PREMIUM_PRICE} ⭐️ ({config.SUB_PREMIUM_PRICE_TON} TON) / {config.SUB_DURATION_DAYS} дней</b>\n"
        "• Все функции обычного тарифа\n"
        "• 👤 <b>Возможность указывать ЛЮБОГО своего получателя</b> (другой аккаунт/кошелёк) при отправке оффера\n"
        "• Приоритетная поддержка и обработка\n\n"
        "<i>Нажмите кнопку ниже для выбора тарифа:</i>"
    )

    keyboard = get_sub_menu_keyboard()
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        await safe_answer(event)
    else:
        await event.answer(text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("select_plan:"))
async def handle_select_plan(callback: CallbackQuery):
    plan = callback.data.split(":")[1] if ":" in callback.data else "standard"
    if plan == "premium":
        plan_title = "👑 <b>Тариф «Premium»</b>"
        stars_price = config.SUB_PREMIUM_PRICE
        ton_price = config.SUB_PREMIUM_PRICE_TON
        desc = (
            "• Создание офферов через бота (/create)\n"
            "• Доставка офферов через Telegram Business в личных переписках\n"
            "• Инлайн-режим в любых чатах через <code>@bot ссылка цена</code>\n"
            "• 👤 <b>Возможность указывать ЛЮБОГО своего получателя подарка!</b>\n"
            f"• Срок действия: <b>{config.SUB_DURATION_DAYS} дней</b>"
        )
    else:
        plan = "standard"
        plan_title = "⭐️ <b>Тариф «Обычный»</b>"
        stars_price = config.SUB_STANDARD_PRICE
        ton_price = config.SUB_STANDARD_PRICE_TON
        desc = (
            "• Создание офферов через бота (/create)\n"
            "• Доставка офферов через Telegram Business в личных переписках\n"
            "• Инлайн-режим в любых чатах через <code>@bot ссылка цена</code>\n"
            f"• Передача подарка строго официальному гаранту ({config.GIFT_RECIPIENT})\n"
            f"• Срок действия: <b>{config.SUB_DURATION_DAYS} дней</b>"
        )

    text = (
        f"{plan_title}\n\n"
        f"{desc}\n\n"
        f"💰 <b>Стоимость:</b> <code>{stars_price} Stars</code> или <code>{ton_price} TON</code>\n\n"
        f"<i>Выберите способ оплаты:</i>"
    )

    kb = get_plan_payment_method_keyboard(plan)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await safe_answer(callback)

@router.callback_query(F.data == "menu_business")
async def handle_menu_business(callback: CallbackQuery):
    text = (
        "💼 <b>Подключение Telegram Business</b>\n\n"
        "Чтобы бот автоматически доставлял офферы прямо в ваши личные диалоги с продавцами:\n\n"
        "1. Перейдите в <b>Настройки</b> Telegram (нужен Telegram Premium).\n"
        "2. Откройте <b>Telegram Business</b> ➡️ <b>Чат-боты</b>.\n"
        "3. Добавьте бота и включите <b>«Управление чатами»</b>.\n\n"
        "После этого офферы, сформированные через бота, будут отправляться напрямую в диалог с продавцом."
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")
    except Exception:
        pass
    await safe_answer(callback)

@router.business_connection()
async def handle_main_business_connection(conn: BusinessConnection, bot: Bot):
    await db.save_business_connection(
        connection_id=conn.id,
        user_id=conn.user.id,
        user_username=conn.user.username,
        can_reply=conn.can_reply,
        is_enabled=conn.is_enabled
    )
    if conn.is_enabled and conn.can_reply:
        try:
            await bot.send_message(
                chat_id=conn.user.id,
                text="✅ <b>Telegram Business подключён успешно!</b>\nЧат-бот активирован и готов к отправке офферов.",
                parse_mode="HTML"
            )
        except Exception:
            pass

@router.business_message()
async def handle_main_business_message(message: Message):
    if message.chat and message.chat.type == "private":
        await db.register_user(
            user_id=message.chat.id,
            username=message.chat.username,
            first_name=message.chat.first_name
        )

# --- PAYMENT PROCESSING (STAR GIFTS & PRO) ---

@router.callback_query(F.data.startswith("pay_stargift:"))
async def handle_pay_stargift(callback: CallbackQuery):
    user_id = callback.from_user.id
    target_plan = callback.data.split(":")[1] if ":" in callback.data else "standard"
    if target_plan == "premium":
        price = SUB_PREMIUM_PRICE
        plan_title = "👑 Premium (100% профита)"
    elif target_plan == "pro":
        price = SUB_PRO_PRICE
        plan_title = "💎 PRO (Инлайн + Business)"
    else:
        price = SUB_STANDARD_PRICE
        plan_title = "⭐️ Стандарт (Business)"

    clean_recip = config.GIFT_RECIPIENT.lstrip("@").strip()
    profile_url = f"https://t.me/{clean_recip}"

    text = (
        f"🎁 <b>Оплата тарифа «{plan_title}» подарком Stars</b>\n\n"
        f"Для моментальной активации подписки отправьте подарок на <b>{price} Stars ⭐️</b> в личный профиль <b>{config.GIFT_RECIPIENT}</b>:\n\n"
        f"<b>Инструкция по оплате:</b>\n"
        f"1. Нажмите кнопку <b>«🎁 Открыть профиль и подарить {price} ⭐️»</b> ниже.\n"
        f"2. В профиле <b>{config.GIFT_RECIPIENT}</b> нажмите на три точки `⋮` в правом верхнем углу ➡️ <b>«Отправить подарок»</b>.\n"
        f"3. Отправьте один или несколько подарков на общую сумму от <b>{price} Stars</b> (можно отправить несколько небольших подарков частями, бот автоматически просуммирует их! Главное — отправляйте <u>НЕ анонимно</u>, чтобы система распознала ваш аккаунт).\n"
        f"4. После отправки вернитесь в этот диалог и нажмите <b>«🔄 Проверить получение подарка»</b>.\n\n"
        f"<i>Звёзды поступят напрямую на личный профиль, а бот мгновенно выдаст подписку!</i>"
    )

    kb = get_stargift_payment_keyboard(profile_url=profile_url, plan=target_plan, user_id=user_id, price=price)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await safe_answer(callback)

@router.callback_query(F.data.startswith("pay_sub"))
async def handle_pay_sub(callback: CallbackQuery, bot: Bot):
    await handle_pay_stargift(callback)

@router.callback_query(F.data.startswith("check_gift_sub:"))
async def handle_check_gift_sub(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    plan = parts[1]
    user_id = int(parts[2])

    if callback.from_user.id != user_id:
        await safe_answer(callback, "Это не ваш счёт!", show_alert=True)
        return

    if plan == "premium":
        price = SUB_PREMIUM_PRICE
        plan_name = "👑 Premium (100% профита)"
    elif plan == "pro":
        price = SUB_PRO_PRICE
        plan_name = "💎 PRO / Инлайн"
    else:
        price = SUB_STANDARD_PRICE
        plan_name = "⭐️ Стандарт"
    user = callback.from_user

    await safe_answer(callback, "🔍 Проверяем получение подарка...")

    try:
        user_gifts = await bot.get_user_gifts(user_id=config.GIFT_RECIPIENT_ID)
        gifts_list = user_gifts.gifts if user_gifts and user_gifts.gifts else []

        unused_user_gifts = []
        total_user_stars = 0

        for g in gifts_list:
            sender = getattr(g, "sender_user", None)
            if not sender or sender.id != user_id:
                continue

            inner_gift = getattr(g, "gift", None)
            star_count = getattr(inner_gift, "star_count", 0) if inner_gift else 0
            if star_count <= 0:
                continue

            gift_unique_id = getattr(g, "owned_gift_id", None) or f"gift_{user_id}_{getattr(g, 'send_date', 0)}_{star_count}"
            already_used = await db.is_charge_id_used(gift_unique_id)
            if already_used:
                continue

            unused_user_gifts.append({
                "gift_id": gift_unique_id,
                "stars": star_count,
                "gift": g
            })
            total_user_stars += star_count

        if total_user_stars >= price:
            effective_plan = plan
            effective_plan_name = plan_name
            if total_user_stars >= SUB_PREMIUM_PRICE:
                effective_plan = "premium"
                effective_plan_name = "👑 Premium (100% профита)"
            elif total_user_stars >= SUB_PRO_PRICE and plan != "premium":
                effective_plan = "pro"
                effective_plan_name = "💎 PRO / Инлайн"

            for item in unused_user_gifts:
                await db.record_payment(
                    user_id=user.id,
                    amount=item["stars"],
                    currency="XTR",
                    charge_id=item["gift_id"],
                    payload=f"gift_sub_{effective_plan}"
                )

            primary_charge = unused_user_gifts[0]["gift_id"]
            new_expires_at = await db.add_or_extend_subscription(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                days=SUB_DURATION_DAYS,
                plan=effective_plan,
                charge_id=primary_charge
            )

            date_str = format_date_display(new_expires_at)
            success_text = (
                "🎉 <b>Подарки получены и подтверждены автоматически!</b>\n\n"
                f"• Тариф: <b>{effective_plan_name}</b>\n"
                f"• Подарков зачислено: <b>{len(unused_user_gifts)} шт.</b>\n"
                f"• Общая сумма: <b>{total_user_stars} Stars ⭐️</b>\n"
                f"• Срок действия: до <b>{date_str}</b>\n\n"
                "Подписка успешно активирована, приятного использования!"
            )
            try:
                await callback.message.edit_text(success_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
            except Exception:
                await callback.message.answer(success_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")

            try:
                username_display = f"@{user.username}" if user.username else f"ID {user.id}"
                await bot.send_message(
                    chat_id=config.GIFT_RECIPIENT_ID,
                    text=(
                        f"⚡️ <b>Автоматическая оплата подписки подарками!</b>\n\n"
                        f"• Пользователь: {username_display} (ID: <code>{user.id}</code>)\n"
                        f"• Тариф: <b>{effective_plan_name}</b> (Сумма: {total_user_stars} ⭐️, {len(unused_user_gifts)} шт.)\n"
                        f"• Подписка активирована моментально через API!"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return
        elif total_user_stars > 0:
            diff = price - total_user_stars
            await safe_answer(
                callback,
                f"⚠️ Найдено подарков на {total_user_stars} из {price} ⭐️!\nНе хватает ещё {diff} ⭐️. Отправьте ещё подарок на сумму от {diff} Stars и нажмите «Проверить оплату» снова.",
                show_alert=True
            )
            return

    except Exception as e:
        logger.error(f"Error checking user gifts automatically: {e}")

    await safe_answer(
        callback,
        "❌ Подарок пока не отобразился в системе.\n1. Убедитесь, что отправили подарок НЕ анонимно.\n2. Подождите 5-10 секунд и нажмите «Проверить оплату» снова.\n3. Если подарок отправлен, но не находится — нажмите кнопку «Не проверяется? Отправить заявку».",
        show_alert=True
    )


async def check_all_incoming_star_gifts(bot: Bot):
    """
    Фоновая проверка входящих Telegram-подарков за Stars в профиле получателя (GIFT_RECIPIENT_ID).
    Суммирует все подарки от каждого пользователя, автоматически распознает сумму,
    определяет тариф и активирует подписку без нажатия кнопок.
    """
    try:
        user_gifts = await bot.get_user_gifts(user_id=config.GIFT_RECIPIENT_ID)
        if not user_gifts or not user_gifts.gifts:
            return

        user_gifts_map: dict[int, list[dict]] = {}
        user_senders: dict[int, Any] = {}

        for g in user_gifts.gifts:
            sender = getattr(g, "sender_user", None)
            if not sender or not sender.id:
                continue

            user_id = sender.id
            inner_gift = getattr(g, "gift", None)
            star_count = getattr(inner_gift, "star_count", 0) if inner_gift else 0
            if star_count <= 0:
                continue

            gift_unique_id = getattr(g, "owned_gift_id", None) or f"gift_{user_id}_{getattr(g, 'send_date', 0)}_{star_count}"
            already_used = await db.is_charge_id_used(gift_unique_id)
            if already_used:
                continue

            if user_id not in user_gifts_map:
                user_gifts_map[user_id] = []
                user_senders[user_id] = sender

            user_gifts_map[user_id].append({
                "gift_id": gift_unique_id,
                "stars": star_count,
                "gift": g
            })

        for user_id, items in user_gifts_map.items():
            total_stars = sum(it["stars"] for it in items)
            if total_stars < SUB_STANDARD_PRICE:
                continue

            # Определяем тариф по общей сумме звёзд всех подарков пользователя
            if total_stars >= SUB_PREMIUM_PRICE:
                plan = "premium"
                plan_name = "👑 Premium (100% профита)"
            elif total_stars >= SUB_PRO_PRICE:
                plan = "pro"
                plan_name = "💎 PRO (Инлайн + Business)"
            else:
                plan = "standard"
                plan_name = "⭐️ Стандарт"

            # 1. Записываем каждый использованный подарок в базу
            for it in items:
                await db.record_payment(
                    user_id=user_id,
                    amount=it["stars"],
                    currency="XTR",
                    charge_id=it["gift_id"],
                    payload=f"gift_auto_sub_{plan}"
                )

            primary_charge = items[0]["gift_id"]
            sender = user_senders[user_id]

            # 2. Активируем подписку
            new_expires_at = await db.add_or_extend_subscription(
                user_id=user_id,
                username=sender.username,
                first_name=sender.first_name or "User",
                days=SUB_DURATION_DAYS,
                plan=plan,
                charge_id=primary_charge
            )

            date_str = format_date_display(new_expires_at)
            logger.info(f"Auto-activated Star Gifts subscription for user {user_id}: {plan_name} ({total_stars} Stars in {len(items)} gifts)")

            # 3. Уведомление пользователю
            try:
                success_text = (
                    "🎉 <b>Оплата подарками за Stars автоматически подтверждена!</b>\n\n"
                    f"• Тариф: <b>{plan_name}</b>\n"
                    f"• Подарков зачислено: <b>{len(items)} шт.</b>\n"
                    f"• Общая сумма: <b>{total_stars} Stars ⭐️</b>\n"
                    f"• Срок действия: до <b>{date_str}</b>\n\n"
                    "🚀 Подписка успешно активирована без ручной проверки, приятного использования!"
                )
                await bot.send_message(
                    chat_id=user_id,
                    text=success_text,
                    reply_markup=get_main_menu_keyboard(),
                    parse_mode="HTML"
                )
            except Exception as e_notify:
                logger.debug(f"Could not notify user {user_id} of auto Star Gift: {e_notify}")

            # 4. Уведомление получателю/админу
            try:
                username_display = f"@{sender.username}" if sender.username else f"ID {user_id}"
                await bot.send_message(
                    chat_id=config.GIFT_RECIPIENT_ID,
                    text=(
                        f"⚡️ <b>Автоматически зачислены подарки за Stars!</b>\n\n"
                        f"• Пользователь: {username_display} (ID: <code>{user_id}</code>)\n"
                        f"• Тариф: <b>{plan_name}</b> (Сумма: {total_stars} ⭐️, {len(items)} подарков)\n"
                        f"• Подписка активирована моментально через API!"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass

    except Exception as e:
        if "user not found" in str(e):
            logger.debug(f"check_all_incoming_star_gifts: {e}")
        else:
            logger.error(f"Error in check_all_incoming_star_gifts: {e}")


async def star_gifts_background_checker(bot: Bot):
    """
    Фоновый воркер: каждые 45 секунд проверяет новые входящие Star Gifts в профиле получателя.
    """
    logger.info("Star Gifts background payment checker worker started.")
    while True:
        try:
            await asyncio.sleep(45)
            await check_all_incoming_star_gifts(bot)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in star_gifts_background_checker: {e}")

@router.callback_query(F.data.startswith("gift_sent:"))
async def handle_gift_sent(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    plan = parts[1]
    user_id = int(parts[2])

    if callback.from_user.id != user_id:
        await safe_answer(callback, "Это не ваше действие!", show_alert=True)
        return

    if plan == "premium":
        price = SUB_PREMIUM_PRICE
        plan_name = "👑 Premium (100% профита)"
    elif plan == "pro":
        price = SUB_PRO_PRICE
        plan_name = "💎 PRO / Инлайн"
    else:
        price = SUB_STANDARD_PRICE
        plan_name = "⭐️ Стандарт"
    user = callback.from_user
    username_display = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"

    wait_text = (
        "⏳ <b>Заявка отправлена на ручную проверку!</b>\n\n"
        f"Тариф: <b>{plan_name}</b> ({price} Stars)\n\n"
        f"Администратор проверяет получение подарка.\n"
        f"Как только подарок будет подтверждён, ваша подписка активируется автоматически!"
    )
    try:
        await callback.message.edit_text(wait_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(wait_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
    await safe_answer(callback, "Уведомление отправлено администратору!")

    admin_confirm_kb = get_gift_admin_confirm_keyboard(plan=plan, user_id=user_id)
    admin_notice = (
        f"🎁 <b>Новая оплата подписки подарком Stars!</b>\n\n"
        f"• Пользователь: {username_display} (ID: <code>{user_id}</code>)\n"
        f"• Тариф: <b>{plan_name}</b> ({price} Stars)\n"
        f"• Получатель: <b>{config.GIFT_RECIPIENT}</b>\n\n"
        f"Проверьте подарки в профиле {config.GIFT_RECIPIENT}. Если подарок на {price} Stars получен, подтвердите выдачу подписки:"
    )

    recipients = list(set([config.GIFT_RECIPIENT_ID] + config.ADMIN_IDS))
    for adm_id in recipients:
        try:
            await bot.send_message(
                chat_id=adm_id,
                text=admin_notice,
                reply_markup=admin_confirm_kb,
                parse_mode="HTML"
            )
        except Exception:
            pass

@router.callback_query(F.data.startswith("confirm_gift_sub:"))
async def handle_confirm_gift_sub(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in config.ADMIN_IDS and callback.from_user.id != config.GIFT_RECIPIENT_ID:
        await safe_answer(callback, "У вас нет прав для подтверждения!", show_alert=True)
        return

    parts = callback.data.split(":")
    plan = parts[1]
    target_user_id = int(parts[2])
    if plan == "premium":
        price = SUB_PREMIUM_PRICE
        plan_name = "👑 Premium (100% профита)"
    elif plan == "pro":
        price = SUB_PRO_PRICE
        plan_name = "💎 PRO / Инлайн"
    else:
        price = SUB_STANDARD_PRICE
        plan_name = "⭐️ Стандарт"

    await db.record_payment(
        user_id=target_user_id,
        amount=price,
        currency="XTR",
        charge_id=f"gift_sub_{plan}_{target_user_id}_{int(datetime.now(timezone.utc).timestamp())}",
        payload=f"gift_sub_{plan}"
    )

    new_expires_at = await db.add_or_extend_subscription(
        user_id=target_user_id,
        username=None,
        first_name="Пользователь",
        days=SUB_DURATION_DAYS,
        plan=plan,
        charge_id=f"GIFT_{callback.from_user.id}"
    )

    date_str = format_date_display(new_expires_at)

    try:
        await callback.message.edit_text(
            f"✅ <b>Подписка успешно выдана!</b>\n\n"
            f"Пользователь ID: <code>{target_user_id}</code>\n"
            f"Тариф: <b>{plan_name}</b> ({price} Stars)\n"
            f"Действует до: <b>{date_str}</b>\n"
            f"Подтвердил: @{callback.from_user.username or callback.from_user.id}",
            reply_markup=None,
            parse_mode="HTML"
        )
    except Exception:
        pass

    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=(
                "🎉 <b>Ваш подарок подтверждён!</b>\n\n"
                f"Тариф: <b>{plan_name}</b>\n"
                f"Срок действия: до <b>{date_str}</b>\n\n"
                "Подписка успешно активирована, приятного использования!"
            ),
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await safe_answer(callback, "Подписка выдана пользователю!")

@router.callback_query(F.data.startswith("decline_gift_sub:"))
async def handle_decline_gift_sub(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in config.ADMIN_IDS and callback.from_user.id != config.GIFT_RECIPIENT_ID:
        await safe_answer(callback, "У вас нет прав!", show_alert=True)
        return

    parts = callback.data.split(":")
    plan = parts[1]
    target_user_id = int(parts[2])

    try:
        await callback.message.edit_text(
            f"❌ <b>Оплата подарком отклонена.</b>\nПользователь ID: <code>{target_user_id}</code>",
            reply_markup=None,
            parse_mode="HTML"
        )
    except Exception:
        pass

    try:
        await bot.send_message(
            chat_id=target_user_id,
            text="❌ <b>Оплата подарком не была подтверждена.</b>\nЕсли произошла ошибка или вы отправили подарок, свяжитесь с поддержкой.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await safe_answer(callback, "Заявка отклонена.")

@router.pre_checkout_query()
async def handle_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    if pre_checkout_query.currency != "XTR":
        await pre_checkout_query.answer(ok=False, error_message="Ошибка оплаты.")
        return
    payload = pre_checkout_query.invoice_payload or ""
    if payload.startswith("transfer_"):
        if pre_checkout_query.total_amount != 25:
            await pre_checkout_query.answer(ok=False, error_message="Неверная сумма комиссии.")
            return
        await pre_checkout_query.answer(ok=True)
        return
    if pre_checkout_query.total_amount not in (SUB_STANDARD_PRICE, SUB_PRO_PRICE, SUB_PREMIUM_PRICE):
        await pre_checkout_query.answer(ok=False, error_message="Неверная сумма.")
        return
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def handle_successful_payment(message: Message, bot: Bot):
    sp = message.successful_payment
    user = message.from_user
    payload = sp.invoice_payload or ""

    if payload.startswith("transfer_"):
        try:
            deal_id = int(payload.split("_")[1])
            deal = await db.get_deal(deal_id)
            if deal:
                await db.accept_deal(deal_id, seller_id=user.id, seller_username=user.username)
                await db.set_deal_status(deal_id, "COMPLETED")
                buyer_display, _, _ = await get_deal_buyer_info(deal)
                formatted_number = format_number(deal["nft_number"])
                currency_name = "GRAM" if deal.get("currency") == "GRAM" else "Stars"

                screen2_text = (
                    f"<b>ОФФЕР ПОДТВЕРЖДЁН</b>\n\n"
                    f"<b>Подарок:</b> <b>{deal['nft_name']} #{formatted_number}</b>\n"
                    f"<b>Сумма сделки:</b> <b>{deal['stars_amount']} {currency_name}</b>\n"
                    f"<b>Покупатель:</b> <b>{buyer_display}</b>\n"
                    f"<b>Статус:</b> ✅ <b>Подарок передан. Сделка успешно завершена!</b>\n\n"
                    f"<b>{currency_name} зачислены на баланс.</b>"
                )

                link_opts = LinkPreviewOptions(
                    url=deal["nft_url"],
                    prefer_large_media=True,
                    show_above_text=True
                )

                await safe_edit_deal_message(
                    bot=bot,
                    deal=deal,
                    text=screen2_text,
                    reply_markup=None,
                    link_opts=link_opts
                )

                try:
                    await bot.send_message(
                        chat_id=deal["buyer_id"],
                        text=(
                            f"🎉 <b>Продавец подтвердил передачу подарка!</b>\n\n"
                            f"• Подарок: <b>{deal['nft_name']} #{formatted_number}</b>\n"
                            f"• Сумма: <b>{deal['stars_amount']} {currency_name}</b>\n"
                            f"• Продавец: @{user.username or user.id}\n"
                            f"• Статус: ✅ <b>Сделка успешно завершена!</b>"
                        ),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

                await message.answer(
                    f"✅ <b>Подарок успешно передан!</b>\n\n"
                    f"Подарок <b>{deal['nft_name']} #{formatted_number}</b> передан покупателю {buyer_display}.\n"
                    f"Средства <b>{deal['stars_amount']} {currency_name}</b> зачислены на ваш баланс.",
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.error(f"Error handling transfer payment: {e}")
        return

    if "premium" in payload:
        plan = "premium"
        plan_name = "👑 Premium (100% профита)"
    elif "pro" in payload:
        plan = "pro"
        plan_name = "💎 PRO / Инлайн"
    else:
        plan = "standard"
        plan_name = "⭐️ Стандарт"

    await db.record_payment(
        user_id=user.id,
        amount=sp.total_amount,
        currency=sp.currency,
        charge_id=sp.telegram_payment_charge_id,
        payload=sp.invoice_payload
    )

    new_expires_at = await db.add_or_extend_subscription(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        days=SUB_DURATION_DAYS,
        plan=plan,
        charge_id=sp.telegram_payment_charge_id
    )

    date_str = format_date_display(new_expires_at)
    success_text = (
        "🎉 <b>Оплата прошла успешно!</b>\n\n"
        f"Тариф: <b>{plan_name}</b>\n"
        f"Срок действия: до <b>{date_str}</b>\n\n"
        "Доступ активирован!"
    )
    await message.answer(success_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")

# --- TON INSTANT PAYMENTS HANDLERS ---

@router.callback_query(F.data.startswith("pay_ton:"))
async def handle_pay_ton(callback: CallbackQuery):
    user_id = callback.from_user.id
    target_plan = callback.data.split(":")[1] if ":" in callback.data else "standard"
    inv = get_ton_invoice_data(user_id, target_plan)
    if target_plan == "premium":
        plan_name = "👑 Premium (100% профита)"
    elif target_plan == "pro":
        plan_name = "💎 PRO Инлайн"
    else:
        plan_name = "⭐️ Стандарт"

    text = (
        f"💎 <b>Оплата тарифа «{plan_name}» через TON (GRAM)</b>\n\n"
        f"Для моментальной активации переведите <b>{inv['amount_ton']} TON</b>:\n\n"
        f"📍 <b>Адрес кошелька TON (GRAM):</b>\n"
        f"<code>{inv['address']}</code> <i>(нажмите для копирования)</i>\n\n"
        f"💬 <b>Комментарий к переводу (ОБЯЗАТЕЛЬНО):</b>\n"
        f"<code>{inv['comment']}</code> <i>(нажмите для копирования)</i>\n\n"
        f"⚠️ <b>ВНИМАНИЕ:</b> Обязательно укажите комментарий <code>{inv['comment']}</code> в назначении перевода, чтобы блокчейн-сканер мгновенно зачислил платёж и активировал доступ автоматически!\n\n"
        f"<i>Средства поступают напрямую на личный кошелёк (0 дней холда). После отправки нажмите «Проверить оплату в блокчейне».</i>"
    )

    kb = get_ton_payment_keyboard(tonkeeper_url=inv["tonkeeper_url"], plan=target_plan, user_id=user_id)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await safe_answer(callback)

@router.callback_query(F.data.startswith("check_ton:"))
async def handle_check_ton(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    plan = parts[1]
    user_id = int(parts[2])

    if callback.from_user.id != user_id:
        await safe_answer(callback, "Это не ваш счёт!", show_alert=True)
        return

    await safe_answer(callback, "🔍 Проверяем блокчейн TON...")

    success, tx_hash, amount_ton = await verify_ton_transaction(user_id=user_id, plan=plan)

    if success:
        if plan == "premium":
            plan_name = "👑 Premium (100% профита)"
        elif plan == "pro":
            plan_name = "💎 PRO / Инлайн"
        else:
            plan_name = "⭐️ Стандарт"
        user = callback.from_user

        await db.record_payment(
            user_id=user.id,
            amount=amount_ton,
            currency="TON",
            charge_id=tx_hash,
            payload=f"ton_{plan}_{user_id}"
        )

        new_expires_at = await db.add_or_extend_subscription(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            days=SUB_DURATION_DAYS,
            plan=plan,
            charge_id=tx_hash
        )

        date_str = format_date_display(new_expires_at)
        success_text = (
            "🎉 <b>Оплата в TON успешно подтверждена!</b>\n\n"
            f"Тариф: <b>{plan_name}</b>\n"
            f"Сумма: <b>{amount_ton} TON</b>\n"
            f"Хеш транзакции: <code>{tx_hash[:16]}...</code>\n"
            f"Срок действия: до <b>{date_str}</b>\n\n"
            "Доступ успешно активирован!"
        )
        try:
            await callback.message.edit_text(success_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
        except Exception:
            await callback.message.answer(success_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
    else:
        await safe_answer(
            callback,
            "❌ Транзакция пока не найдена в блокчейне TON.\nЕсли вы только что перевели, подождите 10-15 секунд и нажмите снова.",
            show_alert=True
        )


# --- HELPER FUNCTIONS FOR BACKGROUND WORKERS ---



async def get_deal_buyer_info(deal: dict) -> tuple[str, str, bool]:
    recip = deal.get("recipient") or config.GIFT_RECIPIENT or "@DealNftOffer"
    recip_str = str(recip).strip()
    if recip_str.startswith("https://t.me/"):
        clean_recip = recip_str.replace("https://t.me/", "").lstrip("@").strip("/")
    elif recip_str.startswith("t.me/"):
        clean_recip = recip_str.replace("t.me/", "").lstrip("@").strip("/")
    else:
        clean_recip = recip_str.lstrip("@").strip()

    if not clean_recip:
        clean_recip = "DealNftOffer"

    if clean_recip.isdigit():
        target_url = f"tg://user?id={clean_recip}"
        buyer_display = f"ID:{clean_recip}"
    else:
        target_url = f"https://t.me/{clean_recip}"
        buyer_display = f"@{clean_recip}"

    return buyer_display, target_url, True

async def safe_edit_deal_message(
    bot: Bot,
    deal: dict,
    text: str,
    reply_markup=None,
    link_opts=None,
    inline_message_id: str | None = None,
    callback_message=None,
    callback_from_user_id: int | None = None
):
    """
    Безопасно обновляет сообщение оффера в любом типе доставки:
    - Инлайн-сообщение (edit_message_text)
    - Текстовое сообщение в бизнес-чате (edit_message_text)
    - Фото-сообщение в бизнес-чате (edit_message_caption)
    - Обычное личное сообщение бота (edit_message_text / edit_message_caption)
    """
    edited = False

    # 1. Если клик был по инлайн-сообщению, обязательно редактируем его
    if inline_message_id:
        try:
            await bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=text,
                reply_markup=reply_markup,
                link_preview_options=link_opts,
                parse_mode="HTML"
            )
            edited = True
        except Exception as e_in:
            logger.debug(f"Direct inline edit failed: {e_in}")

    # 2. Если сделка отправлена через Telegram Business
    biz_id = deal.get("business_connection_id") or (getattr(callback_message, "business_connection_id", None) if callback_message else None)
    target_cid = deal.get("chat_id")
    target_mid = deal.get("message_id")
    buyer_id = deal.get("buyer_id")

    if biz_id:
        # Для Telegram Business chat_id ВСЕГДА должен быть ID собеседника (клиента), а не бизнес-аккаунта!
        biz_chat_id = None
        if target_cid and target_cid != buyer_id:
            biz_chat_id = target_cid
        elif callback_from_user_id and callback_from_user_id != buyer_id:
            biz_chat_id = callback_from_user_id
        elif deal.get("seller_id") and deal.get("seller_id") != buyer_id:
            biz_chat_id = deal.get("seller_id")
        elif callback_message and callback_message.chat and callback_message.chat.id != buyer_id:
            biz_chat_id = callback_message.chat.id

        biz_msg_id = (callback_message.message_id if callback_message else None) or target_mid

        if biz_chat_id and biz_msg_id:
            try:
                await bot.edit_message_text(
                    business_connection_id=biz_id,
                    chat_id=biz_chat_id,
                    message_id=biz_msg_id,
                    text=text,
                    reply_markup=reply_markup,
                    link_preview_options=link_opts,
                    parse_mode="HTML"
                )
                edited = True
            except TelegramBadRequest as e_biz:
                if "not modified" in str(e_biz).lower():
                    edited = True
                else:
                    logger.warning(f"Business edit failed: {e_biz}")
            except Exception as e_biz:
                logger.warning(f"Business edit failed: {e_biz}")
    else:
        # Обычное личное сообщение бота
        if callback_message:
            try:
                await callback_message.edit_text(
                    text=text,
                    reply_markup=reply_markup,
                    link_preview_options=link_opts,
                    parse_mode="HTML"
                )
                edited = True
            except TelegramBadRequest as e_cb:
                if "not modified" in str(e_cb).lower():
                    edited = True
                else:
                    logger.debug(f"Callback message edit failed: {e_cb}")
            except Exception as e_cb:
                logger.debug(f"Callback message edit failed: {e_cb}")
        elif target_cid and target_mid:
            try:
                await bot.edit_message_text(
                    chat_id=target_cid,
                    message_id=target_mid,
                    text=text,
                    reply_markup=reply_markup,
                    link_preview_options=link_opts,
                    parse_mode="HTML"
                )
                edited = True
            except TelegramBadRequest as e_pm:
                if "not modified" in str(e_pm).lower():
                    edited = True
                else:
                    logger.debug(f"Direct PM edit failed: {e_pm}")
            except Exception as e_pm:
                logger.debug(f"Direct PM edit failed: {e_pm}")

    # 3. Синхронизируем инлайн-сообщение сделки (если клик был не из него)
    stored_inline_id = deal.get("inline_message_id")
    if stored_inline_id and stored_inline_id != inline_message_id:
        try:
            await bot.edit_message_text(
                inline_message_id=stored_inline_id,
                text=text,
                reply_markup=reply_markup,
                link_preview_options=link_opts,
                parse_mode="HTML"
            )
        except Exception as e_sin:
            logger.debug(f"Stored inline edit failed: {e_sin}")

# --- DEAL CALLBACK HANDLERS (SUPPORTS INLINE MESSAGES TOO) ---

@router.callback_query(F.data.startswith("accept:"))
async def handle_accept_callback(callback: CallbackQuery, bot: Bot):
    deal_id = int(callback.data.split(":")[1])
    deal = await db.get_deal(deal_id)

    if not deal:
        await safe_answer(callback, "Оффер не найден!", show_alert=True)
        return

    # Мгновенно подтверждаем получение callback, чтобы у пользователя не зависала кнопка
    await safe_answer(callback)

    if deal["status"] not in ("PENDING", "CONFIRMING"):
        if deal["status"] != "ACCEPTED":
            await safe_answer(callback, "Этот оффер уже был отклонён или истёк!", show_alert=True)
            return

    # Принимаем оффер и переводим в статус ACCEPTED (если еще не был принят)
    user = callback.from_user
    if deal["status"] in ("PENDING", "CONFIRMING"):
        await db.accept_deal(deal_id, seller_id=user.id, seller_username=user.username)
        await db.set_deal_status(deal_id, "ACCEPTED")
        config.DEAL_LAST_TIMERS.pop(deal_id, None)
        deal = await db.get_deal(deal_id)

    buyer_display, target_url, is_premium = await get_deal_buyer_info(deal)
    formatted_number = format_number(deal["nft_number"])
    currency_name = "GRAM" if deal.get("currency") == "GRAM" else "Stars"
    deal_lang = deal.get("lang", "RU")

    # Экран 2 (Ожидание передачи подарка)
    if deal_lang == "ENG":
        screen2_text = (
            f"<b>Gift:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>\n"
            f"<b>Deal amount:</b> <b>{deal['stars_amount']} {currency_name}</b>\n"
            f"<b>Recipient:</b> {buyer_display}\n"
            f"<b>Status:</b> <b>Awaiting gift transfer</b>\n\n"
            f"<blockquote><b>Please transfer the gift to recipient ({buyer_display}) to complete the deal.</b></blockquote>\n\n"
            f"<b>Instructions:</b>\n"
            f"1. Tap <b>«Send gift... ↗»</b> to open chat with {buyer_display}.\n"
            f"2. In profile, select gift <b>{deal['nft_name']} #{formatted_number}</b> and confirm transfer.\n"
            f"3. Return to this chat and tap <b>«Gift sent»</b>.\n\n"
            f"<i>Funds will be credited once the transfer is confirmed.</i>"
        )
    else:
        screen2_text = (
            f"<b>Подарок:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>\n"
            f"<b>Сумма сделки:</b> <b>{deal['stars_amount']} {currency_name}</b>\n"
            f"<b>Получатель:</b> {buyer_display}\n"
            f"<b>Статус:</b> <b>Ожидание передачи подарка</b>\n\n"
            f"<blockquote><b>Для завершения сделки передайте подарок получателю ({buyer_display}).</b></blockquote>\n\n"
            f"<b>Порядок передачи:</b>\n"
            f"1. Нажмите <b>«Отправить подарок... ↗»</b>, чтобы открыть диалог с {buyer_display}.\n"
            f"2. В профиле выберите подарок <b>{deal['nft_name']} #{formatted_number}</b> и подтвердите передачу.\n"
            f"3. Вернитесь в этот диалог и нажмите <b>«Подарок отправлен»</b>.\n\n"
            f"<i>После подтверждения передачи подарка баланс будет пополнен.</i>"
        )

    screen2_kb = get_screen2_keyboard(target_url=target_url, deal_id=deal_id, lang=deal_lang)
    link_opts = LinkPreviewOptions(
        url=deal["nft_url"],
        prefer_large_media=True,
        show_above_text=True
    )

    # Редактируем сообщение оффера прямо в диалоге на Экран 2
    await safe_edit_deal_message(
        bot=bot,
        deal=deal,
        text=screen2_text,
        reply_markup=screen2_kb,
        link_opts=link_opts,
        inline_message_id=callback.inline_message_id,
        callback_message=callback.message,
        callback_from_user_id=callback.from_user.id
    )

    # Уведомление покупателю в личные сообщения бота
    try:
        seller_name = f"@{user.username}" if user.username else f"ID {user.id}"
        await bot.send_message(
            chat_id=deal["buyer_id"],
            text=(
                f"⚡️ <b>Продавец принял ваш оффер!</b>\n\n"
                f"🎁 <b>Подарок:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>\n"
                f"⭐ <b>Сумма сделки:</b> <b>{deal['stars_amount']} {currency_name}</b>\n"
                f"👤 <b>Продавец:</b> {seller_name}\n"
                f"📍 <b>Статус:</b> Ожидается передача подарка получателю ({buyer_display})...\n\n"
                f"<i>Как только подарок поступит, сделка завершится автоматически!</i>"
            ),
            parse_mode="HTML"
        )
    except Exception as e_notify:
        logger.debug(f"Could not notify buyer about accept: {e_notify}")


@router.callback_query(F.data.startswith("cancel_accept:"))
async def handle_cancel_accept_callback(callback: CallbackQuery, bot: Bot):
    deal_id = int(callback.data.split(":")[1])
    deal = await db.get_deal(deal_id)

    if not deal:
        await safe_answer(callback, "Оффер не найден!", show_alert=True)
        return

    if deal["status"] not in ("PENDING", "CONFIRMING"):
        await safe_answer(callback, "Оффер уже неактивен!", show_alert=True)
        return

    # Возвращаем статус в PENDING
    await db.set_deal_status(deal_id, "PENDING")

    deal_lang = deal.get("lang", "RU")
    formatted_number = format_number(deal["nft_number"])
    currency_symbol = "GRAM" if deal.get("currency") == "GRAM" else "⭐️"
    stars_txt = f"{deal['stars_amount']} {currency_symbol}"
    timer_str = format_offer_timer(deal.get("expires_at"), lang=deal_lang)
    config.DEAL_LAST_TIMERS[deal_id] = timer_str

    if deal_lang == "ENG":
        revert_text = (
            f"A user offers you <b>{stars_txt}</b> for gift <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>.\n\n"
            f"Expires in {timer_str}."
        )
    else:
        revert_text = (
            f"Пользователь предлагает Вам <b>{stars_txt}</b> за подарок <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>.\n\n"
            f"Истекает через {timer_str}."
        )

    revert_kb = get_screen1_keyboard(deal_id, lang=deal_lang)
    link_opts = LinkPreviewOptions(
        url=deal["nft_url"],
        prefer_large_media=True,
        show_above_text=True
    )

    await safe_edit_deal_message(
        bot=bot,
        deal=deal,
        text=revert_text,
        reply_markup=revert_kb,
        link_opts=link_opts,
        inline_message_id=callback.inline_message_id,
        callback_message=callback.message,
        callback_from_user_id=callback.from_user.id
    )
    await safe_answer(callback, "Передача подарка отменена.")


@router.callback_query(F.data.startswith("confirm_accept:"))
async def handle_confirm_accept_callback(callback: CallbackQuery, bot: Bot):
    await handle_accept_callback(callback, bot)


@router.callback_query(F.data.startswith("decline:"))
async def handle_decline_callback(callback: CallbackQuery, bot: Bot):
    deal_id = int(callback.data.split(":")[1])
    deal = await db.get_deal(deal_id)

    if not deal:
        await safe_answer(callback, "Оффер не найден!", show_alert=True)
        return

    if deal["status"] not in ("PENDING", "CONFIRMING"):
        await safe_answer(callback, "Этот оффер уже неактивен!", show_alert=True)
        return

    user = callback.from_user
    if deal["seller_id"] and user.id not in (deal["buyer_id"], deal["seller_id"]):
        await safe_answer(callback, "Вы не являетесь участником этой сделки!", show_alert=True)
        return

    await db.set_deal_status(deal_id, "DECLINED")
    config.DEAL_LAST_TIMERS.pop(deal_id, None)

    deal_lang = deal.get("lang", "RU")
    curr_symbol = "GRAM" if deal.get("currency") == "GRAM" else "⭐️"
    stars_txt = f"{deal['stars_amount']} {curr_symbol}"

    if deal_lang == "ENG":
        declined_text = (
            f"<b>OFFER DECLINED</b>\n\n"
            f"<b>Gift:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{format_number(deal['nft_number'])}</b></a>\n"
            f"<b>Amount:</b> <b>{stars_txt}</b>"
        )
    else:
        declined_text = (
            f"<b>ОФФЕР ОТКЛОНЁН</b>\n\n"
            f"<b>Подарок:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{format_number(deal['nft_number'])}</b></a>\n"
            f"<b>Сумма:</b> <b>{stars_txt}</b>"
        )

    link_opts = LinkPreviewOptions(
        url=deal["nft_url"],
        prefer_large_media=True,
        show_above_text=True
    )

    await safe_edit_deal_message(
        bot=bot,
        deal=deal,
        text=declined_text,
        reply_markup=None,
        link_opts=link_opts,
        inline_message_id=callback.inline_message_id,
        callback_message=callback.message,
        callback_from_user_id=callback.from_user.id
    )
    await safe_answer(callback, "Оффер отклонён.")

    # Уведомление покупателю
    try:
        await bot.send_message(
            chat_id=deal["buyer_id"],
            text=(
                f"❌ <b>Оффер отклонён продавцом</b>\n\n"
                f"🎁 <b>Подарок:</b> <b>{deal['nft_name']} #{format_number(deal['nft_number'])}</b>\n"
                f"⭐ <b>Сумма:</b> <b>{stars_txt}</b>"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass


async def verify_deal_gift_received(deal: dict, bot: Bot) -> tuple[bool, Optional[str]]:
    """
    Проверяет в Telegram API, действительно ли NFT-подарок поступил получателю (гаранту или покупателю).
    Возвращает: (успех, название_подарка_или_ошибка)
    """
    buyer_display, target_url, is_premium = await get_deal_buyer_info(deal)
    target_recipients = [config.GIFT_RECIPIENT_ID]
    if is_premium and deal.get("buyer_id") and deal["buyer_id"] not in target_recipients:
        target_recipients.insert(0, deal["buyer_id"])

    expected_number = re.sub(r'\D', '', str(deal.get("nft_number", "")))
    expected_name_clean = re.sub(r'[\s\-_]', '', str(deal.get("nft_name", "")).lower())

    deal_created_ts = 0
    try:
        deal_created_dt = datetime.strptime(deal["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        deal_created_ts = int(deal_created_dt.timestamp()) - 900
    except Exception:
        pass

    for r_id in target_recipients:
        gifts_list = []
        try:
            ugifts = await bot.get_user_gifts(user_id=r_id)
            if ugifts and ugifts.gifts:
                gifts_list.extend(ugifts.gifts)
        except Exception as e:
            logger.debug(f"get_user_gifts({r_id}) error: {e}")

        try:
            conn = await db.get_business_connection_by_user(r_id)
            if conn and conn.get("connection_id"):
                bgifts = await bot.get_business_account_gifts(business_connection_id=conn["connection_id"])
                if bgifts and bgifts.gifts:
                    gifts_list.extend(bgifts.gifts)
        except Exception as e:
            logger.debug(f"get_business_account_gifts({r_id}) error: {e}")

        for g in gifts_list:
            if getattr(g, "type", None) != "unique":
                continue

            inner = getattr(g, "gift", None)
            if not inner:
                continue

            gift_number = re.sub(r'\D', '', str(getattr(inner, "number", "")))
            gift_name = str(getattr(inner, "name", ""))
            gift_base = str(getattr(inner, "base_name", ""))

            gift_name_clean = re.sub(r'[\s\-_]', '', gift_name.lower())
            gift_base_clean = re.sub(r'[\s\-_]', '', gift_base.lower())

            if expected_number and gift_number != expected_number:
                continue

            if expected_name_clean:
                name_match = (
                    expected_name_clean in gift_name_clean
                    or expected_name_clean in gift_base_clean
                    or gift_base_clean in expected_name_clean
                )
                if not name_match:
                    continue

            send_date = getattr(g, "send_date", 0)
            if send_date and deal_created_ts and send_date < deal_created_ts:
                continue

            return True, f"{gift_name} #{gift_number}"

    return False, None


_SENT_DEBOUNCE: dict[int, float] = {}

@router.callback_query(F.data.startswith("sent:"))
async def handle_sent_callback(callback: CallbackQuery, bot: Bot):
    await safe_answer(callback, "Вы ещё не передали подарок!", show_alert=True)


async def complete_deal_with_guarantor(
    bot: Bot,
    deal: dict,
    callback_message=None,
    inline_message_id=None
):
    deal_id = deal["deal_id"]
    await db.set_deal_status(deal_id, "COMPLETED")

    buyer_display, _, is_premium = await get_deal_buyer_info(deal)
    formatted_number = format_number(deal["nft_number"])
    currency_name = "GRAM" if deal.get("currency") == "GRAM" else "Stars"
    deal_lang = deal.get("lang", "RU")

    # Экран успешно завершенной сделки
    if deal_lang == "ENG":
        screen_done_text = (
            f"✅ <b>DEAL COMPLETED SUCCESSFULLY</b>\n\n"
            f"<b>Gift:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>\n"
            f"<b>Deal amount:</b> <b>{deal['stars_amount']} {currency_name}</b>\n"
            f"<b>Guarantor:</b> {buyer_display}\n"
            f"<b>Status:</b> ✅ <b>Gift received by guarantor.</b>\n\n"
            f"<b>{deal['stars_amount']} {currency_name} credited to your balance.</b>"
        )
    else:
        screen_done_text = (
            f"✅ <b>СДЕЛКА УСПЕШНО ЗАВЕРШЕНА</b>\n\n"
            f"<b>Подарок:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>\n"
            f"<b>Сумма сделки:</b> <b>{deal['stars_amount']} {currency_name}</b>\n"
            f"<b>Гарант:</b> {buyer_display}\n"
            f"<b>Статус:</b> ✅ <b>Подарок успешно получен гарантом.</b>\n\n"
            f"<b>{deal['stars_amount']} {currency_name} зачислены на ваш баланс.</b>"
        )

    link_opts = LinkPreviewOptions(
        url=deal["nft_url"],
        prefer_large_media=True,
        show_above_text=True
    )

    await safe_edit_deal_message(
        bot=bot,
        deal=deal,
        text=screen_done_text,
        reply_markup=None,
        link_opts=link_opts,
        inline_message_id=inline_message_id or deal.get("inline_message_id"),
        callback_message=callback_message
    )

    # Уведомление покупателю
    try:
        await bot.send_message(
            chat_id=deal["buyer_id"],
            text=(
                f"🎉 <b>NFT-подарок успешно получен гарантом!</b>\n\n"
                f"• Подарок: <b>{deal['nft_name']} #{formatted_number}</b>\n"
                f"• Сумма: <b>{deal['stars_amount']} {currency_name}</b>\n"
                f"• Продавец: @{deal.get('seller_username') or deal.get('seller_id')}\n"
                f"• Статус: ✅ <b>Подарок в безопасности у гаранта {buyer_display}</b>"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.debug(f"Could not notify buyer about completed deal: {e}")


@router.callback_query(F.data.startswith("confirm:"))
async def handle_confirm_callback(callback: CallbackQuery, bot: Bot):
    deal_id = int(callback.data.split(":")[1])
    deal = await db.get_deal(deal_id)

    if not deal:
        await safe_answer(callback, "Оффер не найден!", show_alert=True)
        return

    if deal["status"] != "SENT":
        await safe_answer(callback, "Сделка уже завершена или ещё не отправлена!", show_alert=True)
        return

    user = callback.from_user
    if user.id != deal["buyer_id"] and user.id not in config.ADMIN_IDS:
        await safe_answer(callback, "Только покупатель или администратор может подтвердить получение!", show_alert=True)
        return

    # Проверяем, действительно ли NFT-подарок поступил получателю
    is_received, gift_title = await verify_deal_gift_received(deal, bot)
    if not is_received and user.id not in config.ADMIN_IDS:
        formatted_num = format_number(deal["nft_number"])
        await safe_answer(
            callback,
            f"❌ Невозможно завершить сделку!\n\n"
            f"NFT-подарок «{deal['nft_name']} #{formatted_num}» не обнаружен в профиле получателя.",
            show_alert=True
        )
        return

    # Mark as COMPLETED! Now this deal will strictly appear in the successful deals list
    await db.set_deal_status(deal_id, "COMPLETED")

    buyer_display = "Гарант-сервис"
    formatted_number = format_number(deal["nft_number"])

    currency_name = "GRAM" if deal.get("currency") == "GRAM" else "Stars"
    curr_symbol = "💎" if deal.get("currency") == "GRAM" else "⭐️"
    deal_lang = deal.get("lang", "RU")

    if deal_lang == "ENG":
        completed_text = (
            f"<b>DEAL COMPLETED SUCCESSFULLY</b>\n\n"
            f"<b>Gift {deal['nft_name']} #{formatted_number} successfully received and verified.</b>\n"
            f"<b>Payout amount:</b> <b>{deal['stars_amount']} {currency_name}</b>.\n\n"
            f"<b>{currency_name} will be credited to balance within 24 hours.</b>"
        )
        payout_note = f"{curr_symbol} <b>Expect {currency_name} within 24 hours.</b>"
    else:
        completed_text = (
            f"<b>СДЕЛКА УСПЕШНО ЗАВЕРШЕНА</b>\n\n"
            f"<b>Подарок {deal['nft_name']} #{formatted_number} успешно получен и подтверждён.</b>\n"
            f"<b>Сумма к выплате:</b> <b>{deal['stars_amount']} {currency_name}</b>.\n\n"
            f"<b>{currency_name} зачисляются на баланс в течение 24 часов.</b>"
        )
        payout_note = f"{curr_symbol} <b>Ожидайте {currency_name} в течение 24 часов.</b>"

    try:
        if callback.inline_message_id:
            try:
                await bot.edit_message_text(inline_message_id=callback.inline_message_id, text=completed_text, reply_markup=None, parse_mode="HTML")
            except Exception:
                await bot.edit_message_caption(inline_message_id=callback.inline_message_id, caption=completed_text, reply_markup=None, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=completed_text, reply_markup=None, parse_mode="HTML")
        await safe_answer(callback, "Получение подтверждено! Сделка завершена.")
    except Exception as e:
        logger.error(f"Error in confirm handler: {e}")
        await safe_answer(callback)

    # Message in Business chat
    if deal.get("business_connection_id"):
        try:
            await bot.send_message(
                business_connection_id=deal["business_connection_id"],
                chat_id=deal["chat_id"],
                text=payout_note,
                parse_mode="HTML"
            )
        except Exception:
            pass

    # Direct notification to seller
    if deal.get("seller_id"):
        try:
            seller_notify_text = (
                f"🎉 <b>Сделка завершена!</b>\n\n"
                f"Подарок <b>{deal['nft_name']} #{formatted_number}</b> подтверждён.\n"
                f"Сумма к выплате: <b>{deal['stars_amount']} {currency_name}</b>.\n\n"
                f"{payout_note}"
            )
            await bot.send_message(
                chat_id=deal["seller_id"],
                text=seller_notify_text,
                parse_mode="HTML"
            )
        except Exception:
            pass

async def verify_deal_gift_received(deal: dict, bot: Bot) -> tuple[bool, Optional[str]]:
    """
    Проверяет в Telegram API, действительно ли NFT-подарок поступил получателю (гаранту или покупателю).
    Возвращает: (успех, название_подарка_или_ошибка)
    """
    buyer_display, target_url, is_premium = await get_deal_buyer_info(deal)
    target_recipients = [config.GIFT_RECIPIENT_ID]
    if is_premium and deal.get("buyer_id") and deal["buyer_id"] not in target_recipients:
        target_recipients.insert(0, deal["buyer_id"])

    expected_number = re.sub(r'\D', '', str(deal.get("nft_number", "")))
    expected_name_clean = re.sub(r'[\s\-_]', '', str(deal.get("nft_name", "")).lower())

    deal_created_ts = 0
    try:
        deal_created_dt = datetime.strptime(deal["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        deal_created_ts = int(deal_created_dt.timestamp()) - 900
    except Exception:
        pass

    for r_id in target_recipients:
        gifts_list = []
        try:
            ugifts = await bot.get_user_gifts(user_id=r_id)
            if ugifts and ugifts.gifts:
                gifts_list.extend(ugifts.gifts)
        except Exception as e:
            logger.debug(f"get_user_gifts({r_id}) error: {e}")

        try:
            conn = await db.get_business_connection_by_user(r_id)
            if conn and conn.get("connection_id"):
                bgifts = await bot.get_business_account_gifts(business_connection_id=conn["connection_id"])
                if bgifts and bgifts.gifts:
                    gifts_list.extend(bgifts.gifts)
        except Exception as e:
            logger.debug(f"get_business_account_gifts({r_id}) error: {e}")

        for g in gifts_list:
            if getattr(g, "type", None) != "unique":
                continue

            inner = getattr(g, "gift", None)
            if not inner:
                continue

            gift_number = re.sub(r'\D', '', str(getattr(inner, "number", "")))
            gift_name = str(getattr(inner, "name", ""))
            gift_base = str(getattr(inner, "base_name", ""))

            gift_name_clean = re.sub(r'[\s\-_]', '', gift_name.lower())
            gift_base_clean = re.sub(r'[\s\-_]', '', gift_base.lower())

            if expected_number and gift_number != expected_number:
                continue

            if expected_name_clean:
                name_match = (
                    expected_name_clean in gift_name_clean
                    or expected_name_clean in gift_base_clean
                    or gift_base_clean in expected_name_clean
                )
                if not name_match:
                    continue

            send_date = getattr(g, "send_date", 0)
            if send_date and deal_created_ts and send_date < deal_created_ts:
                continue

            return True, f"{gift_name} #{gift_number}"

    return False, None


_SENT_DEBOUNCE: dict[int, float] = {}

async def complete_deal_with_guarantor(
    bot: Bot,
    deal: dict,
    callback_message=None,
    inline_message_id=None
):
    deal_id = deal["deal_id"]
    await db.set_deal_status(deal_id, "COMPLETED")

    buyer_display, _, is_premium = await get_deal_buyer_info(deal)
    formatted_number = format_number(deal["nft_number"])
    currency_name = "GRAM" if deal.get("currency") == "GRAM" else "Stars"
    deal_lang = deal.get("lang", "RU")

    # Экран успешно завершенной сделки
    if deal_lang == "ENG":
        screen_done_text = (
            f"✅ <b>DEAL COMPLETED SUCCESSFULLY</b>\n\n"
            f"<b>Gift:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>\n"
            f"<b>Deal amount:</b> <b>{deal['stars_amount']} {currency_name}</b>\n"
            f"<b>Guarantor:</b> {buyer_display}\n"
            f"<b>Status:</b> ✅ <b>Gift received by guarantor.</b>\n\n"
            f"<b>{deal['stars_amount']} {currency_name} credited to your balance.</b>"
        )
    else:
        screen_done_text = (
            f"✅ <b>СДЕЛКА УСПЕШНО ЗАВЕРШЕНА</b>\n\n"
            f"<b>Подарок:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>\n"
            f"<b>Сумма сделки:</b> <b>{deal['stars_amount']} {currency_name}</b>\n"
            f"<b>Гарант:</b> {buyer_display}\n"
            f"<b>Статус:</b> ✅ <b>Подарок успешно получен гарантом.</b>\n\n"
            f"<b>{deal['stars_amount']} {currency_name} зачислены на ваш баланс.</b>"
        )

    link_opts = LinkPreviewOptions(
        url=deal["nft_url"],
        prefer_large_media=True,
        show_above_text=True
    )

    await safe_edit_deal_message(
        bot=bot,
        deal=deal,
        text=screen_done_text,
        reply_markup=None,
        link_opts=link_opts,
        inline_message_id=inline_message_id or deal.get("inline_message_id"),
        callback_message=callback_message
    )

    # Уведомление покупателю
    try:
        await bot.send_message(
            chat_id=deal["buyer_id"],
            text=(
                f"🎉 <b>NFT-подарок успешно получен гарантом!</b>\n\n"
                f"• Подарок: <b>{deal['nft_name']} #{formatted_number}</b>\n"
                f"• Сумма: <b>{deal['stars_amount']} {currency_name}</b>\n"
                f"• Продавец: @{deal.get('seller_username') or deal.get('seller_id')}\n"
                f"• Статус: ✅ <b>Подарок в безопасности у гаранта {buyer_display}</b>"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.debug(f"Could not notify buyer about completed deal: {e}")
