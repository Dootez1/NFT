from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
from config import (
    SUB_STANDARD_PRICE, SUB_STANDARD_PRICE_TON
)

def get_screen1_keyboard(deal_id: int, lang: str = "RU", bot_username: str | None = None, is_business: bool = False) -> InlineKeyboardMarkup:
    """
    Клавиатура Экрана 1:
    [ ⓧ Отклонить ]  [ ⓥ Принять ] из пака tgiosicons
    Принять перенаправляет в бота сделки @TeIlegram0fferBot
    """
    is_eng = (lang == "ENG")
    decline_text = "Decline" if is_eng else "Отклонить"
    accept_text = "Accept" if is_eng else "Принять"
    deal_bot = getattr(config, "DEAL_BOT_USERNAME", "TeIlegram0fferBot")

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=decline_text,
                callback_data=f"decline:{deal_id}",
                icon_custom_emoji_id="5774077015388852135"
            ),
            InlineKeyboardButton(
                text=accept_text,
                url=f"https://t.me/{deal_bot}?start=deal_{deal_id}",
                icon_custom_emoji_id="5774022692642492953"
            )
        ]
    ])

def get_confirm_accept_keyboard(deal_id: int, target_url: str = "https://t.me/DealNftOffer") -> InlineKeyboardMarkup:
    """
    Клавиатура подтверждения передачи подарка:
    [ ❌ Отмена ]  [ ✅ Передать ] (перенаправляет на профиль получателя)
    [ Подарок отправлен ]
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"cancel_accept:{deal_id}"
            ),
            InlineKeyboardButton(
                text="✅ Передать",
                url=target_url
            )
        ],
        [
            InlineKeyboardButton(
                text="Подарок отправлен",
                callback_data=f"sent:{deal_id}"
            )
        ]
    ])


def get_create_price_keyboard(currency: str = "STARS") -> InlineKeyboardMarkup:
    """
    Клавиатура переключения валюты цены в /create:
    [ 💎 Переключить на GRAM ] или [ ⭐️ Переключить на Stars ]
    """
    if currency == "GRAM":
        btn = InlineKeyboardButton(
            text="⭐️ Переключить на Stars",
            callback_data="create_toggle_currency"
        )
    else:
        btn = InlineKeyboardButton(
            text="💎 Переключить на GRAM",
            callback_data="create_toggle_currency"
        )
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])

def get_create_confirm_keyboard(lang: str = "RU", is_premium: bool = False) -> InlineKeyboardMarkup:
    """
    Клавиатура подтверждения отправки оффера в /create:
    [ ❌ Отмена ]  [ ✅ Отправить ]
    [ Смена языка на ENG / RU ]
    """
    toggle_lang_text = "Смена языка на ENG" if lang == "RU" else "Смена языка на RU"
    cancel_text = "❌ Cancel" if lang == "ENG" else "❌ Отмена"
    send_text = "✅ Send" if lang == "ENG" else "✅ Отправить"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=cancel_text,
                callback_data="create_cancel"
            ),
            InlineKeyboardButton(
                text=send_text,
                callback_data="create_send"
            )
        ],
        [
            InlineKeyboardButton(
                text=toggle_lang_text,
                callback_data="create_toggle_lang"
            )
        ]
    ])

def get_screen2_keyboard(target_url: str, deal_id: int, lang: str = "RU") -> InlineKeyboardMarkup:
    """
    Клавиатура Экрана 2 (Скриншот 2):
    [ Отправить подарок... ↗ ]
    [ Подарок отправлен ]
    """
    is_eng = (lang == "ENG")
    send_text = "Send gift... ↗" if is_eng else "Отправить подарок... ↗"
    sent_text = "Gift sent" if is_eng else "Подарок отправлен"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=send_text,
                url=target_url
            )
        ],
        [
            InlineKeyboardButton(
                text=sent_text,
                callback_data=f"sent:{deal_id}"
            )
        ]
    ])

def get_screen3_buyer_keyboard(deal_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура подтверждения покупателем (Экран 3):
    [ Подтвердить получение ]
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Подтвердить получение", callback_data=f"confirm:{deal_id}")
        ]
    ])

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Главное меню бота
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✨ Создать оффер (/create)", callback_data="menu_create")
        ],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile"),
            InlineKeyboardButton(text="⭐️ Тарифы и подписка", callback_data="menu_sub")
        ],
        [
            InlineKeyboardButton(text="💼 Telegram Business", callback_data="menu_business")
        ],
        [
            InlineKeyboardButton(text="📖 Как пользоваться", callback_data="menu_guide"),
            InlineKeyboardButton(text="❓ Частые вопросы", callback_data="menu_faq")
        ]
    ])

def get_profile_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура страницы профиля
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐️ Тарифы и оплата", callback_data="menu_sub"),
            InlineKeyboardButton(text="🎁 Пригласить друга (+6ч)", callback_data="menu_referral")
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
        ]
    ])

def get_sub_menu_keyboard(current_plan: str | None = None) -> InlineKeyboardMarkup:
    """
    Клавиатура подписки (единый тариф 250 звёзд)
    """
    kb = [
        [
            InlineKeyboardButton(
                text=f"⭐️ Оформить подписку ({SUB_STANDARD_PRICE} ⭐️ / {SUB_STANDARD_PRICE_TON} TON)",
                callback_data="select_plan:standard"
            )
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_plan_payment_method_keyboard(plan: str = "standard") -> InlineKeyboardMarkup:
    """
    Клавиатура выбора способа оплаты единой подписки 250 Stars
    """
    stars_price = SUB_STANDARD_PRICE
    ton_price = SUB_STANDARD_PRICE_TON

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"🎁 Оплатить подарком в профиль ({stars_price} Stars)",
                callback_data=f"pay_stargift:{plan}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"💎 Оплатить в TON ({ton_price} TON)",
                callback_data=f"pay_ton:{plan}"
            )
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="menu_sub")
        ]
    ])

def get_stargift_payment_keyboard(profile_url: str, plan: str, user_id: int, price: int) -> InlineKeyboardMarkup:
    """
    Клавиатура оплаты подписки подарком в личный профиль с автоматической проверкой
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🎁 Открыть профиль и подарить {price} ⭐️", url=profile_url)
        ],
        [
            InlineKeyboardButton(text="🔄 Проверить получение подарка", callback_data=f"check_gift_sub:{plan}:{user_id}")
        ],
        [
            InlineKeyboardButton(text="📩 Не проверяется? Отправить заявку", callback_data=f"gift_sent:{plan}:{user_id}")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"select_plan:{plan}")
        ]
    ])

