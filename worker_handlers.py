import logging
import re
import urllib.parse
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    LinkPreviewOptions,
    BusinessConnection,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ChosenInlineResult,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import database as db
import config
from parser import parse_nft_url, format_number, extract_buy_args
from keyboards import (
    get_create_price_keyboard,
    get_create_confirm_keyboard,
    get_screen1_keyboard,
    get_worker_bot_main_keyboard
)
from handlers import (
    build_confirm_card_text,
    build_randomized_offer_text,
    safe_answer
)

logger = logging.getLogger("nft_bot.worker_handlers")
worker_router = Router(name="worker_handlers")

class CreateOfferStates(StatesGroup):
    waiting_gift_url = State()
    waiting_price = State()
    confirm_send = State()
    waiting_recipient = State()

async def check_or_lock_bot_owner(bot: Bot, from_user_id: int) -> bool:
    """
    Проверяет, является ли пользователь единственным владельцем бота.
    Бот жестко блокируется ТОЛЬКО за 1 чатом (первый написавший пользователь).
    Для ВСЕХ остальных пользователей и чатов доступ полностью закрыт.
    Кэшировано в памяти (O(1)) без лишних сетевых вызовов к Telegram API.
    """
    from worker_manager import worker_manager
    bot_id = bot.id

    owner_id = worker_manager.bot_owners.get(bot_id)
    if not owner_id:
        rec = await db.get_worker_bot_by_bot_id(bot_id)
        if rec and rec.get("owner_tg_id"):
            owner_id = rec["owner_tg_id"]
            worker_manager.bot_owners[bot_id] = owner_id
        elif rec and rec.get("user_id") and rec["user_id"] > 100000:
            owner_id = rec["user_id"]
            worker_manager.bot_owners[bot_id] = owner_id

    # Первый вход — навсегда блокируем бота за этим чатом
    if not owner_id:
        owner_id = from_user_id
        worker_manager.bot_owners[bot_id] = owner_id
        await db.set_worker_bot_owner(bot_id, owner_id)
        logger.info(f"🔒 Бот {bot_id} успешно привязан ТОЛЬКО к чату {owner_id}")
        return True

    return from_user_id == owner_id or from_user_id in config.ADMIN_IDS

@worker_router.message.outer_middleware()
async def worker_message_guard(handler, event: Message, data: dict):
    if not event.from_user:
        return await handler(event, data)
    bot: Bot = data["bot"]
    user_id = event.from_user.id
    if not await check_or_lock_bot_owner(bot, user_id):
        await event.answer(
            "⛔ <b>Доступ ограничен.</b>\n\n"
            "Этот бот является персональным рабочим инструментом и привязан только к одному владельцу.",
            parse_mode="HTML"
        )
        return
    return await handler(event, data)

@worker_router.callback_query.outer_middleware()
async def worker_callback_guard(handler, event: CallbackQuery, data: dict):
    if not event.from_user:
        return await handler(event, data)
    bot: Bot = data["bot"]
    user_id = event.from_user.id
    if not await check_or_lock_bot_owner(bot, user_id):
        await safe_answer(event, "⛔ Этот бот является персональным и открыт только для своего владельца.", show_alert=True)
        return
    return await handler(event, data)

@worker_router.message(CommandStart())
async def handle_worker_start(message: Message, bot: Bot):
    user_id = message.from_user.id
    bot_info = await bot.get_me()

    text = (
        f"👋 <b>Добро пожаловать в панель управления ботом @{bot_info.username}!</b>\n\n"
        f"🔑 <b>Статус:</b> <code>Владелец (Эксклюзивный доступ)</code>\n"
        f"🔒 <b>Защита:</b> <i>Привязан только к вашему чату, посторонние не могут пользоваться ботом.</i>\n\n"
        f"Вам сразу доступны все права: создание офферов, статистика и управление сделками."
    )
    await message.answer(text, reply_markup=get_worker_bot_main_keyboard(), parse_mode="HTML")

