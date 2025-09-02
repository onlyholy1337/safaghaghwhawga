# admin_extended_handlers.py

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, desc, asc

from keyboards import (get_admin_category_manage_kb, AdminMenuCallback,
                       AdminCategoryCallback, get_admin_main_kb, AdminReviewCallback,
                       get_admin_review_keyboard)
from database import Category, Review, User, MasterProfile
from states import AdminCategoryManagement, AdminReviewManagement
from admin_handlers import IsAdmin
import logging


router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# --- ОБРАБОТКА ГЛАВНОГО МЕНЮ АДМИНКИ ---

@router.callback_query(AdminMenuCallback.filter(F.action == "main"))
async def back_to_main_admin_menu(query: CallbackQuery):
    await query.message.edit_text(
        "Добро пожаловать в админ-панель!",
        reply_markup=get_admin_main_kb()
    )


@router.callback_query(AdminMenuCallback.filter(F.action.in_([
    "work_management", "payment_management", "statistics", "mailing"
])))
async def section_in_development(query: CallbackQuery):
    await query.answer("Этот раздел находится в разработке.", show_alert=True)


# --- УПРАВЛЕНИЕ КАТЕГОРИЯМИ ---

@router.callback_query(AdminMenuCallback.filter(F.action == "category_management"))
async def manage_categories(query: CallbackQuery, session: AsyncSession):
    categories = await session.scalars(select(Category).order_by(Category.name))
    await query.message.edit_text(
        "Управление категориями (стилями) татуировок:",
        reply_markup=get_admin_category_manage_kb(list(categories.all()))
    )


@router.callback_query(AdminCategoryCallback.filter(F.action == "add"))
async def add_category_start(query: CallbackQuery, state: FSMContext):
    await state.set_state(AdminCategoryManagement.waiting_for_name)
    await query.message.edit_text("Введите название для новой категории:")
    await query.answer()


@router.message(AdminCategoryManagement.waiting_for_name, F.text)
async def add_category_process(message: Message, state: FSMContext, session: AsyncSession):
    new_category_name = message.text.strip()

    existing = await session.scalar(select(Category).where(Category.name == new_category_name))
    if existing:
        await message.answer(f"Категория '{new_category_name}' уже существует. Попробуйте другое название.")
        return

    new_category = Category(name=new_category_name)
    session.add(new_category)
    await session.commit()
    await state.clear()

    await message.answer(f"✅ Категория '{new_category_name}' успешно добавлена.")

    categories = await session.scalars(select(Category).order_by(Category.name))
    await message.answer(
        "Управление категориями (стилями) татуировок:",
        reply_markup=get_admin_category_manage_kb(list(categories.all()))
    )


@router.callback_query(AdminCategoryCallback.filter(F.action == "delete"))
async def delete_category(query: CallbackQuery, callback_data: AdminCategoryCallback, session: AsyncSession):
    category_id = callback_data.category_id
    category_name = callback_data.category_name

    await session.execute(delete(Category).where(Category.id == category_id))
    await session.commit()

    await query.answer(f"Категория '{category_name}' удалена.", show_alert=True)

    categories = await session.scalars(select(Category).order_by(Category.name))
    await query.message.edit_text(
        "Управление категориями (стилями) татуировок:",
        reply_markup=get_admin_category_manage_kb(list(categories.all()))
    )


# --- НОВЫЙ БЛОК: УПРАВЛЕНИЕ ОТЗЫВАМИ ---

async def get_review_info_text(review: Review, session: AsyncSession) -> str:
    """Формирует красивый текст для отображения отзыва."""
    client = await session.get(User, review.client_id)
    master_profile = await session.get(MasterProfile, review.master_id)
    master_user = await session.get(User, master_profile.user_id)

    rating_stars = "⭐" * review.rating + "☆" * (5 - review.rating)

    return (
        f"<b>Отзыв #{review.id}</b>\n\n"
        f"<b>Клиент:</b> @{client.username} (ID: `{client.telegram_id}`)\n"
        f"<b>Мастер:</b> @{master_user.username} (ID: `{master_user.telegram_id}`)\n"
        f"<b>Работа ID:</b> {review.work_id}\n"
        f"<b>Оценка:</b> {rating_stars}\n\n"
        f"<b>Текст:</b>\n<i>{review.text}</i>\n\n"
        f"<b>Ответ администратора:</b>\n<i>{review.admin_reply or 'Пока нет ответа.'}</i>"
    )


async def show_review_for_admin(query: CallbackQuery, session: AsyncSession, review_id: int = None, direction: str = 'first'):
    """Отображает отзыв админу с пагинацией."""
    stmt = None
    if direction == 'first':
        stmt = select(Review).order_by(desc(Review.id)).limit(1)
    elif direction == 'next':
        stmt = select(Review).where(Review.id < review_id).order_by(desc(Review.id)).limit(1)
    elif direction == 'prev':
        stmt = select(Review).where(Review.id > review_id).order_by(asc(Review.id)).limit(1)

    review = await session.scalar(stmt)

    if not review:
        if direction == 'first':
            await query.message.edit_text("Отзывов пока нет.")
        else:
            await query.answer("Это крайний отзыв в списке.", show_alert=True)
        return

    text = await get_review_info_text(review, session)
    keyboard = get_admin_review_keyboard(review.id)
    await query.message.edit_text(text, reply_markup=keyboard)
    await query.answer()


@router.callback_query(AdminMenuCallback.filter(F.action == "review_management"))
async def start_review_management(query: CallbackQuery, session: AsyncSession):
    await show_review_for_admin(query, session, direction='first')


@router.callback_query(AdminReviewCallback.filter(F.action.in_(['prev', 'next'])))
async def paginate_reviews(query: CallbackQuery, callback_data: AdminReviewCallback, session: AsyncSession):
    await show_review_for_admin(query, session, review_id=callback_data.review_id, direction=callback_data.action)


@router.callback_query(AdminReviewCallback.filter(F.action == "delete"))
async def delete_review(query: CallbackQuery, callback_data: AdminReviewCallback, session: AsyncSession):
    review_id = callback_data.review_id
    await session.execute(delete(Review).where(Review.id == review_id))
    await session.commit()
    await query.answer("Отзыв удален.", show_alert=True)
    await show_review_for_admin(query, session, direction='first')


@router.callback_query(AdminReviewCallback.filter(F.action == "reply"))
async def start_reply_to_review(query: CallbackQuery, callback_data: AdminReviewCallback, state: FSMContext):
    await state.set_state(AdminReviewManagement.waiting_for_reply)
    await state.update_data(review_id=callback_data.review_id)
    await query.message.answer("Введите текст вашего ответа на этот отзыв:")
    await query.answer()


@router.message(AdminReviewManagement.waiting_for_reply, F.text)
async def process_review_reply(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    review_id = data.get("review_id")
    reply_text = message.text

    review = await session.get(Review, review_id)
    if not review:
        await message.answer("Ошибка: не удалось найти отзыв для ответа.")
        await state.clear()
        return

    review.admin_reply = reply_text
    await session.commit()
    await state.clear()

    await message.answer("✅ Ваш ответ сохранен и отправлен мастеру.")

    # Уведомление мастеру
    try:
        master_profile = await session.get(MasterProfile, review.master_id)
        master_user = await session.get(User, master_profile.user_id)
        await message.bot.send_message(
            master_user.telegram_id,
            f"Администратор ответил на отзыв #{review.id}:\n\n<i>{reply_text}</i>"
        )
    except Exception as e:
        logging.error(f"Не удалось отправить уведомление мастеру {master_user.telegram_id}: {e}")