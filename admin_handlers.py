import asyncio
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database as db

admin_router = Router()

class AdminStates(StatesGroup):
    waiting_grant_input = State()
    waiting_grant_plan = State()
    waiting_revoke_input = State()
    waiting_check_input = State()
    waiting_broadcast_text = State()

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
            InlineKeyboardButton(text="➕ Выдать подписку", callback_data="admin_grant"),
            InlineKeyboardButton(text="➖ Забрать подписку", callback_data="admin_revoke")
        ],
        [
            InlineKeyboardButton(text="🔍 Проверить юзера", callback_data="admin_check"),
            InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_close")
        ]
    ])

def get_grant_plan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐️ Стандарт (только .buy)", callback_data="admin_grant_plan:standard")
        ],
        [
            InlineKeyboardButton(text="💎 PRO (Инлайн + .buy)", callback_data="admin_grant_plan:pro")
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
        f"• Всего создано офферов: <b>{stats['total_deals']}</b>\n"
        f"• Успешно завершено: <b>{stats['completed_deals']}</b>\n\n"
        "💰 <b>Куда приходят звёзды (Stars):</b>\n"
        "Звёзды зачисляются прямо на баланс этого бота в Telegram.\n"
        "Вывести их в <b>Toncoin (TON)</b> можно в @BotFather: <code>/mybots</code> ➡️ выберите бота ➡️ <b>Bot Settings</b> ➡️ <b>Payments</b> ➡️ <b>Fragment.com</b>."
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

    plan_name = "💎 PRO (Инлайн + .buy)" if plan == "pro" else "⭐️ Стандарт (только .buy)"

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
        except Exception:
            blocked += 1

    await state.clear()
    await status_msg.edit_text(
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"• Успешно доставлено: <b>{sent}</b>\n"
        f"• Не доставлено (заблокировали бота): <b>{blocked}</b>\n"
        f"• Всего получателей: <b>{total}</b>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )
