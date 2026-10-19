import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest

import config
import database as db
from handlers import (
    router, verify_deal_gift_received, complete_deal_with_guarantor,
    safe_edit_deal_message, get_deal_buyer_info, star_gifts_background_checker
)
from admin_handlers import admin_router
from middlewares import ThrottlingMiddleware
from worker_manager import worker_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nft_bot")

from aiogram.types import LinkPreviewOptions
from keyboards import get_screen1_keyboard, get_confirm_accept_keyboard
from parser import format_number, format_offer_timer, close_http_session
from ton_payments import ton_background_checker

async def countdown_timer_worker(bot: Bot):
    """
    Выделенный быстрый воркер обновления таймера в активных офферах (PENDING и CONFIRMING).
    Проверяет каждые 8-10 секунд и плавно обновляет сообщение ТОЛЬКО при смене минуты.
    """
    logger.info("Countdown timer worker started.")
    while True:
        try:
            await asyncio.sleep(10)
            active_deals = await db.get_active_pending_deals()
            active_ids = {d["deal_id"] for d in active_deals}

            # Очищаем устаревшие ID из памяти
            for cached_id in list(config.DEAL_LAST_TIMERS.keys()):
                if cached_id not in active_ids:
                    config.DEAL_LAST_TIMERS.pop(cached_id, None)

            for deal in active_deals:
                deal_id = deal["deal_id"]
                # Skip minute text edits for inline messages to preserve the rich gift card preview
                if deal.get("inline_message_id") and not deal.get("business_connection_id"):
                    continue

                deal_lang = deal.get("lang", "RU")
                timer_str = format_offer_timer(deal.get("expires_at"), lang=deal_lang)
                last_timer = config.DEAL_LAST_TIMERS.get(deal_id)

                if last_timer == timer_str:
                    # Минута ещё не сменилась, пропускаем
                    continue

                if last_timer is None:
                    # Оффер только появился, фиксируем текущий таймер без перередактирования
                    config.DEAL_LAST_TIMERS[deal_id] = timer_str
                    continue

                # Минута сменилась!
                config.DEAL_LAST_TIMERS[deal_id] = timer_str

                formatted_number = format_number(deal["nft_number"])
                curr_symbol = "GRAM" if deal.get("currency") == "GRAM" else "⭐️"
                stars_txt = f"{deal['stars_amount']} {curr_symbol}"

                link_opts = LinkPreviewOptions(
                    url=deal["nft_url"],
                    prefer_large_media=True,
                    show_above_text=True
                )

                if deal_lang == "ENG":
                    msg_text = (
                        f"A user offers you <b>{stars_txt}</b> for gift <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>.\n\n"
                        f"Expires in {timer_str}."
                    )
                else:
                    msg_text = (
                        f"Пользователь предлагает Вам <b>{stars_txt}</b> за подарок <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{formatted_number}</b></a>.\n\n"
                        f"Истекает через {timer_str}."
                    )
                kb = get_screen1_keyboard(deal_id=deal_id, lang=deal_lang)

                try:
                    await safe_edit_deal_message(
                        bot=bot,
                        deal=deal,
                        text=msg_text,
                        reply_markup=kb,
                        link_opts=link_opts,
                        inline_message_id=deal.get("inline_message_id")
                    )
                    logger.info(f"Updated countdown for deal #{deal_id}: {timer_str}")
                except Exception as e_upd:
                    logger.debug(f"Failed to update timer for deal #{deal_id}: {e_upd}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in countdown timer worker: {e}")

async def expiration_checker(bot: Bot):
    """
    Периодическая фоновая проверка офферов:
    1. Проверяет принятые офферы на поступление подарка гаранту (@DealNftOffer) и завершает сделку.
    2. Реально истекшие по таймеру офферы (через 6 часов) переводит в EXPIRED и обновляет сообщение.
    """
    while True:
        try:
            await asyncio.sleep(20)
            await db.cleanup_orphan_deals(older_than_minutes=15)

            # Auto-verification for accepted deals transferred to guarantor
            accepted_deals = await db.get_accepted_deals()
            for deal in accepted_deals:
                try:
                    is_rcv, gift_title = await verify_deal_gift_received(deal, bot)
                    if is_rcv:
                        logger.info(f"Auto-verified gift receipt for deal #{deal['deal_id']} ({gift_title})! Completing deal.")
                        await complete_deal_with_guarantor(bot, deal)
                except Exception as e:
                    logger.debug(f"Error checking accepted deal #{deal.get('deal_id')}: {e}")

            # Check expired deals (когда реально истекло 6 часов)
            expired_deals = await db.get_pending_expired_deals()
            for deal in expired_deals:
                deal_id = deal["deal_id"]
                config.DEAL_LAST_TIMERS.pop(deal_id, None)
                await db.set_deal_status(deal_id, "EXPIRED")
                logger.info(f"Deal #{deal_id} expired.")
                deal_lang = deal.get("lang", "RU")
                curr_txt = "GRAM" if deal.get("currency") == "GRAM" else ("Stars" if deal_lang == "ENG" else "звёзд")
                if deal_lang == "ENG":
                    expired_text = (
                        f"<b>OFFER EXPIRED</b>\n\n"
                        f"<b>Gift:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{deal['nft_number']}</b></a>\n"
                        f"<b>Amount:</b> <b>{deal['stars_amount']} {curr_txt}</b>"
                    )
                else:
                    expired_text = (
                        f"<b>СРОК ДЕЙСТВИЯ ПРЕДЛОЖЕНИЯ ИСТЁК</b>\n\n"
                        f"<b>Подарок:</b> <a href=\"{deal['nft_url']}\"><b>{deal['nft_name']} #{deal['nft_number']}</b></a>\n"
                        f"<b>Сумма:</b> <b>{deal['stars_amount']} {curr_txt}</b>"
                    )
                link_opts = LinkPreviewOptions(
                    url=deal["nft_url"],
                    prefer_large_media=True,
                    show_above_text=True
                )
                await safe_edit_deal_message(
                    bot=bot,
                    deal=deal,
                    text=expired_text,
                    reply_markup=None,
                    link_opts=link_opts,
                    inline_message_id=deal.get("inline_message_id")
                )

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in expiration checker: {e}")

async def start_web_server():
    try:
        import uvicorn
        from web_server import app as fastapi_app
        host = getattr(config, "WEB_HOST", "0.0.0.0")
        port = getattr(config, "WEB_PORT", 8080)
        server_config = uvicorn.Config(
            app=fastapi_app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False
        )
        server = uvicorn.Server(server_config)
        logger.info(f"NFT Deals SaaS Web Server running on http://{host}:{port}")
        await server.serve()
    except Exception as e:
        logger.error(f"Error starting web server: {e}")

async def main():
    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n" + "="*60)
        print(" ОШИБКА: Токен бота не указан!")
        print(" Пожалуйста, откройте файл .env и вставьте BOT_TOKEN от @BotFather:")
        print(" BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ")
        print("="*60 + "\n")
        sys.exit(1)

    # Initialize SQLite database
    await db.init_db()
    logger.info("Database initialized successfully.")

    # Create Bot
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    try:
        bot_info = await bot.get_me()
        config.MAIN_BOT_USERNAME = bot_info.username or ""
        logger.info(f"Main bot connected: @{config.MAIN_BOT_USERNAME} (ID: {bot_info.id})")
    except Exception as e_main:
        logger.error("=" * 60)
        logger.error(f" КРИТИЧЕСКАЯ ОШИБКА: Не удалось подключиться к Telegram по BOT_TOKEN!")
        logger.error(f" Ошибка: {e_main}")
        logger.error(f" Возможно, бот был удалён или токен указан неверно.")
        logger.error(f" Пожалуйста, откройте вкладку 'Переменные окружения' или 'Файлы (.env)'")
        logger.error(f" в панели Bothost и укажите новый BOT_TOKEN от @BotFather.")
        logger.error("=" * 60)
        await asyncio.sleep(30)
        sys.exit(1)

    if getattr(config, "DEAL_BOT_TOKEN", None) and config.DEAL_BOT_TOKEN != config.BOT_TOKEN:
        logger.info("Initializing dedicated deal bot from config...")
        ok, res = await worker_manager.start_deal_bot(config.DEAL_BOT_TOKEN)
        if ok:
            logger.info(f"Dedicated deal bot connected: @{res}")
        else:
            logger.warning(f"Could not connect dedicated deal bot ({res}). Falling back to main bot @{config.MAIN_BOT_USERNAME}.")
            config.DEAL_BOT_ID = bot_info.id
            config.DEAL_BOT_USERNAME = config.MAIN_BOT_USERNAME
    else:
        config.DEAL_BOT_ID = bot_info.id
        config.DEAL_BOT_USERNAME = config.MAIN_BOT_USERNAME
        logger.info(f"Режим работы: Single-Bot (все функции и сделки ведёт @{config.MAIN_BOT_USERNAME}).")

    dp = Dispatcher()

    # Anti-Flood & Anti-DDoS Throttling Protection
    dp.message.outer_middleware(ThrottlingMiddleware(limit=0.5))
    dp.callback_query.outer_middleware(ThrottlingMiddleware(limit=0.5))

    _SEEN_USERS = set()

    @dp.update.outer_middleware()
    async def log_update_middleware(handler, event, data):
        logger.info(f"[UPDATE] id={event.update_id} type={event.event_type}")
        if event.inline_query:
            logger.info(f"  -> INLINE_QUERY: user={event.inline_query.from_user.id}, query='{event.inline_query.query}'")
        if event.callback_query:
            logger.info(f"  -> CALLBACK_QUERY: user={event.callback_query.from_user.id}, data='{event.callback_query.data}'")
        if event.message:
            logger.info(f"  -> MESSAGE: chat={event.message.chat.id}, text='{event.message.text}'")
        if event.business_message:
            bm = event.business_message
            logger.info(f"  -> BUSINESS_MESSAGE: conn={bm.business_connection_id}, chat={bm.chat.id}, uname={bm.chat.username}, text='{bm.text}'")
            if bm.chat and bm.chat.id and bm.chat.id not in _SEEN_USERS:
                _SEEN_USERS.add(bm.chat.id)
                uname = bm.chat.username or (bm.from_user.username if bm.from_user else None)
                fname = bm.chat.first_name or (bm.from_user.first_name if bm.from_user else "")
                asyncio.create_task(db.register_user(bm.chat.id, uname, fname))
        return await handler(event, data)

    dp.include_router(admin_router)
    dp.include_router(router)

    # Start all subscriber worker bots restored from database
    logger.info("Initializing subscriber worker bots...")
    asyncio.create_task(worker_manager.start_all_from_db())

    # Run background workers
    timer_task = asyncio.create_task(countdown_timer_worker(bot))
    checker_task = asyncio.create_task(expiration_checker(bot))
    ton_task = asyncio.create_task(ton_background_checker(bot))
    star_gifts_task = asyncio.create_task(star_gifts_background_checker(bot))
    web_task = asyncio.create_task(start_web_server())

    logger.info("Starting Master bot polling with Anti-DDoS & Worker Manager...")
    try:
        await dp.start_polling(
            bot,
            handle_signals=False,
            allowed_updates=[
                "message",
                "edited_message",
                "callback_query",
                "business_connection",
                "business_message",
                "edited_business_message",
                "deleted_business_messages",
                "pre_checkout_query",
                "inline_query",
                "chosen_inline_result"
            ]
        )
    finally:
        web_task.cancel()
        timer_task.cancel()
        checker_task.cancel()
        ton_task.cancel()
        star_gifts_task.cancel()
        await worker_manager.stop_all()
        await bot.session.close()
        await close_http_session()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
