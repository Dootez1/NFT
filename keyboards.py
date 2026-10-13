from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import SUB_STANDARD_PRICE, SUB_PRO_PRICE

def get_screen1_keyboard(deal_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура Экрана 1 (Скриншот 1):
    [ ✅ Принять ]  [ ❎ Отклонить ]
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{deal_id}"),
            InlineKeyboardButton(text="❎ Отклонить", callback_data=f"decline:{deal_id}")
        ]
    ])

def get_screen2_keyboard(nft_url: str, deal_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура Экрана 2 (Скриншот 2):
    [ Отправить подарок... ↗ ]  [ ✅ Подарок отправлен ]
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Отправить подарок... ↗", url=nft_url),
            InlineKeyboardButton(text="✅ Подарок отправлен", callback_data=f"sent:{deal_id}")
        ]
    ])

def get_screen3_buyer_keyboard(deal_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура подтверждения покупателем (Скриншот 3):
    [ ✅ Подтвердить получение ]
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить получение", callback_data=f"confirm:{deal_id}")
        ]
    ])

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Главное меню бота с профилем, тарифами и реферальной системой
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile"),
            InlineKeyboardButton(text="⭐️ Тарифы и подписка", callback_data="menu_sub")
        ],
        [
            InlineKeyboardButton(text="👥 Рефералы (+6ч)", callback_data="menu_referral")
        ],
        [
            InlineKeyboardButton(text="📖 Как пользоваться (.buy)", callback_data="menu_guide"),
            InlineKeyboardButton(text="💼 Telegram Business", callback_data="menu_business")
        ],
        [
            InlineKeyboardButton(text="❓ Частые вопросы", callback_data="menu_faq")
        ]
    ])

def get_profile_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура страницы профиля
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐️ Тарифы и подписка", callback_data="menu_sub"),
            InlineKeyboardButton(text="👥 Рефералы", callback_data="menu_referral")
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
        ]
    ])

def get_sub_menu_keyboard(current_plan: str | None = None) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора тарифов
    """
    kb = [
        [
            InlineKeyboardButton(
                text=f"⭐️ Стандарт ({SUB_STANDARD_PRICE} Stars / 30 дн)",
                callback_data="pay_sub:standard"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"💎 PRO Инлайн ({SUB_PRO_PRICE} Stars / 30 дн)",
                callback_data="pay_sub:pro"
            )
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_deals_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Обновить список", callback_data="menu_deals")
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
        ]
    ])

def get_referral_keyboard(bot_username: str, user_id: int) -> InlineKeyboardMarkup:
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    share_url = f"https://t.me/share/url?url={ref_link}&text=Создавай%20офферы%20NFT%20подарков%20в%20Telegram!"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="↗️ Поделиться ссылкой", url=share_url)
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
        ]
    ])

def get_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
        ]
    ])

def get_buy_sub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"⭐️ Стандарт ({SUB_STANDARD_PRICE} Stars)",
                callback_data="pay_sub:standard"
            ),
            InlineKeyboardButton(
                text=f"💎 PRO ({SUB_PRO_PRICE} Stars)",
                callback_data="pay_sub:pro"
            )
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
        ]
    ])
