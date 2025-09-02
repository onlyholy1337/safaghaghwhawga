from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, asc, desc
from sqlalchemy.orm import selectinload
import logging

from states import WorkSubmission, MasterProfileEdit, MasterReviewReply # Добавили MasterReviewReply
from crypto_api import CryptoAPI
from config import settings
from keyboards import (get_payment_kb, get_main_menu_kb, PaymentCallback, get_admin_moderation_kb,
                       get_master_profile_kb, MyWorksPaginationCallback, get_my_works_pagination_kb,
                       get_master_profile_edit_kb, MasterProfileEditCallback, get_master_review_keyboard,
                       MasterReviewCallback) # Добавили get_master_review_keyboard и MasterReviewCallback
from database import TattooWork, User, MasterProfile, Category, Review # Добавили Review


router = Router()
crypto_api = CryptoAPI(token=settings.crypto_api_token.get_secret_value())

# Словарь для статусов
STATUS_TRANSLATE = {
    'pending_payment': 'Ожидает оплаты',
    'pending_approval': 'На модерации',
    'published': '✅ Опубликована',
    'rejected': '❌ Отклонена'
}


@router.message(F.text == "✍️ Подать свою работу")
async def submit_work_start(message: Message, state: FSMContext, session: AsyncSession):
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user or user.role != 'master':
        await message.answer("Эта функция доступна только для зарегистрированных мастеров.")
        return

    categories_exist = await session.scalar(select(Category).limit(1))
    if not categories_exist:
        await message.answer(
            "В данный момент не добавлено ни одной категории (стиля) для работ. Пожалуйста, обратитесь к администратору.")
        return

    await state.set_state(WorkSubmission.waiting_for_photo)
    await message.answer("Отлично! Пришлите фотографию вашей лучшей работы.", reply_markup=types.ReplyKeyboardRemove())


