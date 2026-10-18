import time
import logging
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, CallbackQuery, Message

logger = logging.getLogger("nft_bot.throttling")

class ThrottlingMiddleware(BaseMiddleware):
    """
    Защита от флуда, кликеров и DDoS-атак.
    Ограничивает частоту запросов от одного пользователя.
    """
    def __init__(self, limit: float = 0.5):
        self.limit = limit
        self.user_timestamps: dict[int, float] = {}

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = getattr(event, "from_user", None)
        if user:
            user_id = user.id
            now = time.monotonic()
            last_time = self.user_timestamps.get(user_id, 0)

            if now - last_time < self.limit:
                # Anti-flood trigger
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer("⚠️ Слишком много нажатий. Подождите секунду.", show_alert=False)
                    except Exception:
                        pass
                elif isinstance(event, Message):
                    # Silently ignore rapid message spam to prevent bot from hanging
                    pass
                return None

            self.user_timestamps[user_id] = now

            # Периодическая очистка кэша меток времени для экономии памяти
            if len(self.user_timestamps) > 10000:
                cutoff = now - 60
                self.user_timestamps = {uid: t for uid, t in self.user_timestamps.items() if t > cutoff}

        return await handler(event, data)
