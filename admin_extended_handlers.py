# admin_extended_handlers.py

import asyncio
import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, delete, desc, asc, func
from sqlalchemy.ext.asyncio import AsyncSession

from admin_handlers import IsAdmin
from database import Category, Review, User, MasterProfile, TattooWork, BotSettings, get_setting
from keyboards import (get_admin_category_manage_kb, AdminMenuCallback,
                       AdminCategoryCallback, get_admin_main_kb, AdminReviewCallback,
                       get_admin_review_keyboard, get_admin_stats_kb,
                       AdminMailingCallback, get_admin_mailing_confirm_kb,
                       AdminPaymentCallback, get_admin_payment_keyboard)  # Добавили импорты
from states import AdminCategoryManagement, AdminReviewManagement, AdminMailing, AdminSettingsManagement

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# --- ОБРАБОТКА ГЛАВНОГО МЕНЮ АДМИНКИ ---

@router.callback_query(AdminMenuCallback.filter(F.action == "main"))
async def back_to_main_admin_menu(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text(
        "Добро пожаловать в админ-панель!",
        reply_markup=get_admin_main_kb()
    )


@router.callback_query(AdminMenuCallback.filter(F.action == "work_management"))
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


# --- УПРАВЛЕНИЕ ОТЗЫВАМИ ---

async def get_review_info_text(review: Review, session: AsyncSession) -> str:
    client = await session.get(User, review.client_id)
    master_profile = await session.get(MasterProfile, review.master_id)
    master_user = await session.get(User, master_profile.user_id)
    rating_stars = "⭐" * review.rating + "☆" * (5 - review.rating)
    return (
        f"<b>Отзыв #{review.id}</b>\n\n"
        f"<b>Клиент:</b> @{client.username} (ID: <code>{client.telegram_id}</code>)\n"
        f"<b>Мастер:</b> @{master_user.username} (ID: <code>{master_user.telegram_id}</code>)\n"
        f"<b>Работа ID:</b> {review.work_id}\n"
        f"<b>Оценка:</b> {rating_stars}\n\n"
        f"<b>Текст:</b>\n<i>{review.text}</i>\n\n"
        f"<b>Ответ администратора:</b>\n<i>{review.admin_reply or 'Пока нет ответа.'}</i>"
    )


async def show_review_for_admin(query: CallbackQuery, session: AsyncSession, review_id: int = None,
                                direction: str = 'first'):
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

    master_user = None  # Initialize master_user to None
    try:
        master_profile = await session.get(MasterProfile, review.master_id)
        if master_profile:
            master_user = await session.get(User, master_profile.user_id)
            if master_user:
                await message.bot.send_message(
                    master_user.telegram_id,
                    f"Администратор ответил на отзыв #{review.id}:\n\n<i>{reply_text}</i>"
                )
    except Exception as e:
        user_id_for_log = master_user.telegram_id if master_user else "unknown"
        logging.error(f"Не удалось отправить уведомление мастеру {user_id_for_log}: {e}")


# --- СТАТИСТИКА ---

@router.callback_query(AdminMenuCallback.filter(F.action == "statistics"))
async def show_statistics(query: CallbackQuery, session: AsyncSession):
    total_users = await session.scalar(select(func.count(User.id)))
    total_masters = await session.scalar(select(func.count(User.id)).where(User.role == 'master'))
    total_clients = await session.scalar(select(func.count(User.id)).where(User.role == 'client'))
    total_works = await session.scalar(select(func.count(TattooWork.id)))
    published_works = await session.scalar(select(func.count(TattooWork.id)).where(TattooWork.status == 'published'))
    pending_works = await session.scalar(
        select(func.count(TattooWork.id)).where(TattooWork.status == 'pending_approval'))
    rejected_works = await session.scalar(select(func.count(TattooWork.id)).where(TattooWork.status == 'rejected'))
    total_reviews = await session.scalar(select(func.count(Review.id)))
    stats_text = (
        "📊 <b>Статистика Маркетплейса</b>\n\n"
        "👥 <b>Пользователи:</b>\n"
        f"  - Всего: <b>{total_users}</b>\n"
        f"  - Мастеров: <b>{total_masters}</b>\n"
        f"  - Клиентов: <b>{total_clients}</b>\n\n"
        "🎨 <b>Работы:</b>\n"
        f"  - Всего загружено: <b>{total_works}</b>\n"
        f"  - Опубликовано: <b>{published_works}</b>\n"
        f"  - На модерации: <b>{pending_works}</b>\n"
        f"  - Отклонено: <b>{rejected_works}</b>\n\n"
        "⭐️ <b>Отзывы:</b>\n"
        f"  - Всего оставлено: <b>{total_reviews}</b>"
    )
    await query.message.edit_text(stats_text, reply_markup=get_admin_stats_kb())
    await query.answer()


# --- РАССЫЛКА ---

@router.callback_query(AdminMenuCallback.filter(F.action == "mailing"))
async def start_mailing(query: CallbackQuery, state: FSMContext):
    await state.set_state(AdminMailing.waiting_for_message_content)
    await query.message.edit_text(
        "Введите сообщение для рассылки.\n"
        "Оно будет отправлено <b>всем</b> пользователям бота.\n\n"
        "Вы можете использовать HTML-теги для форматирования."
    )
    await query.answer()


@router.message(AdminMailing.waiting_for_message_content)
async def mailing_content_received(message: Message, state: FSMContext):
    await state.update_data(text=message.html_text)
    await state.set_state(AdminMailing.waiting_for_confirmation)
    await message.answer(
        "<b>Предпросмотр сообщения:</b>\n\n"
        f"{message.html_text}\n\n"
        "Отправляем?",
        reply_markup=get_admin_mailing_confirm_kb()
    )


@router.callback_query(AdminMailing.waiting_for_confirmation, AdminMailingCallback.filter(F.action == "cancel"))
async def cancel_mailing(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text("Рассылка отменена.", reply_markup=None)
    await query.answer()


@router.callback_query(AdminMailing.waiting_for_confirmation, AdminMailingCallback.filter(F.action == "send"))
async def process_mailing(query: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    text = data.get("text")
    await state.clear()
    await query.message.edit_text("⏳ Начинаю рассылку...", reply_markup=None)
    users_result = await session.execute(select(User.telegram_id))
    user_ids = users_result.scalars().all()
    successful_sends = 0
    failed_sends = 0
    for user_id in user_ids:
        try:
            await query.bot.send_message(chat_id=user_id, text=text, disable_web_page_preview=True)
            successful_sends += 1
        except Exception as e:
            failed_sends += 1
            logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        await asyncio.sleep(0.1)
    await query.message.answer(
        "✅ <b>Рассылка завершена.</b>\n\n"
        f"Успешно отправлено: <b>{successful_sends}</b>\n"
        f"Ошибок: <b>{failed_sends}</b>"
    )


# --- НОВЫЙ БЛОК: УПРАВЛЕНИЕ ПЛАТЕЖАМИ ---

async def get_payment_info_text(work: TattooWork, session: AsyncSession) -> str:
    master_profile = await session.get(MasterProfile, work.master_id)
    master_user = await session.get(User, master_profile.user_id)

    return (
        f"🧾 <b>Платеж за работу #{work.id}</b>\n\n"
        f"<b>Мастер:</b> @{master_user.username} (ID: <code>{master_user.telegram_id}</code>)\n"
        f"<b>Invoice ID:</b> <code>{work.invoice_id}</code>\n"
        f"<b>Сумма:</b> {int(work.price)} руб.\n"
        f"<b>Дата:</b> {work.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"<b>Текущий статус работы:</b> {work.status}"
    )


async def show_payment_for_admin(query: CallbackQuery, session: AsyncSession, work_id: int = None,
                                 direction: str = 'first'):
    stmt = None
    paid_statuses = ['pending_approval', 'published', 'rejected']

    if direction == 'first':
        stmt = select(TattooWork).where(TattooWork.status.in_(paid_statuses)).order_by(desc(TattooWork.id)).limit(1)
    elif direction == 'next':
        stmt = select(TattooWork).where(TattooWork.id < work_id, TattooWork.status.in_(paid_statuses)).order_by(
            desc(TattooWork.id)).limit(1)
    elif direction == 'prev':
        stmt = select(TattooWork).where(TattooWork.id > work_id, TattooWork.status.in_(paid_statuses)).order_by(
            asc(TattooWork.id)).limit(1)

    work = await session.scalar(stmt)

    if not work:
        if direction == 'first':
            await query.message.edit_text("Проведенных платежей пока нет.")
        else:
            await query.answer("Это крайний платеж в списке.", show_alert=True)
        return

    text = await get_payment_info_text(work, session)
    keyboard = get_admin_payment_keyboard(work.id)
    await query.message.edit_text(text, reply_markup=keyboard)
    await query.answer()


@router.callback_query(AdminMenuCallback.filter(F.action == "payment_management"))
async def start_payment_management(query: CallbackQuery, session: AsyncSession):
    await show_payment_for_admin(query, session, direction='first')


@router.callback_query(AdminPaymentCallback.filter(F.action.in_(['prev', 'next'])))
async def paginate_payments(query: CallbackQuery, callback_data: AdminPaymentCallback, session: AsyncSession):
    await show_payment_for_admin(query, session, work_id=callback_data.work_id, direction=callback_data.action)


# --- НОВЫЙ БЛОК: УПРАВЛЕНИЕ НАСТРОЙКАМИ ---

@router.callback_query(AdminMenuCallback.filter(F.action == "settings"))
async def show_settings(query: CallbackQuery, session: AsyncSession):
    master_price = await get_setting(session, 'master_price', '0')
    await query.message.edit_text(
        "⚙️ Настройки бота",
        reply_markup=get_admin_settings_kb(master_price)
    )


@router.callback_query(F.data == "set_master_price")
async def start_set_master_price(query: CallbackQuery, state: FSMContext):
    await state.set_state(AdminSettingsManagement.waiting_for_master_price)
    await query.message.edit_text(
        "Введите новую цену в USDT за получение статуса мастера (например: 10). Введите 0, чтобы сделать регистрацию бесплатной.")
    await query.answer()


@router.message(AdminSettingsManagement.waiting_for_master_price, F.text)
async def process_new_master_price(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите целое число.")
        return

    new_price = message.text

    setting = await session.get(BotSettings, 'master_price')
    if setting:
        setting.value = new_price
    else:
        session.add(BotSettings(key='master_price', value=new_price))

    await session.commit()
    await state.clear()

    await message.answer(f"✅ Цена за статус мастера установлена: {new_price} USDT.")

    # Возвращаемся в меню настроек
    master_price = await get_setting(session, 'master_price', '0')
    await message.answer(
        "⚙️ Настройки бота",
        reply_markup=get_admin_settings_kb(master_price)
    )