@worker_router.message(Command("create"))
async def handle_cmd_create(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    if not await check_or_lock_bot_owner(bot, user_id):
        return await message.answer("⛔ Доступ ограничен.", parse_mode="HTML")

    await state.clear()
    await state.set_state(CreateOfferStates.waiting_gift_url)
    await message.answer("🔗 <b>Введите ссылку на подарок (например, https://t.me/nft/BigYear-70698):</b>", parse_mode="HTML")

@worker_router.callback_query(F.data == "menu_create")
async def handle_menu_create(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    if not await check_or_lock_bot_owner(bot, user_id):
        return await safe_answer(callback, "⛔ Доступ ограничен (чужой бот)", show_alert=True)

    await state.clear()
    await state.set_state(CreateOfferStates.waiting_gift_url)
    await callback.message.answer("🔗 <b>Введите ссылку на подарок (например, https://t.me/nft/BigYear-70698):</b>", parse_mode="HTML")
    await safe_answer(callback)

@worker_router.callback_query(F.data == "menu_profile")
async def handle_worker_profile(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if not await check_or_lock_bot_owner(bot, user_id):
        return await safe_answer(callback, "⛔ Доступ ограничен", show_alert=True)

    bot_info = await bot.get_me()
    deals = await db.get_deals_by_buyer(user_id)
    deals_count = len(deals)
    completed_deals = len([d for d in deals if d.get("status") == "COMPLETED"])
    total_stars = sum(d.get("stars_amount", 0) for d in deals if d.get("status") == "COMPLETED")

    text = (
        f"👤 <b>Профиль владельца бота</b>\n\n"
        f"🤖 <b>Бот:</b> @{bot_info.username}\n"
        f"🆔 <b>Ваш Chat ID:</b> <code>{user_id}</code>\n"
        f"💎 <b>Права:</b> <code>Владелец (Полный доступ без лимитов)</code>\n"
        f"🔒 <b>Режим:</b> <code>Приватный (Только этот чат)</code>\n\n"
        f"📊 <b>Статистика офферов:</b>\n"
        f"• Всего создано офферов: <b>{deals_count}</b>\n"
        f"• Успешных сделок: <b>{completed_deals}</b>\n"
        f"• Общий объем: <b>{total_stars} ⭐️</b>\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Создать оффер", callback_data="menu_create")],
        [InlineKeyboardButton(text="📋 Мои сделки", callback_data="menu_my_deals")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu_main")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await safe_answer(callback)

@worker_router.callback_query(F.data.in_(["menu_my_deals", "menu_deals"]))
async def handle_worker_my_deals(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if not await check_or_lock_bot_owner(bot, user_id):
        return await safe_answer(callback, "⛔ Доступ ограничен", show_alert=True)

    deals = await db.get_deals_by_buyer(user_id, limit=10)
    if not deals:
        text = (
            "📋 <b>Ваши сделки</b>\n\n"
            "У вас пока нет созданных офферов.\n"
            "Нажмите «Создать оффер», чтобы отправить первое предложение!"
        )
    else:
        text = "📋 <b>Последние сделки бота:</b>\n\n"
        for d in deals[:8]:
            st = d.get("status", "PENDING")
            st_icon = "⏳" if st in ("PENDING", "CONFIRMING") else ("✅" if st == "COMPLETED" else "❌")
            text += (
                f"{st_icon} <b>#{d['deal_id']}</b>: {d.get('nft_name')} #{d.get('nft_number')} — "
                f"<b>{d.get('stars_amount')} {d.get('currency', '⭐️')}</b> [{st}]\n"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Создать оффер", callback_data="menu_create")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="menu_my_deals")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu_main")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await safe_answer(callback)

@worker_router.callback_query(F.data == "menu_main")
async def handle_worker_main_menu(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if not await check_or_lock_bot_owner(bot, user_id):
        return await safe_answer(callback, "⛔ Доступ ограничен", show_alert=True)

    bot_info = await bot.get_me()
    text = (
        f"👋 <b>Главное меню бота @{bot_info.username}</b>\n\n"
        f"🔑 <b>Статус:</b> <code>Владелец (Эксклюзивный доступ)</code>\n"
        f"🔒 <b>Защита:</b> <i>Бот заблокирован только для этого чата.</i>\n\n"
        f"Выберите нужное действие ниже:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_worker_bot_main_keyboard(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=get_worker_bot_main_keyboard(), parse_mode="HTML")
    await safe_answer(callback)

@worker_router.callback_query(F.data == "menu_business")
async def handle_worker_business(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if not await check_or_lock_bot_owner(bot, user_id):
        return await safe_answer(callback, "⛔ Доступ ограничен", show_alert=True)

    bot_info = await bot.get_me()
    text = (
        f"💼 <b>Подключение Telegram Business</b>\n\n"
        f"Вы можете подключить бота @{bot_info.username} прямо в диалоги вашего Telegram-аккаунта:\n\n"
        f"1. Откройте <i>Настройки Telegram ➔ Telegram Business</i>\n"
        f"2. Выберите раздел <b>«Чат-боты»</b>\n"
        f"3. Введите username: <b>@{bot_info.username}</b>\n"
        f"4. Разрешите боту отвечать на сообщения.\n\n"
        f"После этого офферы смогут отправляться автоматически прямо в диалог с продавцом!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu_main")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
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
        is_premium = True
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

@worker_router.message(CreateOfferStates.waiting_gift_url)
async def handle_create_gift_url(message: Message, state: FSMContext):
    await process_gift_url(message, state, message.text or "")

@worker_router.message(F.text.regexp(r'(https?://)?(t\.me/nft/|fragment\.com/)\S+'))
async def handle_direct_nft_link(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    if not await check_or_lock_bot_owner(bot, user_id):
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

@worker_router.callback_query(F.data == "create_toggle_currency", CreateOfferStates.waiting_price)
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

@worker_router.message(CreateOfferStates.waiting_price)
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
    is_premium = True
    await message.answer(
        card_text,
        reply_markup=get_create_confirm_keyboard(lang, is_premium=is_premium),
        link_preview_options=link_opts,
        parse_mode="HTML"
    )

@worker_router.callback_query(F.data == "create_toggle_lang")
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
    is_premium = True
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

@worker_router.callback_query(F.data == "create_change_recipient")
async def handle_create_change_recipient(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CreateOfferStates.waiting_recipient)
    await callback.message.answer("👤 <b>Введите @username или ID нового получателя:</b>", parse_mode="HTML")
    await safe_answer(callback)

@worker_router.message(CreateOfferStates.waiting_recipient)
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

@worker_router.callback_query(F.data == "create_cancel")
async def handle_create_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Создание оффера отменено.", reply_markup=get_worker_bot_main_keyboard())
    await safe_answer(callback, "Отменено")

@worker_router.callback_query(F.data == "create_send")
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

        business_keyboard = get_screen1_keyboard(deal_id=deal_id, lang=lang, is_business=True)
        pm_keyboard = get_screen1_keyboard(deal_id=deal_id, lang=lang, is_business=False)

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

        if has_own_biz and sent_via_biz:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ <b>Оффер успешно отправлен владельцу подарка ({target_seller})!</b>\n\n"
                    f"🎁 <b>Подарок:</b> <b>{nft_data['name']} #{formatted_number}</b>\n"
                    f"⭐ <b>Сумма:</b> <b>{stars_txt}</b>\n"
                    f"👤 <b>Получатель:</b> <b>{recipient}</b>\n\n"
                    f"<i>Когда {target_seller} примет или отклонит оффер, вы сразу получите уведомление.</i>"
                ),
                parse_mode="HTML"
            )
        else:
            share_kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Отправить оффер",
                        switch_inline_query=f"deal_{deal_id}"
                    )
                ]
            ])

            if sent_to_owner:
                extra_info = (
                    f"⚡ <i>Оффер доставлен ботом в диалог с {target_seller}.</i>\n\n"
                    f"👉 <b>Нажмите кнопку ниже, чтобы переслать оффер:</b>"
                )
            elif has_own_biz:
                extra_info = (
                    f"ℹ️ <i>Бот подключен к вашему Telegram Business, но диалог с {target_seller} ещё не был начат (Telegram требует числовой ID для первой отправки).</i>\n\n"
                    f"👉 <b>Нажмите кнопку ниже, чтобы отправить оффер в чат в 1 клик:</b>"
                )
            else:
                extra_info = (
                    f"💡 <i>На этом аккаунте не подключен Telegram Business к боту (или бот не добавлен в Чат-боты).</i>\n\n"
                    f"👉 <b>Нажмите кнопку ниже, чтобы отправить оффер:</b>"
                )

            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ <b>Оффер сформирован для {target_seller}!</b>\n\n"
                    f"🎁 <b>Подарок:</b> <b>{nft_data['name']} #{formatted_number}</b>\n"
                    f"⭐ <b>Сумма:</b> <b>{stars_txt}</b>\n"
                    f"👤 <b>Получатель:</b> <b>{recipient}</b>\n\n"
                    f"{extra_info}"
                ),
                reply_markup=share_kb,
                parse_mode="HTML"
            )

        await state.clear()
        await safe_answer(callback, "Оффер отправлен!")
    except Exception as e:
        logger.exception(f"Error in handle_create_send: {e}")
        await safe_answer(callback, f"Ошибка при отправке: {e}", show_alert=True)

