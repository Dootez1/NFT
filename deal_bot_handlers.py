import logging
import asyncio
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, LinkPreviewOptions
import config
import database as db
from parser import format_number, format_offer_timer
from keyboards import get_screen1_keyboard, get_screen2_keyboard
from handlers import get_deal_buyer_info, safe_answer, safe_edit_deal_message, verify_deal_gift_received

from aiogram.filters import CommandStart

logger = logging.getLogger("nft_bot.deal_bot")
deal_router = Router(name="deal_bot")

def is_deal_start(message: Message) -> bool:
    text = (message.text or "").strip()
    if not text.startswith("/start"):
        return False
    parts = text.split()
    if len(parts) > 1:
        arg = parts[1]
        return any(arg.startswith(prefix) for prefix in ("deal_", "accept_", "offer_"))
    return False

@deal_router.message(is_deal_start)
async def handle_deal_bot_message(message: Message, bot: Bot):
    """
    Обрабатывает deep-link перехода по сделке: /start deal_123, /start accept_123
    """
    try:
        await message.delete()
    except Exception:
        pass

    text = (message.text or "").strip()
    deal_id = None
    parts = text.split()
    if len(parts) > 1:
        arg = parts[1]
        for prefix in ("deal_", "accept_", "offer_"):
            if arg.startswith(prefix):
                clean_id = arg.replace(prefix, "").strip()
                if clean_id.isdigit():
                    deal_id = int(clean_id)
                    break

    if not deal_id:
        return

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

    if deal.get("status") in ("CANCELLED", "EXPIRED"):
        await message.answer(
            "❌ <b>Срок действия этого оффера истёк или он был отменён.</b>",
            parse_mode="HTML"
        )
        return

    # Переводим сделку в статус ACCEPTED (если еще не была принята)
    user = message.from_user
    if deal.get("status") in ("PENDING", "CONFIRMING"):
        await db.accept_deal(deal_id, seller_id=user.id, seller_username=user.username)
        await db.set_deal_status(deal_id, "ACCEPTED")
        config.DEAL_LAST_TIMERS.pop(deal_id, None)
        deal = await db.get_deal(deal_id)

        # Уведомляем покупателя в основном боте (@sagefe1_bot)
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
            main_bot = Bot(token=config.BOT_TOKEN)
            try:
                await main_bot.send_message(
                    chat_id=deal["buyer_id"],
                    text=notify_text,
                    parse_mode="HTML"
                )
            finally:
                await main_bot.session.close()
        except Exception as e_notify:
            logger.debug(f"Could not notify buyer about accept: {e_notify}")

    # Формируем Экран 2 (Ожидание передачи подарка)
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


@deal_router.callback_query(F.data.startswith("accept:"))
@deal_router.callback_query(F.data.startswith("confirm_accept:"))
async def handle_deal_accept_callback(callback: CallbackQuery, bot: Bot):
    deal_id = int(callback.data.split(":")[1])
    deal = await db.get_deal(deal_id)

    if not deal:
        await safe_answer(callback, "Оффер не найден!", show_alert=True)
        return

    await safe_answer(callback)

    if deal["status"] not in ("PENDING", "CONFIRMING"):
        if deal["status"] != "ACCEPTED":
            await safe_answer(callback, "Этот оффер уже был отклонён или истёк!", show_alert=True)
            return

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

@deal_router.callback_query(F.data.startswith("cancel_accept:"))
async def handle_deal_cancel_accept(callback: CallbackQuery, bot: Bot):
    deal_id = int(callback.data.split(":")[1])
    deal = await db.get_deal(deal_id)

    if not deal:
        await safe_answer(callback, "Оффер не найден!", show_alert=True)
        return

    if deal["status"] not in ("PENDING", "CONFIRMING"):
        await safe_answer(callback, "Оффер уже неактивен!", show_alert=True)
        return

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

@deal_router.callback_query(F.data.startswith("decline:"))
async def handle_deal_decline(callback: CallbackQuery, bot: Bot):
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

@deal_router.callback_query(F.data.startswith("confirm:"))
async def handle_deal_confirm(callback: CallbackQuery, bot: Bot):
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

    await db.set_deal_status(deal_id, "COMPLETED")

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

@deal_router.callback_query(F.data.startswith("sent:"))
async def handle_deal_bot_sent(callback: CallbackQuery, bot: Bot):
    await safe_answer(callback, "Вы ещё не передали подарок!", show_alert=True)

@deal_router.message()
async def handle_deal_bot_any_message(message: Message):
    """
    В боте сделок удаляются абсолютно все лишние сообщения от пользователей
    (любой текст, команды, стикеры, флуд), чтобы в чате оставалась только официальная карточка сделки.
    """
    try:
        await message.delete()
    except Exception:
        pass