@router.message(WorkSubmission.waiting_for_photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await state.set_state(WorkSubmission.waiting_for_description)
    await message.answer("Фото принято! Теперь введите описание работы (идея, размер и т.д.).")


@router.message(WorkSubmission.waiting_for_description, F.text)
async def process_work_description(message: Message, state: FSMContext, session: AsyncSession):
    await state.update_data(description=message.text)
    await state.set_state(WorkSubmission.waiting_for_style)

    categories = await session.scalars(select(Category).order_by(Category.name))

    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.row(InlineKeyboardButton(text=cat.name, callback_data=f"style_{cat.id}"))

    await message.answer("Описание принято. Теперь выберите стиль татуировки из списка:",
                         reply_markup=builder.as_markup())


@router.callback_query(WorkSubmission.waiting_for_style, F.data.startswith("style_"))
async def process_style_choice(query: CallbackQuery, state: FSMContext):
    category_id = int(query.data.split("_")[1])
    await state.update_data(category_id=category_id)
    await state.set_state(WorkSubmission.waiting_for_price)

    await query.message.delete()
    await query.message.answer(
        "Стиль принят. Укажите примерную цену самой татуировки для клиента (только число, например: 15000)."
    )
    await query.answer()


@router.message(WorkSubmission.waiting_for_price, F.text)
async def process_price(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите цену только цифрами.")
        return

    await state.update_data(price=int(message.text))
    user_data = await state.get_data()

    placement_price = 1  # Цена за размещение
    invoice = await crypto_api.create_invoice(asset="USDT", amount=placement_price)

    if invoice:
        master_profile = await session.scalar(
            select(MasterProfile).join(User).where(User.telegram_id == message.from_user.id)
        )

        if not master_profile:
            await message.answer("Произошла ошибка: не найден ваш профиль мастера.")
            await state.clear()
            return

        new_work = TattooWork(
            master_id=master_profile.id,
            image_file_id=user_data.get("photo_file_id"),
            description=user_data.get("description"),
            category_id=user_data.get("category_id"),
            price=user_data.get("price"),
            status='pending_payment',
            invoice_id=invoice['invoice_id']
        )
        session.add(new_work)
        await session.commit()
        await session.refresh(new_work) # Обновляем объект, чтобы получить его id

        await message.answer(
            f"Ваша работа почти добавлена! Осталось оплатить размещение.\n\nСумма: {placement_price} USDT",
            reply_markup=get_payment_kb(
                pay_url=invoice['pay_url'],
                work_id=new_work.id,
                invoice_id=new_work.invoice_id
            )
        )
        await state.set_state(WorkSubmission.waiting_for_payment_check)
    else:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        await message.answer("Не удалось создать счет для оплаты. Попробуйте позже.",
                             reply_markup=get_main_menu_kb(user.role))
        await state.clear()


@router.callback_query(PaymentCallback.filter(F.action == "check_payment"))
async def check_payment(query: types.CallbackQuery, callback_data: PaymentCallback, state: FSMContext,
                        session: AsyncSession):
    await query.answer("Проверяем оплату...")
    invoices_data = await crypto_api.get_invoices(invoice_ids=[callback_data.invoice_id])

    if invoices_data and invoices_data.get('items'):
        invoice = invoices_data['items'][0]
        if invoice['status'] == 'paid':
            work = await session.get(TattooWork, callback_data.work_id)
            if work and work.status == 'pending_payment':
                work.status = 'pending_approval'
                await session.commit()

                await query.message.edit_text("✅ Оплата прошла успешно! Ваша работа отправлена на модерацию.")

                admin_ids = [int(i) for i in settings.admin_ids.split(',')]
                for admin_id in admin_ids:
                    try:
                        category = await session.get(Category, work.category_id)
                        await query.bot.send_photo(
                            chat_id=admin_id,
                            photo=work.image_file_id,
                            caption=f"Новая работа на модерацию!\n\n"
                                    f"Мастер: @{query.from_user.username}\n"
                                    f"Описание: {work.description}\n"
                                    f"Стиль: {category.name if category else 'Не указан'}\n"
                                    f"Цена: {work.price} руб.",
                            reply_markup=get_admin_moderation_kb(work.id)
                        )
                    except Exception as e:
                        logging.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

                current_user = await session.scalar(select(User).where(User.telegram_id == query.from_user.id))
                await state.clear()
                await query.message.answer("Вы можете добавить еще одну работу или вернуться в главное меню.",
                                           reply_markup=get_main_menu_kb(current_user.role))

            elif work and work.status != 'pending_payment':
                await query.message.edit_text("Эта работа уже была оплачена.")
            else:
                await query.message.answer("Произошла ошибка, работа не найдена.")
        else:
            await query.answer("Оплата еще не поступила. Попробуйте проверить через минуту.", show_alert=True)
    else:
        await query.answer("Не удалось проверить статус оплаты. Попробуйте позже.", show_alert=True)


@router.message(WorkSubmission.waiting_for_photo)
@router.message(WorkSubmission.waiting_for_description)
@router.message(WorkSubmission.waiting_for_price)
async def incorrect_input_during_submission(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == WorkSubmission.waiting_for_photo.state:
        await message.answer("Пожалуйста, отправьте фотографию.")
    else:
        await message.answer("Пожалуйста, отправьте текстовое сообщение, как я просил.")


# --- НОВЫЙ БЛОК: МОИ РАБОТЫ ---

async def show_my_work_func(message_or_query, session: AsyncSession, master_profile_id: int, work_id: int = None,
                            direction: str = 'first'):
    """Отображает работу мастера с пагинацией."""
    if isinstance(message_or_query, CallbackQuery):
        query = message_or_query
        message = query.message
    else:
        query = None
        message = message_or_query

    stmt = None
    order_by = asc(TattooWork.id)
    if direction == 'first':
        stmt = select(TattooWork).where(TattooWork.master_id == master_profile_id).order_by(order_by).limit(1)
    elif direction == 'next':
        stmt = select(TattooWork).where(TattooWork.master_id == master_profile_id, TattooWork.id > work_id).order_by(
            order_by).limit(1)
    elif direction == 'prev':
        order_by = desc(TattooWork.id)
        stmt = select(TattooWork).where(TattooWork.master_id == master_profile_id, TattooWork.id < work_id).order_by(
            order_by).limit(1)

    work = await session.scalar(stmt)

    if not work:
        if direction == 'first':
            await message.answer("Вы еще не добавили ни одной работы.")
        elif query:
            await query.answer("Это последняя работа в списке.", show_alert=True)
        return

    category = await session.get(Category, work.category_id)
    status_text = STATUS_TRANSLATE.get(work.status, work.status)
    caption = (
        f"<b>Статус: {status_text}</b>\n\n"
        f"<b>Стиль:</b> {category.name if category else 'Не указан'}\n"
        f"<b>Описание:</b> {work.description}\n"
        f"<b>Цена:</b> ~{int(work.price)} руб."
    )
    keyboard = get_my_works_pagination_kb(work_id=work.id)

    if query:
        # Если сообщение уже с фото, редактируем
        if message.photo:
            await message.edit_media(
                media=InputMediaPhoto(media=work.image_file_id, caption=caption),
                reply_markup=keyboard
            )
        # Если было текстовое, удаляем и отправляем фото
        else:
            await message.delete()
            await message.answer_photo(photo=work.image_file_id, caption=caption, reply_markup=keyboard)
        await query.answer()
    else:
        await message.answer_photo(photo=work.image_file_id, caption=caption, reply_markup=keyboard)


@router.message(F.text == "📂 Мои работы")
async def my_works_start(message: Message, session: AsyncSession):
    master_profile = await session.scalar(
        select(MasterProfile).join(User).where(User.telegram_id == message.from_user.id).options(
            selectinload(MasterProfile.works))
    )
    if not master_profile:
        await message.answer("Не удалось найти ваш профиль мастера.")
        return
    await show_my_work_func(message, session, master_profile_id=master_profile.id, direction='first')


@router.callback_query(MyWorksPaginationCallback.filter())
async def my_works_paginated(query: CallbackQuery, callback_data: MyWorksPaginationCallback, session: AsyncSession):
    master_profile = await session.scalar(
        select(MasterProfile).join(User).where(User.telegram_id == query.from_user.id).options(
            selectinload(MasterProfile.works))
    )
    if not master_profile:
        await query.answer("Профиль не найден.", show_alert=True)
        return

    await show_my_work_func(query, session, master_profile_id=master_profile.id, work_id=callback_data.work_id,
                            direction=callback_data.action)


# --- ПРОФИЛЬ МАСТЕРА И РЕДАКТИРОВАНИЕ ---

async def get_profile_text(master_profile: MasterProfile) -> str:
    """Формирует текст профиля мастера."""
    profile_text = (
        f"<b>Ваш профиль мастера:</b>\n\n"
        f"<b>Город:</b> {master_profile.city}\n"
        f"<b>О себе:</b> {master_profile.description}"
    )
    if master_profile.social_links:
        links = [link['url'] for link in master_profile.social_links]
        profile_text += f"\n<b>Соц. сети:</b> {', '.join(links)}"
    return profile_text


@router.message(F.text == "👤 Мой профиль")
async def show_my_profile_handler(message: Message, session: AsyncSession):
    master_profile = await session.scalar(
        select(MasterProfile).join(User).where(User.telegram_id == message.from_user.id)
    )
    if not master_profile:
        await message.answer("Не удалось найти ваш профиль мастера.")
        return

    profile_text = await get_profile_text(master_profile)
    await message.answer(profile_text, reply_markup=get_master_profile_kb())


@router.callback_query(F.data == "show_my_profile")
async def show_my_profile_callback(query: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    master_profile = await session.scalar(
        select(MasterProfile).join(User).where(User.telegram_id == query.from_user.id)
    )
    if not master_profile:
        await query.message.edit_text("Не удалось найти ваш профиль мастера.")
        await query.answer()
        return

    profile_text = await get_profile_text(master_profile)
    await query.message.edit_text(profile_text, reply_markup=get_master_profile_kb())
    await query.answer()


@router.callback_query(F.data == "edit_master_profile")
async def start_edit_profile(query: CallbackQuery, state: FSMContext):
    await state.set_state(MasterProfileEdit.waiting_for_choice)
    await query.message.edit_text(
        "Выберите, что вы хотите изменить:",
        reply_markup=get_master_profile_edit_kb()
    )
    await query.answer()


@router.callback_query(MasterProfileEditCallback.filter(F.action == 'city'))
async def ask_for_new_city(query: CallbackQuery, state: FSMContext):
    await state.set_state(MasterProfileEdit.waiting_for_new_city)
    await query.message.edit_text("Введите новый город:")
    await query.answer()


@router.message(MasterProfileEdit.waiting_for_new_city, F.text)
async def process_edit_city(message: Message, state: FSMContext, session: AsyncSession):
    new_city = message.text
    master_profile = await session.scalar(
        select(MasterProfile).join(User).where(User.telegram_id == message.from_user.id)
    )
    master_profile.city = new_city
    await session.commit()
    await state.clear()
    await message.answer("✅ Ваш город успешно обновлен!", reply_markup=get_main_menu_kb(user_role='master'))


@router.callback_query(MasterProfileEditCallback.filter(F.action == 'description'))
async def ask_for_new_description(query: CallbackQuery, state: FSMContext):
    await state.set_state(MasterProfileEdit.waiting_for_new_description)
    await query.message.edit_text("Введите новое описание для вашего профиля:")
    await query.answer()


@router.message(MasterProfileEdit.waiting_for_new_description, F.text)
async def process_edit_description(message: Message, state: FSMContext, session: AsyncSession):
    new_description = message.text
    master_profile = await session.scalar(
        select(MasterProfile).join(User).where(User.telegram_id == message.from_user.id)
    )
    master_profile.description = new_description
    await session.commit()
    await state.clear()
    await message.answer("✅ Ваше описание успешно обновлено!", reply_markup=get_main_menu_kb(user_role='master'))


@router.callback_query(MasterProfileEditCallback.filter(F.action == 'socials'))
async def ask_for_new_socials(query: CallbackQuery, state: FSMContext):
    await state.set_state(MasterProfileEdit.waiting_for_new_socials)
    await query.message.edit_text("Отправьте новую ссылку на вашу социальную сеть:")
    await query.answer()


@router.message(MasterProfileEdit.waiting_for_new_socials, F.text)
async def process_edit_socials(message: Message, state: FSMContext, session: AsyncSession):
    new_social_link = message.text
    master_profile = await session.scalar(
        select(MasterProfile).join(User).where(User.telegram_id == message.from_user.id)
    )
    master_profile.social_links = [{"name": "link", "url": new_social_link}]
    await session.commit()
    await state.clear()
    await message.answer("✅ Ваша социальная сеть успешно обновлена!", reply_markup=get_main_menu_kb(user_role='master'))


# --- НОВЫЙ БЛОК: ПРОСМОТР И ОТВЕТ НА ОТЗЫВЫ ---

async def get_review_text_for_master(review: Review, session: AsyncSession) -> str:
    """Формирует текст отзыва для мастера."""
    client = await session.get(User, review.client_id)
    rating_stars = "⭐" * review.rating + "☆" * (5 - review.rating)

    text = (
        f"<b>Отзыв #{review.id} от клиента @{client.username or 'скрыт'}</b>\n\n"
        f"<b>Оценка:</b> {rating_stars}\n"
        f"<b>Текст отзыва:</b>\n<i>{review.text}</i>\n\n"
        "<b>Ваш ответ:</b>\n"
        f"<i>{review.admin_reply or 'Вы еще не ответили.'}</i>"
    )
    return text


async def show_master_review(query: CallbackQuery, session: AsyncSession, master_id: int, review_id: int = None,
                             direction: str = 'first'):
    """Отображает отзывы для мастера с пагинацией."""
    stmt = None
    if direction == 'first':
        stmt = select(Review).where(Review.master_id == master_id).order_by(desc(Review.id)).limit(1)
    elif direction == 'next':
        stmt = select(Review).where(Review.master_id == master_id, Review.id < review_id).order_by(
            desc(Review.id)).limit(1)
    elif direction == 'prev':
        stmt = select(Review).where(Review.master_id == master_id, Review.id > review_id).order_by(
            asc(Review.id)).limit(1)
    # Добавляем условие для обновления после ответа
    elif direction is None and review_id is not None:
        stmt = select(Review).where(Review.id == review_id)

    review = await session.scalar(stmt)

    if not review:
        if direction == 'first':
            await query.message.edit_text("У вас пока нет ни одного отзыва.")
        else:
            await query.answer("Это последний отзыв в списке.", show_alert=True)
        return

    text = await get_review_text_for_master(review, session)
    keyboard = get_master_review_keyboard(review.id)

    # Проверяем, есть ли у сообщения метод edit_text, чтобы избежать ошибки
    if hasattr(query.message, 'edit_text'):
        await query.message.edit_text(text, reply_markup=keyboard)
    else:
        # Если это новое сообщение (как после ответа мастера), отправляем его
        await query.message.answer(text, reply_markup=keyboard)

    await query.answer()


@router.callback_query(F.data == "master_reviews_view")
async def view_master_reviews_start(query: CallbackQuery, session: AsyncSession):
    master_profile = await session.scalar(
        select(MasterProfile).join(User).where(User.telegram_id == query.from_user.id)
    )
    if not master_profile:
        await query.answer("Ваш профиль мастера не найден.", show_alert=True)
        return

    await show_master_review(query, session, master_id=master_profile.id, direction='first')


@router.callback_query(MasterReviewCallback.filter(F.action.in_(['prev', 'next'])))
async def paginate_master_reviews(query: CallbackQuery, callback_data: MasterReviewCallback, session: AsyncSession):
    master_profile = await session.scalar(
        select(MasterProfile).join(User).where(User.telegram_id == query.from_user.id)
    )
    if not master_profile:
        await query.answer("Ваш профиль мастера не найден.", show_alert=True)
        return

    await show_master_review(query, session, master_id=master_profile.id, review_id=callback_data.review_id,
                             direction=callback_data.action)


@router.callback_query(MasterReviewCallback.filter(F.action == "reply"))
async def start_master_reply(query: CallbackQuery, callback_data: MasterReviewCallback, state: FSMContext):
    await state.set_state(MasterReviewReply.waiting_for_reply_text)
    await state.update_data(review_id=callback_data.review_id)
    await query.message.answer("Введите ваш ответ на этот отзыв:")
    await query.answer()


@router.message(MasterReviewReply.waiting_for_reply_text, F.text)
async def process_master_reply(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    review_id = data.get("review_id")
    reply_text = message.text

    review = await session.get(Review, review_id)
    if not review:
        await message.answer("Ошибка: не удалось найти отзыв для ответа.")
        await state.clear()
        return

    review.admin_reply = reply_text  # Используем то же поле, что и админ
    await session.commit()
    await state.clear()

    await message.answer("✅ Ваш ответ сохранен.")

    # Уведомление клиенту
    client = None
    try:
        client = await session.get(User, review.client_id)
        # Для уведомления нам нужен профиль мастера
        master_profile = await session.get(MasterProfile, review.master_id)
        master_user = await session.get(User, master_profile.user_id)
        if client:
            await message.bot.send_message(
                client.telegram_id,
                f"Мастер @{master_user.username or '...'} ответил на ваш отзыв:\n\n<i>{reply_text}</i>"
            )
    except Exception as e:
        client_id_for_log = client.telegram_id if client else "unknown"
        logging.error(f"Не удалось отправить уведомление клиенту {client_id_for_log}: {e}")

    # Показываем обновленный отзыв мастеру
    master_profile = await session.scalar(
        select(MasterProfile).join(User).where(User.telegram_id == message.from_user.id)
    )
    fake_query = types.CallbackQuery(id="fake", from_user=message.from_user, chat_instance="", message=message)
    await show_master_review(fake_query, session, master_id=master_profile.id, review_id=review_id, direction=None)