# --- TELEGRAM BUSINESS & INLINE QUERY HANDLERS ---

@worker_router.business_connection()
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
                text="✅ <b>Telegram Business подключён успешно!</b>\nТеперь рабочий бот может автоматически доставлять офферы в ваши личные диалоги.",
                parse_mode="HTML"
            )
        except Exception:
            pass

@worker_router.business_message()
async def handle_business_message_tracker(message: Message):
    if message.chat and message.chat.type == "private":
        await db.register_user(
            user_id=message.chat.id,
            username=message.chat.username,
            first_name=message.chat.first_name
        )

@worker_router.inline_query()
async def handle_inline_query(inline_query: InlineQuery, bot: Bot):
    user = inline_query.from_user
    if not await check_or_lock_bot_owner(bot, user.id):
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
                    reply_markup=get_screen1_keyboard(deal_id=deal_id, lang=deal_lang)
                )
                await inline_query.answer([article], cache_time=1, is_personal=True)
                return

    # Hint for user on syntax
    hint = InlineQueryResultArticle(
        id="hint",
        title="💡 Формат инлайн-оффера",
        description="Пример: https://t.me/nft/libertyfigure-264534 1200",
        input_message_content=InputTextMessageContent(
            message_text=f"Формат оффера: <code>@{bot_uname} ссылка_на_nft сумма [gram]</code>",
            parse_mode="HTML"
        )
    )
    await inline_query.answer([hint], cache_time=1, is_personal=True)

@worker_router.chosen_inline_result()
async def handle_chosen_inline_result(result: ChosenInlineResult):
    if result.result_id.startswith("deal_"):
        clean_id = result.result_id.replace("deal_", "").strip()
        if clean_id.isdigit():
            deal_id = int(clean_id)
            if result.inline_message_id:
                await db.set_deal_inline_message_id(deal_id, result.inline_message_id)
