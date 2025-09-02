from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from typing import Optional, List

from database import Category


# --- CALLBACKS ---

class MasterSearchCallback(CallbackData, prefix="master_search"):
    action: str  # 'show_all', 'by_city'


class MasterListPagination(CallbackData, prefix="master_pag"):
    action: str  # 'prev', 'next'
    page: int
    city: Optional[str] = None


class WorkFilterCallback(CallbackData, prefix="work_filter"):
    action: str
    category_id: Optional[int] = None


class MyWorksPaginationCallback(CallbackData, prefix="my_works_pag"):
    action: str
    work_id: int


class AdminMenuCallback(CallbackData, prefix="admin_menu"):
    action: str


class AdminCategoryCallback(CallbackData, prefix="admin_cat"):
    action: str
    category_id: Optional[int] = None
    category_name: Optional[str] = None


class WorkPaginationCallback(CallbackData, prefix="work_pag"):
    action: str
    current_work_id: int
    category_id: Optional[int] = None


class LikeCallback(CallbackData, prefix="like"):
    action: str
    work_id: int


class ReviewCallback(CallbackData, prefix="review"):
    action: str
    work_id: int


class MainMenuCallback(CallbackData, prefix="main_menu"):
    action: str


class WorkActionCallback(CallbackData, prefix="work_action"):
    action: str
    work_id: int


class PaymentCallback(CallbackData, prefix="payment"):
    action: str
    work_id: int
    invoice_id: int


class MasterCallback(CallbackData, prefix="master"):
    action: str
    master_id: int


class AdminModerationCallback(CallbackData, prefix="admin_mod"):
    action: str
    work_id: int


class AdminUserActionCallback(CallbackData, prefix="admin_user"):
    action: str
    user_id: int


# --- КЛАВИАТУРЫ ---

def get_main_menu_kb(user_role: str = 'client') -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🎨 Просмотр работ"), KeyboardButton(text="👥 Просмотр мастеров"))

    if user_role == 'master':
        builder.row(
            KeyboardButton(text="✍️ Подать свою работу"),
            KeyboardButton(text="📂 Мои работы"),
            KeyboardButton(text="👤 Мой профиль")
        )
    else:
        builder.row(KeyboardButton(text="⭐️ Стать мастером"))

    builder.row(KeyboardButton(text="❓ FAQ"), KeyboardButton(text="📞 Контакты"))
    return builder.as_markup(resize_keyboard=True)


def get_master_search_options_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Показать всех (сортировка по рейтингу)",
            callback_data=MasterSearchCallback(action="show_all").pack()
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔎 Найти по городу",
            callback_data=MasterSearchCallback(action="by_city").pack()
        )
    )
    return builder.as_markup()


def get_master_list_pagination_kb(total_pages: int, current_page: int,
                                  city: Optional[str] = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    prev_page = current_page - 1
    next_page = current_page + 1

    nav_buttons = []
    if current_page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️",
                                 callback_data=MasterListPagination(action="prev", page=prev_page, city=city).pack())
        )

    nav_buttons.append(
        InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="do_nothing")
    )

    if current_page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="➡️",
                                 callback_data=MasterListPagination(action="next", page=next_page, city=city).pack())
        )

    builder.row(*nav_buttons)
    return builder.as_markup()


def get_work_filter_options_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Показать все работы", callback_data=WorkFilterCallback(action="show_all").pack())
    )
    builder.row(
        InlineKeyboardButton(text="Фильтр по стилю 🎨", callback_data=WorkFilterCallback(action="by_style").pack())
    )
    return builder.as_markup()


def get_category_filter_kb(categories: List[Category]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.row(
            InlineKeyboardButton(
                text=category.name,
                callback_data=WorkFilterCallback(action="select_style", category_id=category.id).pack()
            )
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=WorkFilterCallback(action="back_to_options").pack())
    )
    return builder.as_markup()


