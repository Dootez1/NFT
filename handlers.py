import re
from datetime import datetime
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
    InputTextMessageContent,
    ChosenInlineResult
)
from aiogram.filters import CommandStart, Command, CommandObject

import database as db
import config
from config import (
    SUB_STANDARD_PRICE,
    SUB_PRO_PRICE,
    SUB_DURATION_DAYS
)
from parser import parse_nft_url, extract_buy_args, format_number
from keyboards import (
    get_screen1_keyboard,
    get_screen2_keyboard,
    get_screen3_buyer_keyboard,
    get_main_menu_keyboard,
    get_profile_keyboard,
    get_sub_menu_keyboard,
    get_back_to_menu_keyboard,
    get_buy_sub_keyboard,
    get_deals_keyboard,
    get_referral_keyboard
)

router = Router()

async def safe_answer(callback: CallbackQuery, text: str | None = None, show_alert: bool = False):
    try:
        await callback.answer(text=text, show_alert=show_alert)
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
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Бот создан для удобного оформления и сопровождения сделок по покупке Telegram NFT-подарков.\n\n"
        "⚡ <b>Возможности:</b>\n"
        "• Мгновенное формирование офферов в личных переписках через Telegram Business\n"
        "• Инлайн-режим в любых чатах и группах (тариф PRO)\n"
        "• Интерактивная карточка с превью подарка, ценой и кнопками\n"
        "• Реферальная программа: <b>+6 часов подписки</b> за каждого приглашённого друга\n\n"
        "Выберите раздел ниже для ознакомления:"
    )

