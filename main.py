import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
import database as db
from handlers import router
from admin_handlers import admin_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nft_bot")

async def expiration_checker(bot: Bot):
    """
    Периодическая фоновая проверка истекших офферов (раз в минуту)
    """
    while True:
        try:
            await asyncio.sleep(60)
            expired_deals = await db.get_pending_expired_deals()
            for deal in expired_deals:
                await db.set_deal_status(deal["deal_id"], "EXPIRED")
                logger.info(f"Deal #{deal['deal_id']} expired.")
                expired_text = (
                    f'<a href="{deal["nft_url"]}">&#8203;</a>'
                    f"⏰ <b>Срок действия предложения истёк.</b>\n\n"
                    f"Подарок: {deal['nft_name']} #{deal['nft_number']}\n"
                    f"Сумма: {deal['stars_amount']} Stars"
                )
                if deal.get("inline_message_id"):
                    try:
                        await bot.edit_message_text(
                            inline_message_id=deal["inline_message_id"],
                            text=expired_text,
                            parse_mode="HTML",
                            reply_markup=None
                        )
                    except Exception as e:
                        logger.debug(f"Could not update expired inline message: {e}")
                elif deal.get("chat_id") and deal.get("message_id"):
                    try:
                        if deal.get("business_connection_id"):
                            await bot.edit_message_text(
                                business_connection_id=deal["business_connection_id"],
                                chat_id=deal["chat_id"],
                                message_id=deal["message_id"],
                                text=expired_text,
                                parse_mode="HTML",
                                reply_markup=None
                            )
                        else:
                            await bot.edit_message_text(
                                chat_id=deal["chat_id"],
                                message_id=deal["message_id"],
                                text=expired_text,
                                parse_mode="HTML",
                                reply_markup=None
                            )
                    except Exception as e:
                        logger.debug(f"Could not update expired message: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in expiration checker: {e}")

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

    # Create Bot and Dispatcher
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    @dp.update.outer_middleware()
    async def log_update_middleware(handler, event, data):
        logger.info(f"[UPDATE] id={event.update_id} type={event.event_type}")
        if event.inline_query:
            logger.info(f"  -> INLINE_QUERY: user={event.inline_query.from_user.id}, query='{event.inline_query.query}'")
        if event.message:
            logger.info(f"  -> MESSAGE: chat={event.message.chat.id}, text='{event.message.text}'")
        return await handler(event, data)

    dp.include_router(admin_router)
    dp.include_router(router)

    # Run background expiration worker
    checker_task = asyncio.create_task(expiration_checker(bot))

    logger.info("Starting bot polling with Telegram Business & Stars Payments...")
    try:
        await dp.start_polling(
            bot,
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
        checker_task.cancel()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