def get_pagination_kb(
        current_work_id: int,
        master_id: int,
        likes_count: int,
        is_liked: bool,
        category_id: Optional[int] = None
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="⬅️",
            callback_data=WorkPaginationCallback(action="prev", current_work_id=current_work_id,
                                                 category_id=category_id).pack()
        ),
        InlineKeyboardButton(
            text="➡️",
            callback_data=WorkPaginationCallback(action="next", current_work_id=current_work_id,
                                                 category_id=category_id).pack()
        )
    )

    like_text = f"❤️ {likes_count}" if not is_liked else f"💔 {likes_count}"
    builder.row(
        InlineKeyboardButton(
            text=like_text,
            callback_data=LikeCallback(action="toggle", work_id=current_work_id).pack()
        ),
        InlineKeyboardButton(
            text="💬 Оставить отзыв",
            callback_data=ReviewCallback(action="create", work_id=current_work_id).pack()
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="👤 Профиль мастера",
            callback_data=MasterCallback(action="view", master_id=master_id).pack()
        )
    )
    return builder.as_markup()


def get_my_works_pagination_kb(work_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️", callback_data=MyWorksPaginationCallback(action="prev", work_id=work_id).pack()),
        InlineKeyboardButton(text="➡️", callback_data=MyWorksPaginationCallback(action="next", work_id=work_id).pack())
    )
    return builder.as_markup()


def get_admin_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 Управление пользователями",
                             callback_data=AdminMenuCallback(action="user_management").pack()),
        InlineKeyboardButton(text="🎨 Управление работами",
                             callback_data=AdminMenuCallback(action="work_management").pack())
    )
    builder.row(
        InlineKeyboardButton(text="⭐️ Управление отзывами",
                             callback_data=AdminMenuCallback(action="review_management").pack()),
        InlineKeyboardButton(text="💰 Управление оплатами",
                             callback_data=AdminMenuCallback(action="payment_management").pack())
    )
    builder.row(
        InlineKeyboardButton(text="🗂️ Управление категориями",
                             callback_data=AdminMenuCallback(action="category_management").pack()),
        InlineKeyboardButton(text="📊 Статистика", callback_data=AdminMenuCallback(action="statistics").pack())
    )
    builder.row(
        InlineKeyboardButton(text="📤 Рассылка", callback_data=AdminMenuCallback(action="mailing").pack())
    )
    return builder.as_markup()


def get_admin_category_manage_kb(categories: List[Category]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.row(
            InlineKeyboardButton(text=category.name, callback_data="do_nothing"),
            InlineKeyboardButton(
                text="❌ Удалить",
                callback_data=AdminCategoryCallback(action="delete", category_id=category.id,
                                                    category_name=category.name).pack()
            )
        )
    builder.row(
        InlineKeyboardButton(text="➕ Добавить новую категорию",
                             callback_data=AdminCategoryCallback(action="add").pack())
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад в админ-панель", callback_data=AdminMenuCallback(action="main").pack())
    )
    return builder.as_markup()


def get_rating_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    buttons = [InlineKeyboardButton(text=f"{i} ⭐", callback_data=f"rating_{i}") for i in range(1, 6)]
    builder.row(*buttons)
    return builder.as_markup()


def get_payment_kb(pay_url: str, work_id: int, invoice_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💸 Оплатить через Crypto Bot", url=pay_url))
    builder.row(InlineKeyboardButton(
        text="✅ Проверить оплату",
        callback_data=PaymentCallback(action="check_payment", work_id=work_id, invoice_id=invoice_id).pack()
    ))
    return builder.as_markup()


def get_admin_moderation_kb(work_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Одобрить",
            callback_data=AdminModerationCallback(action="approve", work_id=work_id).pack()
        ),
        InlineKeyboardButton(
            text="❌ Отклонить",
            callback_data=AdminModerationCallback(action="reject", work_id=work_id).pack()
        )
    )
    return builder.as_markup()


def get_admin_user_manage_kb(user_id: int, is_active: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_active:
        builder.row(
            InlineKeyboardButton(
                text="🚫 Заблокировать",
                callback_data=AdminUserActionCallback(action="block", user_id=user_id).pack()
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="✅ Разблокировать",
                callback_data=AdminUserActionCallback(action="unblock", user_id=user_id).pack()
            )
        )
    return builder.as_markup()


def get_master_profile_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ Редактировать профиль", callback_data="edit_master_profile"))
    return builder.as_markup()