async def build_profile_text(user, bot: Bot) -> str:
    user_id = user.id
    is_admin = user_id in config.ADMIN_IDS
    sub = await db.get_subscription(user_id)
    ref_count = await db.get_referral_count(user_id)

    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

    is_active = is_admin
    if is_admin:
        sub_status = "👑 <b>Администратор</b> (Бессрочный PRO доступ)"
        plan_desc = "Тариф: <b>💎 PRO (Инлайн + Business)</b>"
        time_desc = "Срок: <b>Не ограничен</b>"
    elif sub:
        now = datetime.utcnow()
        try:
            exp_dt = datetime.strptime(sub["expires_at"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            exp_dt = now

        if exp_dt > now:
            is_active = True
            plan_name = "💎 PRO (Инлайн)" if sub.get("plan") == "pro" else "⭐️ Стандарт"
            sub_status = "✅ <b>Активна</b>"
            plan_desc = f"Тариф: <b>{plan_name}</b>"
            time_desc = f"Действует до: <b>{format_date_display(sub['expires_at'])}</b>"
        else:
            sub_status = "❌ <b>Истекла</b>"
            plan_desc = f"Предыдущий тариф: <b>{'💎 PRO' if sub.get('plan') == 'pro' else '⭐️ Стандарт'}</b>"
            time_desc = f"Закончилась: <b>{format_date_display(sub['expires_at'])}</b>"
    else:
        sub_status = "❌ <b>Не активна</b>"
        plan_desc = "Тариф: <i>Отсутствует</i>"
        time_desc = "<i>Оформите подписку для создания офферов</i>"

    username_str = f"@{user.username}" if user.username else "—"
    first_name_str = user.first_name or "Пользователь"

    if is_active:
        ref_block = (
            f"👥 <b>Приглашено рефералов:</b> <b>{ref_count}</b> чел. (+{ref_count * 6} ч. бонусов)\n"
            f"🔗 <b>Ваша реферальная ссылка:</b>\n"
            f"<code>{ref_link}</code>"
        )
    else:
        ref_block = (
            "👥 <b>Реферальная программа:</b> <i>Доступна только после оформления подписки (+6 ч. за друга)</i>"
        )

    return (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
        f"👤 <b>Имя:</b> {first_name_str}\n"
        f"🏷 <b>Юзернейм:</b> {username_str}\n\n"
        f"⭐️ <b>Статус подписки:</b> {sub_status}\n"
        f"• {plan_desc}\n"
        f"• {time_desc}\n\n"
        f"{ref_block}"
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

# --- MENU NAVIGATION & REFERRALS ---

@router.message(CommandStart())
async def handle_start(message: Message, command: CommandObject, bot: Bot):
    user_id = message.from_user.id
    await db.register_user(user_id, message.from_user.username, message.from_user.first_name)

    # Referral checking - available only if referrer has an active subscription
    if command.args and command.args.startswith("ref_"):
        try:
            ref_id = int(command.args.replace("ref_", ""))
            if ref_id != user_id:
                referrer_active = await db.is_subscription_active(ref_id)
                if referrer_active:
                    success = await db.register_referral(referrer_id=ref_id, new_user_id=user_id)
                    if success:
                        new_exp = await db.add_or_extend_subscription_hours(ref_id, hours=6)
                        date_display = format_date_display(new_exp)

                        new_user = message.from_user
                        if new_user.username:
                            new_user_display = f"@{new_user.username}"
                        else:
                            new_user_display = f"<a href='tg://user?id={new_user.id}'>{new_user.first_name}</a>"

                        try:
                            await bot.send_message(
                                chat_id=ref_id,
                                text=(
                                    "🎉 <b>Новый реферал!</b>\n\n"
                                    f"По вашей ссылке зарегистрировался пользователь {new_user_display} (ID: <code>{new_user.id}</code>).\n\n"
                                    f"🎁 Вам начислено <b>+6 часов подписки</b>!\n"
                                    f"📅 Действует до: <b>{date_display}</b>"
                                ),
                                parse_mode="HTML"
                            )
                        except Exception as e:
                            print(f"Error sending referral notification to {ref_id}: {e}")
        except Exception as e:
            print(f"Error in referral processing: {e}")

    await message.answer(get_welcome_text(), reply_markup=get_main_menu_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "menu_main")
async def handle_menu_main(callback: CallbackQuery):
    try:
        await callback.message.edit_text(get_welcome_text(), reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
    except Exception:
        pass
    await safe_answer(callback)

# --- SUCCESSFUL DEALS LIST ---

@router.callback_query(F.data == "menu_deals")
async def handle_menu_deals(callback: CallbackQuery):
    deals = await db.get_successful_deals(limit=10)

    if not deals:
        text = (
            "🔥 <b>Успешно завершённые сделки</b>\n\n"
            "Здесь отображаются только реальные подтверждённые офферы, по которым NFT-подарок был передан получателю.\n\n"
            "<i>Список обновляется автоматически при завершении новых сделок.</i>"
        )
    else:
        text = (
            "🔥 <b>Успешно завершённые сделки</b>\n\n"
            "Список последних подтверждённых офферов с успешной передачей подарка:\n\n"
        )
        for i, d in enumerate(deals, 1):
            num = format_number(d['nft_number'])
            stars = format_number(d['stars_amount'])
            date_str = format_date_display(d.get('created_at', ''))
            text += (
                f"{i}. 🎁 <b>{d['nft_name']} #{num}</b>\n"
                f"   • Сумма: <b>{stars} Stars</b>\n"
                f"   • Получатель: <code>@DealNftOffer</code>\n"
                f"   • Статус: ✅ <b>Подарок передан и получен</b> ({date_str})\n\n"
            )

    try:
        await callback.message.edit_text(text, reply_markup=get_deals_keyboard(), parse_mode="HTML")
    except Exception:
        pass
    await safe_answer(callback)

# --- REFERRAL SYSTEM ---

@router.callback_query(F.data == "menu_referral")
async def handle_menu_referral(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    is_active = await db.is_subscription_active(user_id)
    if not is_active:
        text = (
            "🔒 <b>Реферальная программа недоступна</b>\n\n"
            "Реферальная система и пригласительные ссылки доступны только пользователям с активной подпиской.\n\n"
            "Оформите подписку, чтобы приглашать друзей и получать <b>+6 часов</b> к сроку действия за каждого приглашённого!"
        )
        try:
            await callback.message.edit_text(text, reply_markup=get_buy_sub_keyboard(), parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=get_buy_sub_keyboard(), parse_mode="HTML")
        await safe_answer(callback)
        return

    ref_count = await db.get_referral_count(user_id)
    me = await bot.get_me()
    bot_username = me.username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    text = (
        "👥 <b>Реферальная программа</b>\n\n"
        "Приглашайте друзей и продлевайте подписку бесплатно!\n\n"
        "🎁 <b>Условия:</b>\n"
        "За каждого нового пользователя, перешедшего по вашей ссылке, вы получаете <b>+6 часов</b> к вашей подписке.\n\n"
        "📊 <b>Ваша статистика:</b>\n"
        f"• Приглашено пользователей: <b>{ref_count}</b>\n"
        f"• Получено бонусов: <b>+{ref_count * 6} часов</b>\n\n"
        "🔗 <b>Ваша ссылка для приглашения:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "<i>Нажмите кнопку ниже, чтобы поделиться ссылкой в Telegram:</i>"
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_referral_keyboard(bot_username, user_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await safe_answer(callback)

# --- SUBSCRIPTION MENU (ТАРИФЫ СТАНДАРТ И PRO) ---

@router.callback_query(F.data == "menu_sub")
@router.message(Command("subscribe", "sub", "profile"))
async def handle_subscription_view(event: Message | CallbackQuery):
    user_id = event.from_user.id
    await db.register_user(user_id, event.from_user.username, event.from_user.first_name)
    sub = await db.get_subscription(user_id)
    is_active = await db.is_subscription_active(user_id)
    current_plan = sub.get("plan", "standard") if (is_active and sub) else None

    if is_active and sub:
        plan_name = "💎 PRO (Инлайн + Business)" if current_plan == "pro" else "⭐️ Стандарт (Business)"
        date_str = format_date_display(sub["expires_at"])
        status_text = (
            f"• Ваш тариф: <b>{plan_name}</b>\n"
            f"• Статус: 🟢 <b>Активен до {date_str}</b>\n\n"
        )
    else:
        status_text = "• Статус: 🔴 <b>Не активен</b>\n\n"

    text = (
        "⭐️ <b>Тарифные планы</b>\n\n"
        f"{status_text}"
        f"<b>1. Тариф «Стандарт» ({SUB_STANDARD_PRICE} Stars / {SUB_DURATION_DAYS} дней)</b>\n"
        "• Работа через Telegram Business в личных переписках\n"
        "• Создание офферов через команду <code>.buy</code>\n"
        "• Передача подарка на @DealNftOffer\n\n"
        f"<b>2. Тариф «PRO / Инлайн» ({SUB_PRO_PRICE} Stars / {SUB_DURATION_DAYS} дней)</b>\n"
        "• Всё, что входит в «Стандарт»\n"
        "• <b>Инлайн-режим в любых чатах</b>\n\n"
        "<b>В чём суть:</b>\n"
        "Сейчас для отправки в чужих чатах нужен Telegram Business. А с инлайн-режимом вы сможете в абсолютно любом чате, группе или канале написать: "
        "<code>@SAgaFE_bot https://t.me/nft/... 1200</code> "
        "и прямо во всплывающем меню в один клик отправить готовую карточку с кнопками!\n\n"
        "<b>Плюс:</b>\n"
        "Работает даже без Telegram Premium и в любых группах.\n\n"
        "<i>Выберите подходящий тариф ниже для оплаты:</i>"
    )

    keyboard = get_sub_menu_keyboard(current_plan)
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        await safe_answer(event)
    else:
        await event.answer(text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data == "menu_guide")
async def handle_menu_guide(callback: CallbackQuery):
    text = (
        "📖 <b>Как пользоваться командой .buy</b>\n\n"
        "1. Откройте диалог с продавцом NFT-подарка.\n"
        "2. Отправьте сообщение в формате:\n"
        "<code>.buy ссылка_на_подарок сумма_звезд</code>\n\n"
        "<i>Пример:</i>\n"
        "<code>.buy https://t.me/nft/libertyfigure-264534 1200</code>\n\n"
        "3. Сообщение превратится в карточку с кнопками <b>«Принять»</b> и <b>«Отклонить»</b>.\n"
        "4. После принятия продавец передаст подарок и подтвердит отправку."
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")
    except Exception:
        pass
    await safe_answer(callback)

@router.callback_query(F.data == "menu_business")
async def handle_menu_business(callback: CallbackQuery):
    text = (
        "💼 <b>Подключение Telegram Business</b>\n\n"
        "Чтобы бот создавал офферы прямо в ваших личных переписках с продавцами:\n\n"
        "1. Перейдите в <b>Настройки</b> Telegram (нужен Telegram Premium).\n"
        "2. Откройте <b>Telegram Business</b> ➡️ <b>Чат-боты</b>.\n"
        "3. Добавьте бота и включите <b>«Управление чатами»</b>.\n\n"
        "После этого команда <code>.buy</code> в переписке с продавцом будет преобразовываться в оффер."
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")
    except Exception:
        pass
    await safe_answer(callback)

@router.callback_query(F.data == "menu_faq")
async def handle_menu_faq(callback: CallbackQuery):
    text = (
        "❓ <b>Часто задаваемые вопросы</b>\n\n"
        "• <b>Где взять ссылку на NFT?</b>\n"
        "В профиле владельца подарка или на Fragment. Ссылка выглядит как <code>https://t.me/nft/...</code>.\n\n"
        "• <b>Как продавец передаёт подарок?</b>\n"
        "На странице подарка в Telegram нажимает «Передать подарок» и выбирает профиль <code>@DealNftOffer</code>.\n\n"
        "• <b>Чем PRO отличается от Стандарта?</b>\n"
        "В PRO доступен инлайн-режим — отправка офферов в любых группах и чатах через <code>@SAgaFE_bot ссылка цена</code> без необходимости иметь Telegram Business."
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode="HTML")
    except Exception:
        pass
    await safe_answer(callback)

# --- PAYMENT PROCESSING (STANDARD & PRO) ---

@router.callback_query(F.data.startswith("pay_sub"))
async def handle_pay_sub(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    target_plan = "pro" if "pro" in callback.data else "standard"
    price = SUB_PRO_PRICE if target_plan == "pro" else SUB_STANDARD_PRICE
    plan_title = "Тариф PRO (Инлайн + Business)" if target_plan == "pro" else "Тариф Стандарт (Business)"

    prices = [LabeledPrice(label=f"{plan_title} на {SUB_DURATION_DAYS} дней", amount=price)]

    try:
        await bot.send_invoice(
            chat_id=user_id,
            title=f"⭐️ {plan_title}",
            description=f"Полный доступ к тарифу {plan_title} на {SUB_DURATION_DAYS} дней",
            payload=f"sub_{target_plan}_{SUB_DURATION_DAYS}d_{user_id}",
            currency="XTR",
            prices=prices,
            provider_token=""
        )
        await safe_answer(callback)
    except Exception as e:
        print(f"Error sending invoice: {e}")
        await safe_answer(callback, "Ошибка при формировании счёта. Попробуйте снова.", show_alert=True)

@router.pre_checkout_query()
async def handle_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    if pre_checkout_query.currency != "XTR":
        await pre_checkout_query.answer(ok=False, error_message="Ошибка оплаты.")
        return
    if pre_checkout_query.total_amount not in (SUB_STANDARD_PRICE, SUB_PRO_PRICE):
        await pre_checkout_query.answer(ok=False, error_message="Неверная сумма.")
        return
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    sp = message.successful_payment
    user = message.from_user
    payload = sp.invoice_payload or ""
    plan = "pro" if "pro" in payload else "standard"
    plan_name = "💎 PRO / Инлайн" if plan == "pro" else "⭐️ Стандарт"

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

# --- INLINE MODE HANDLER (ТАРИФ PRO) ---

@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery, bot: Bot):
    query_text = inline_query.query.strip()
    user = inline_query.from_user

    # Check PRO subscription
    has_pro = await db.is_subscription_active(user.id, required_plan="pro")
    if not has_pro:
        await inline_query.answer([], cache_time=1, is_personal=True)
        return

    args = extract_buy_args(query_text)
    if not args:
        hint_title = "💡 Ссылка на NFT и количество звёзд"
        hint_desc = "Пример: https://t.me/nft/libertyfigure-264534 1200"

        if any(d in query_text.lower() for d in ["t.me/nft/", "fragment.com"]):
            hint_title = "⭐️ Укажите количество звёзд через пробел"
            hint_desc = f"{query_text.strip()} 1200"

        article = InlineQueryResultArticle(
            id="hint",
            title=hint_title,
            description=hint_desc,
            input_message_content=InputTextMessageContent(
                message_text="Формат оффера: <code>@SAgaFE_bot ссылка_на_nft сумма_звезд</code>",
                parse_mode="HTML"
            )
        )
        await inline_query.answer([article], cache_time=1, is_personal=True)
        return

    nft_url, stars_amount = args
    nft_data = await parse_nft_url(nft_url)

    # Pre-create deal in DB
    deal_id = await db.create_deal(
        buyer_id=user.id,
        buyer_username=user.username,
        buyer_first_name=user.first_name,
        seller_id=None,
        nft_name=nft_data["name"],
        nft_number=nft_data["number"],
        nft_url=nft_data["url"],
        image_url=nft_data.get("image_url"),
        stars_amount=stars_amount,
        chat_id=None
    )

    formatted_number = format_number(nft_data["number"])
    message_text = (
        f'<a href="{nft_data["url"]}">&#8203;</a>'
        f"Пользователь предлагает Вам {stars_amount} ⭐️ за подарок {nft_data['name']} #{formatted_number}.\n\n"
        f"Предложение действительно 5ч 59м ."
    )

    link_opts = LinkPreviewOptions(
        url=nft_data["url"],
        prefer_large_media=True,
        show_above_text=True
    )

    keyboard = get_screen1_keyboard(deal_id=deal_id)

    article_kwargs = {
        "id": f"deal_{deal_id}",
        "title": f"🎁 Оффер: {nft_data['name']} #{formatted_number}",
        "description": f"Предложить {stars_amount} Stars за подарок",
        "input_message_content": InputTextMessageContent(
            message_text=message_text,
            parse_mode="HTML",
            link_preview_options=link_opts
        ),
        "reply_markup": keyboard
    }
    if nft_data.get("image_url") and str(nft_data["image_url"]).startswith("http"):
        article_kwargs["thumbnail_url"] = nft_data["image_url"]

    article = InlineQueryResultArticle(**article_kwargs)

    try:
        await inline_query.answer([article], cache_time=1, is_personal=True)
    except Exception as e:
        print(f"Error answering inline query: {e}")

@router.chosen_inline_result()
async def handle_chosen_inline_result(chosen_result: ChosenInlineResult):
    if chosen_result.result_id.startswith("deal_") and chosen_result.inline_message_id:
        try:
            deal_id = int(chosen_result.result_id.replace("deal_", ""))
            await db.set_deal_inline_message_id(deal_id, chosen_result.inline_message_id)
        except Exception:
            pass

# --- BUSINESS CONNECTION ---

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
                text="✅ <b>Telegram Business подключён успешно!</b>\nТеперь вы можете отправлять офферы через <code>.buy</code> в личных переписках.",
                parse_mode="HTML"
            )
        except Exception:
            pass

# --- BUY OFFER PROCESSOR ---

async def process_buy_offer(
    bot: Bot,
    text: str,
    buyer,
    chat_id: int,
    original_message_id: int,
    business_connection_id: str | None,
    target_seller_id: int | None = None,
    target_seller_username: str | None = None
):
    # Subscription gate
    is_active = await db.is_subscription_active(buyer.id)
    if not is_active:
        msg_text = (
            "Для использования команды <code>.buy</code> требуется активная подписка.\n\n"
            "Оформить доступ можно кнопкой ниже (или получить бесплатно в реферальной системе):"
        )
        if business_connection_id:
            try:
                await bot.send_message(
                    chat_id=buyer.id,
                    text=msg_text,
                    parse_mode="HTML",
                    reply_markup=get_buy_sub_keyboard()
                )
            except Exception:
                pass
            return
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=msg_text,
                parse_mode="HTML",
                reply_markup=get_buy_sub_keyboard()
            )
            return

    args = extract_buy_args(text)
    if not args:
        if not business_connection_id:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "Формат команды:\n"
                    "<code>.buy ссылка_на_nft сумма_звезд</code>\n\n"
                    "<i>Пример:</i>\n"
                    "<code>.buy https://t.me/nft/libertyfigure-264534 1200</code>"
                ),
                parse_mode="HTML"
            )
        return

    nft_url, stars_amount = args
    nft_data = await parse_nft_url(nft_url)

    deal_id = await db.create_deal(
        buyer_id=buyer.id,
        buyer_username=buyer.username,
        buyer_first_name=buyer.first_name,
        seller_id=target_seller_id,
        nft_name=nft_data["name"],
        nft_number=nft_data["number"],
        nft_url=nft_data["url"],
        image_url=nft_data["image_url"],
        stars_amount=stars_amount,
        chat_id=chat_id,
        business_connection_id=business_connection_id
    )

    formatted_number = format_number(nft_data["number"])

    # Screen 1 Text (Identical to Screenshot 1)
    message_text = (
        f'<a href="{nft_data["url"]}">&#8203;</a>'
        f"Пользователь предлагает Вам {stars_amount} ⭐️ за подарок {nft_data['name']} #{formatted_number}.\n\n"
        f"Предложение действительно 5ч 59м ."
    )

    keyboard = get_screen1_keyboard(deal_id=deal_id)

    link_opts = LinkPreviewOptions(
        url=nft_data["url"],
        prefer_large_media=True,
        show_above_text=True
    )

    if business_connection_id:
        edited_successfully = False
        try:
            await bot.edit_message_text(
                business_connection_id=business_connection_id,
                chat_id=chat_id,
                message_id=original_message_id,
                text=message_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=keyboard
            )
            await db.set_deal_message_id(deal_id, original_message_id)
            edited_successfully = True
        except Exception:
            pass

        if not edited_successfully:
            sent_msg = await bot.send_message(
                business_connection_id=business_connection_id,
                chat_id=chat_id,
                text=message_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=keyboard
            )
            if sent_msg:
                await db.set_deal_message_id(deal_id, sent_msg.message_id)
            try:
                await bot.delete_message(chat_id=chat_id, message_id=original_message_id)
            except Exception:
                pass
    else:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=original_message_id)
        except Exception:
            pass

        sent_msg = await bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode="HTML",
            link_preview_options=link_opts,
            reply_markup=keyboard
        )
        if sent_msg:
            await db.set_deal_message_id(deal_id, sent_msg.message_id)

@router.business_message(F.text.regexp(r'^(?:[./]buy|@\w+_bot(?:\s+[./]?buy)?|\S+\s+https?://).*', flags=re.IGNORECASE))
async def handle_business_buy(message: Message, bot: Bot):
    target_seller_id = message.chat.id
    target_seller_username = message.chat.username

    await process_buy_offer(
        bot=bot,
        text=message.text or "",
        buyer=message.from_user,
        chat_id=message.chat.id,
        original_message_id=message.message_id,
        business_connection_id=message.business_connection_id,
        target_seller_id=target_seller_id,
        target_seller_username=target_seller_username
    )

@router.message(F.text.regexp(r'^(?:[./]buy|@\w+_bot(?:\s+[./]?buy)?|\S+\s+https?://).*', flags=re.IGNORECASE))
async def handle_regular_buy(message: Message, bot: Bot):
    target_seller_id = None
    target_seller_username = None
    if message.reply_to_message and message.reply_to_message.from_user:
        replied_user = message.reply_to_message.from_user
        if replied_user.id != message.from_user.id and not replied_user.is_bot:
            target_seller_id = replied_user.id
            target_seller_username = replied_user.username

    await process_buy_offer(
        bot=bot,
        text=message.text or "",
        buyer=message.from_user,
        chat_id=message.chat.id,
        original_message_id=message.message_id,
        business_connection_id=None,
        target_seller_id=target_seller_id,
        target_seller_username=target_seller_username
    )

# --- DEAL CALLBACK HANDLERS (SUPPORTS INLINE MESSAGES TOO) ---

@router.callback_query(F.data.startswith("accept:"))
async def handle_accept_callback(callback: CallbackQuery, bot: Bot):
    deal_id = int(callback.data.split(":")[1])
    deal = await db.get_deal(deal_id)

    if not deal:
        await safe_answer(callback, "Оффер не найден!", show_alert=True)
        return

    if deal["status"] != "PENDING":
        await safe_answer(callback, "Этот оффер уже был принят, отклонён или истёк!", show_alert=True)
        return

    user = callback.from_user
    if user.id == deal["buyer_id"]:
        await safe_answer(callback, "Вы не можете принять собственный оффер!", show_alert=True)
        return

    await db.accept_deal(deal_id, seller_id=user.id, seller_username=user.username)

    buyer_display = "@DealNftOffer"
    formatted_number = format_number(deal["nft_number"])
    target_transfer_url = "https://t.me/DealNftOffer"

    # Screen 2 Text (Идентично Скриншоту 2)
    screen2_text = (
        f'<a href="{deal["nft_url"]}">&#8203;</a>'
        f"<b>Оффер подтверждён</b>\n\n"
        f"Подарок: {deal['nft_name']} #{formatted_number}\n"
        f"Сумма: {deal['stars_amount']} Stars\n"
        f"Покупатель: {buyer_display}\n\n"
        f"Нажмите «Отправить подарок», чтобы открыть этот NFT в Telegram. "
        f"На его странице нажмите «Передать подарок», выберите {buyer_display}, "
        f"проверьте системное подтверждение Telegram и подтвердите передачу. "
        f"Затем вернитесь сюда и нажмите «Подарок отправлен». После этого покупатель сможет подтвердить получение.\n\n"
        f"Оплату стороны согласуют отдельно; бот её не принимает и не проверяет."
    )

    keyboard = get_screen2_keyboard(nft_url=target_transfer_url, deal_id=deal_id)

    link_opts = LinkPreviewOptions(
        url=deal["nft_url"],
        prefer_large_media=True,
        show_above_text=True
    )

    try:
        if callback.inline_message_id:
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=screen2_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=keyboard
            )
        elif deal.get("business_connection_id"):
            await bot.edit_message_text(
                business_connection_id=deal["business_connection_id"],
                chat_id=deal["chat_id"],
                message_id=deal["message_id"],
                text=screen2_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=keyboard
            )
        else:
            await callback.message.edit_text(
                text=screen2_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=keyboard
            )
        await safe_answer(callback, "Вы приняли оффер!")
    except Exception as e:
        print(f"Error editing message to Screen 2: {e}")
        await safe_answer(callback)


@router.callback_query(F.data.startswith("decline:"))
async def handle_decline_callback(callback: CallbackQuery, bot: Bot):
    deal_id = int(callback.data.split(":")[1])
    deal = await db.get_deal(deal_id)

    if not deal:
        await safe_answer(callback, "Оффер не найден!", show_alert=True)
        return

    if deal["status"] != "PENDING":
        await safe_answer(callback, "Этот оффер уже неактивен!", show_alert=True)
        return

    user = callback.from_user
    if deal["seller_id"] and user.id not in (deal["buyer_id"], deal["seller_id"]):
        await safe_answer(callback, "Вы не являетесь участником этой сделки!", show_alert=True)
        return

    await db.set_deal_status(deal_id, "DECLINED")

    declined_text = (
        f'<a href="{deal["nft_url"]}">&#8203;</a>'
        f"❌ <b>Оффер отклонён</b>\n\n"
        f"Подарок: {deal['nft_name']} #{format_number(deal['nft_number'])}\n"
        f"Сумма: {deal['stars_amount']} Stars"
    )

    link_opts = LinkPreviewOptions(
        url=deal["nft_url"],
        prefer_large_media=True,
        show_above_text=True
    )

    try:
        if callback.inline_message_id:
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=declined_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=None
            )
        elif deal.get("business_connection_id"):
            await bot.edit_message_text(
                business_connection_id=deal["business_connection_id"],
                chat_id=deal["chat_id"],
                message_id=deal["message_id"],
                text=declined_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=None
            )
        else:
            await callback.message.edit_text(
                text=declined_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=None
            )
        await safe_answer(callback, "Оффер отклонён.")
    except Exception as e:
        print(f"Error updating decline: {e}")
        await safe_answer(callback)


@router.callback_query(F.data.startswith("sent:"))
async def handle_sent_callback(callback: CallbackQuery, bot: Bot):
    deal_id = int(callback.data.split(":")[1])
    deal = await db.get_deal(deal_id)

    if not deal:
        await safe_answer(callback, "Оффер не найден!", show_alert=True)
        return

    if deal["status"] != "ACCEPTED":
        await safe_answer(callback, "Действие недоступно для текущего статуса сделки!", show_alert=True)
        return

    user = callback.from_user
    if user.id != deal["seller_id"]:
        await safe_answer(callback, "Только продавец может подтвердить отправку подарка!", show_alert=True)
        return

    await db.set_deal_status(deal_id, "SENT")

    buyer_display = "@DealNftOffer"
    formatted_number = format_number(deal["nft_number"])

    # Screen 3 status text
    screen3_text = (
        f'<a href="{deal["nft_url"]}">&#8203;</a>'
        f"<b>Оффер подтверждён</b>\n\n"
        f"Подарок: {deal['nft_name']} #{formatted_number}\n"
        f"Сумма: {deal['stars_amount']} Stars\n"
        f"Покупатель: {buyer_display}\n\n"
        f"⏳ <b>Подарок отправлен. Ожидание получения покупателя {buyer_display}...</b>\n\n"
        f"⭐️ <b>Ожидайте звёзды в течение 24 часов.</b>"
    )

    link_opts = LinkPreviewOptions(
        url=deal["nft_url"],
        prefer_large_media=True,
        show_above_text=True
    )

    try:
        if callback.inline_message_id:
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=screen3_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=None
            )
        elif deal.get("business_connection_id"):
            await bot.edit_message_text(
                business_connection_id=deal["business_connection_id"],
                chat_id=deal["chat_id"],
                message_id=deal["message_id"],
                text=screen3_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=None
            )
        else:
            await callback.message.edit_text(
                text=screen3_text,
                parse_mode="HTML",
                link_preview_options=link_opts,
                reply_markup=None
            )
    except Exception as e:
        print(f"Error updating message to sent status: {e}")

    # Notification to recipient channel/chat
    try:
        await bot.send_message(
            chat_id=config.GIFT_RECIPIENT,
            text=(
                f"🎁 <b>Новый подарок отправлен!</b>\n\n"
                f"• Подарок: <b>{deal['nft_name']} #{formatted_number}</b>\n"
                f"• Сумма: <b>{deal['stars_amount']} Stars</b>\n"
                f"• Продавец: @{deal.get('seller_username') or deal['seller_id']}\n"
                f"• Ссылка: {deal['nft_url']}"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    buyer_confirm_kb = get_screen3_buyer_keyboard(deal_id)
    buyer_prompt_text = (
        f"📦 {buyer_display}, продавец отметил, что подарок <b>{deal['nft_name']} #{formatted_number}</b> отправлен!\n\n"
        f"Пожалуйста, подтвердите получение, когда подарок поступит в ваш профиль:"
    )

    if deal.get("business_connection_id"):
        try:
            await bot.send_message(
                business_connection_id=deal["business_connection_id"],
                chat_id=deal["chat_id"],
                text=buyer_prompt_text,
                reply_markup=buyer_confirm_kb,
                parse_mode="HTML"
            )
        except Exception:
            try:
                await bot.send_message(
                    chat_id=deal["buyer_id"],
                    text=buyer_prompt_text,
                    reply_markup=buyer_confirm_kb,
                    parse_mode="HTML"
                )
            except Exception:
                pass
    elif not callback.inline_message_id:
        await callback.message.answer(
            text=buyer_prompt_text,
            reply_markup=buyer_confirm_kb,
            parse_mode="HTML"
        )
    else:
        # For inline mode: send to buyer PM
        try:
            await bot.send_message(
                chat_id=deal["buyer_id"],
                text=buyer_prompt_text,
                reply_markup=buyer_confirm_kb,
                parse_mode="HTML"
            )
        except Exception:
            pass

    await safe_answer(callback, "Вы подтвердили отправку подарка!")


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

    # Mark as COMPLETED! Now this deal will strictly appear in the successful deals list
    await db.set_deal_status(deal_id, "COMPLETED")

    buyer_display = "@DealNftOffer"
    formatted_number = format_number(deal["nft_number"])

    completed_text = (
        f'<a href="{deal["nft_url"]}">&#8203;</a>'
        f"🎉 <b>Сделка успешно завершена!</b>\n\n"
        f"Подарок <b>{deal['nft_name']} #{formatted_number}</b> успешно получен покупателем {buyer_display}.\n"
        f"Сумма: <b>{deal['stars_amount']} Stars</b>.\n\n"
        f"⭐️ <b>Ожидайте звёзды в течение 24 часов.</b>"
    )

    try:
        if callback.inline_message_id:
            await bot.edit_message_text(inline_message_id=callback.inline_message_id, text=completed_text, reply_markup=None, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=completed_text, reply_markup=None, parse_mode="HTML")
        await safe_answer(callback, "Получение подтверждено! Сделка завершена.")
    except Exception as e:
        print(f"Error in confirm handler: {e}")
        await safe_answer(callback)

    # Message in Business chat
    if deal.get("business_connection_id"):
        try:
            await bot.send_message(
                business_connection_id=deal["business_connection_id"],
                chat_id=deal["chat_id"],
                text="⭐️ <b>Ожидайте звёзды в течение 24 часов.</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    # Direct notification to seller
    if deal.get("seller_id"):
        try:
            await bot.send_message(
                chat_id=deal["seller_id"],
                text=(
                    f"🎉 <b>Сделка завершена!</b>\n\n"
                    f"Подарок <b>{deal['nft_name']} #{formatted_number}</b> подтверждён.\n"
                    f"Сумма к выплате: <b>{deal['stars_amount']} Stars</b>.\n\n"
                    f"⭐️ <b>Ожидайте звёзды в течение 24 часов.</b>"
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass
