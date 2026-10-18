import asyncio
import logging
import re
from typing import Optional, Dict, Any, Tuple
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import database as db
import config

logger = logging.getLogger("nft_bot.worker_manager")

class WorkerBotManager:
    """
    Менеджер рабочих ботов-воркеров и центрального бота сделок.
    Позволяет подписчикам подключать личных ботов на лету без перезагрузки сервера,
    а администратору — мгновенно менять бота сделок.
    """
    def __init__(self, worker_dp: Dispatcher):
        self.worker_dp = worker_dp
        self.active_tasks: Dict[int, asyncio.Task] = {}
        self.active_bots: Dict[int, Bot] = {}
        self.deal_bot_task: Optional[asyncio.Task] = None
        self.deal_bot_instance: Optional[Bot] = None

    def is_valid_token(self, token: str) -> bool:
        return bool(re.match(r"^\d{8,12}:[A-Za-z0-9_-]{30,}$", token.strip()))

    async def start_worker(self, user_id: int, token: str) -> Tuple[bool, str]:
        token = token.strip()
        if not self.is_valid_token(token):
            return False, "Неверный формат токена Telegram! Пример: <code>123456789:ABCdefGHIjklMNOpqrSTUvwxYZ</code>"

        # Останавливаем предыдущего воркера, если он уже запущен
        await self.stop_worker(user_id, remove_from_db=False)

        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            bot_info = await bot.get_me()
        except Exception as e:
            await bot.session.close()
            logger.warning(f"Failed to verify worker token for user {user_id}: {e}")
            return False, f"Telegram отклонил токен бота ({e}). Проверьте токен в @BotFather."

        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.delete_my_commands()
        except Exception:
            pass

        # Сохраняем в базу данных
        await db.save_worker_bot(
            user_id=user_id,
            bot_token=token,
            bot_id=bot_info.id,
            bot_username=bot_info.username or ""
        )

        # Запускаем поллинг
        task = asyncio.create_task(self._poll_worker(user_id, bot, bot_info.username or "bot"))
        self.active_tasks[user_id] = task
        self.active_bots[user_id] = bot
        logger.info(f"Worker bot @{bot_info.username} started for user {user_id}")
        return True, bot_info.username or "bot"

    async def _poll_worker(self, user_id: int, bot: Bot, username: str):
        try:
            logger.info(f"Starting polling for worker @{username} (user {user_id})...")
            await self.worker_dp.start_polling(
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
                    "inline_query",
                    "chosen_inline_result"
                ]
            )
        except asyncio.CancelledError:
            logger.info(f"Worker polling cancelled for user {user_id} (@{username})")
        except Exception as e:
            logger.error(f"Error in worker polling for user {user_id} (@{username}): {e}")
        finally:
            try:
                await bot.session.close()
            except Exception:
                pass
            self.active_tasks.pop(user_id, None)
            self.active_bots.pop(user_id, None)

    async def stop_worker(self, user_id: int, remove_from_db: bool = True):
        task = self.active_tasks.pop(user_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        bot = self.active_bots.pop(user_id, None)
        if bot:
            try:
                await bot.session.close()
            except Exception:
                pass
        if remove_from_db:
            await db.delete_worker_bot(user_id)
        logger.info(f"Stopped worker for user {user_id}")

    async def stop_all(self):
        await self.stop_deal_bot()
        user_ids = list(self.active_tasks.keys())
        for uid in user_ids:
            await self.stop_worker(uid, remove_from_db=False)

    async def start_deal_bot(self, token: str) -> Tuple[bool, str]:
        token = (token or "").strip()
        if not self.is_valid_token(token):
            return False, "Неверный формат токена Telegram! Пример: <code>123456789:ABCdefGHIjklMNOpqrSTUvwxYZ</code>"

        await self.stop_deal_bot()

        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            bot_info = await bot.get_me()
        except Exception as e:
            await bot.session.close()
            logger.warning(f"Failed to verify DEAL_BOT token: {e}")
            return False, f"Telegram отклонил токен бота ({e}). Проверьте токен в @BotFather."

        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.delete_my_commands()
        except Exception:
            pass

        config.DEAL_BOT_TOKEN = token
        config.DEAL_BOT_USERNAME = bot_info.username or ""
        config.DEAL_BOT_ID = bot_info.id

        from admin_handlers import update_env_file
        update_env_file("DEAL_BOT_TOKEN", token)
        update_env_file("DEAL_BOT_USERNAME", config.DEAL_BOT_USERNAME)

        self.deal_bot_instance = bot
        self.deal_bot_task = asyncio.create_task(self._poll_deal_bot(bot, config.DEAL_BOT_USERNAME))
        logger.info(f"Dedicated deal bot @{config.DEAL_BOT_USERNAME} started and polling.")
        return True, config.DEAL_BOT_USERNAME

    async def _poll_deal_bot(self, bot: Bot, username: str):
        try:
            logger.info(f"Starting polling for deal bot @{username}...")
            await self.worker_dp.start_polling(
                bot,
                handle_signals=False,
                allowed_updates=["message", "callback_query"]
            )
        except asyncio.CancelledError:
            logger.info(f"Deal bot polling cancelled (@{username})")
        except Exception as e:
            logger.error(f"Error in deal bot polling (@{username}): {e}")
        finally:
            try:
                await bot.session.close()
            except Exception:
                pass
            self.deal_bot_task = None
            self.deal_bot_instance = None

    async def stop_deal_bot(self):
        task = self.deal_bot_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        bot = self.deal_bot_instance
        if bot:
            try:
                await bot.session.close()
            except Exception:
                pass
        self.deal_bot_task = None
        self.deal_bot_instance = None
        logger.info("Deal bot stopped.")

    async def start_all_from_db(self):
        records = await db.get_all_active_worker_bots()
        logger.info(f"Restoring {len(records)} worker bot(s) from database...")
        for rec in records:
            uid = rec["user_id"]
            token = rec["bot_token"]
            # Запускаем только если подписка пользователя активна
            is_active = await db.is_subscription_active(uid)
            if not is_active:
                logger.info(f"Skipping worker for user {uid} (subscription expired)")
                continue
            try:
                ok, res = await self.start_worker(uid, token)
                if not ok:
                    logger.warning(f"Could not restore worker for user {uid}: {res}")
            except Exception as e:
                logger.error(f"Failed to start worker for user {uid}: {e}")

from middlewares import ThrottlingMiddleware
from deal_bot_handlers import deal_router
from worker_handlers import worker_router

worker_dp = Dispatcher()

@worker_dp.update.outer_middleware()
async def log_worker_update_middleware(handler, event, data):
    if event.callback_query:
        logger.info(f"[WORKER CALLBACK] user={event.callback_query.from_user.id}, data='{event.callback_query.data}'")
    elif event.message:
        logger.info(f"[WORKER MESSAGE] chat={event.message.chat.id}, text='{event.message.text}'")
    return await handler(event, data)

worker_dp.message.outer_middleware(ThrottlingMiddleware(limit=0.5))
worker_dp.callback_query.outer_middleware(ThrottlingMiddleware(limit=0.5))
worker_dp.include_router(worker_router)
worker_dp.include_router(deal_router)

worker_manager = WorkerBotManager(worker_dp)