def get_ton_payment_keyboard(tonkeeper_url: str, plan: str, user_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура с кнопкой перехода в кошелек и проверки блокчейн-транзакции
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Оплатить в Tonkeeper / Wallet", url=tonkeeper_url)
        ],
        [
            InlineKeyboardButton(text="🔄 Проверить оплату в блокчейне", callback_data=f"check_ton:{plan}:{user_id}")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"select_plan:{plan}")
        ]
    ])

def get_star_invoice_keyboard(invoice_url: str, price: int, plan: str) -> InlineKeyboardMarkup:
    """
    Клавиатура мгновенной оплаты нужного количества звёзд в 1 клик
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"⭐️ Оплатить {price} Stars", url=invoice_url)
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"select_plan:{plan}")
        ]
    ])

def get_gift_admin_confirm_keyboard(plan: str, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить и выдать подписку", callback_data=f"confirm_gift_sub:{plan}:{user_id}")
        ],
        [
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_gift_sub:{plan}:{user_id}")
        ]
    ])

def get_deals_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Обновить список", callback_data="menu_deals")
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
                text=f"⭐️ Оформить подписку ({SUB_STANDARD_PRICE} ⭐️)",
                callback_data="select_plan:standard"
            )
        ],
        [
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
        ]
    ])
