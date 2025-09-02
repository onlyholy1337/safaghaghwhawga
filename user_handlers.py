from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove, CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc, func, or_
import logging
from typing import Optional
from math import ceil

from keyboards import (get_main_menu_kb, get_pagination_kb, WorkPaginationCallback,
                       MasterCallback, LikeCallback, ReviewCallback, get_rating_kb,
                       get_work_filter_options_kb, get_category_filter_kb, WorkFilterCallback,
                       get_master_search_options_kb, get_master_list_pagination_kb,
                       MasterSearchCallback, MasterListPagination)
from database import User, MasterProfile, TattooWork, Like, Review, Category
from states import MasterRegistration, UserReviewing, UserMasterSearch

router = Router()


async def update_master_rating(master_id: int, session: AsyncSession):
    """Пересчитывает и обновляет рейтинг мастера на основе всех его отзывов."""
    avg_rating_result = await session.execute(
        select(func.avg(Review.rating)).where(Review.master_id == master_id)
    )
    avg_rating = avg_rating_result.scalar_one_or_none()

    master_profile = await session.get(MasterProfile, master_id)
    if master_profile:
        master_profile.rating = avg_rating if avg_rating is not None else 0
        await session.commit()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    user_result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
    user = user_result.scalar_one_or_none()
    if not user:
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name
        )
        session.add(user)
        await session.commit()
    keyboard = get_main_menu_kb(user.role)
    await message.answer(
        "Добро пожаловать в Тату Маркетплейс!",
        reply_markup=keyboard
    )


# --- РЕГИСТРАЦИЯ МАСТЕРА ---

@router.message(F.text == "⭐️ Стать мастером")
async def start_master_reg(message: Message, state: FSMContext):
    await state.set_state(MasterRegistration.waiting_for_city)
    await message.answer("Из какого вы города?", reply_markup=ReplyKeyboardRemove())


@router.message(MasterRegistration.waiting_for_city, F.text)
async def process_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text)
    await state.set_state(MasterRegistration.waiting_for_description)
    await message.answer("Город записан. Теперь расскажите немного о себе...")


@router.message(MasterRegistration.waiting_for_description, F.text)
async def process_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(MasterRegistration.waiting_for_socials)
    await message.answer("Отличное описание! Теперь отправьте ссылку на соц. сеть.")


@router.message(MasterRegistration.waiting_for_socials, F.text)
async def process_socials(message: Message, state: FSMContext, session: AsyncSession):
    await state.update_data(socials=[{"name": "link", "url": message.text}])
    user_data = await state.get_data()

    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))

    new_master_profile = MasterProfile(
        user_id=user.id,
        city=user_data.get("city"),
        description=user_data.get("description"),
        social_links=user_data.get("socials")
    )
    session.add(new_master_profile)

    user.role = 'master'

    await session.commit()
    await session.refresh(user)

    await state.clear()

    keyboard = get_main_menu_kb(user_role=user.role)
    await message.answer(
        "🎉 Поздравляем! Вы стали мастером на нашей площадке. Ваш профиль создан.\n\n"
        "Теперь вам доступны новые функции.",
        reply_markup=keyboard
    )


# --- ПРОСМОТР РАБОТ И ФИЛЬТРАЦИЯ ---

async def show_work(message_or_query, session: AsyncSession, work_id: int = None, direction: str = 'first',
                    category_id: Optional[int] = None):
    if isinstance(message_or_query, CallbackQuery):
        query = message_or_query
        message = query.message
        user_id = query.from_user.id
    else:
        query = None
        message = message_or_query
        user_id = message.from_user.id

    base_stmt = select(TattooWork).where(TattooWork.status == 'published')
    if category_id:
        base_stmt = base_stmt.where(TattooWork.category_id == category_id)

    stmt = None
    if direction == 'first':
        stmt = base_stmt.order_by(asc(TattooWork.id)).limit(1)
    elif direction == 'next':
        stmt = base_stmt.where(TattooWork.id > work_id).order_by(asc(TattooWork.id)).limit(1)
    elif direction == 'prev':
        stmt = base_stmt.where(TattooWork.id < work_id).order_by(desc(TattooWork.id)).limit(1)

    if stmt is None:
        logging.error(f"Неизвестное направление пагинации: {direction}")
        if query: await query.answer("Произошла ошибка!")
        return

    work = await session.scalar(stmt)

    if not work:
        if direction == 'first':
            text = "В галерее пока нет ни одной работы."
            if category_id:
                category = await session.get(Category, category_id)
                text = f"В категории '{category.name}' пока нет работ."

            if query:
                await query.message.edit_text(text, reply_markup=None)
            else:
                await message.answer(text)
        elif query:
            await query.answer("Это последняя работа в галерее.", show_alert=True)
        return

    master_profile = await session.get(MasterProfile, work.master_id)
    user_master = await session.get(User, master_profile.user_id)

    current_user_db = await session.scalar(select(User).where(User.telegram_id == user_id))
    is_liked = False
    if current_user_db:
        like = await session.scalar(select(Like).where(Like.user_id == current_user_db.id, Like.work_id == work.id))
        is_liked = bool(like)

    username = user_master.username if user_master.username else "скрыт"
    category_name = work.category.name if work.category else "Не указан"

    caption = (
        f"<b>Стиль:</b> {category_name}\n"
        f"<b>Описание:</b> {work.description}\n"
        f"<b>Цена:</b> ~{int(work.price)} руб.\n\n"
        f"<b>Мастер:</b> @{username}"
    )

    keyboard = get_pagination_kb(
        current_work_id=work.id,
        master_id=master_profile.id,
        likes_count=work.likes_count,
        is_liked=is_liked,
        category_id=category_id
    )

    media = InputMediaPhoto(media=work.image_file_id, caption=caption)

    if query:
        if query.message.photo:
            await query.message.edit_media(media=media, reply_markup=keyboard)
        else:
            await query.message.delete()
            await query.message.answer_photo(photo=media.media, caption=caption, reply_markup=keyboard)
        await query.answer()
    else:
        await message.answer_photo(photo=media.media, caption=caption, reply_markup=keyboard)


@router.message(F.text == "🎨 Просмотр работ")
async def browse_works_start(message: Message, session: AsyncSession):
    await message.answer("Выберите, как вы хотите просматривать работы:", reply_markup=get_work_filter_options_kb())


@router.callback_query(WorkFilterCallback.filter(F.action == "show_all"))
async def filter_show_all(query: CallbackQuery, session: AsyncSession):
    await show_work(query, session, direction='first', category_id=None)


@router.callback_query(WorkFilterCallback.filter(F.action == "by_style"))
async def filter_by_style(query: CallbackQuery, session: AsyncSession):
    categories = await session.scalars(select(Category).order_by(Category.name))
    await query.message.edit_text("Выберите стиль для фильтрации:",
                                  reply_markup=get_category_filter_kb(list(categories)))
    await query.answer()


@router.callback_query(WorkFilterCallback.filter(F.action == "select_style"))
async def filter_select_style(query: CallbackQuery, callback_data: WorkFilterCallback, session: AsyncSession):
    await show_work(query, session, direction='first', category_id=callback_data.category_id)


@router.callback_query(WorkFilterCallback.filter(F.action == "back_to_options"))
async def filter_back_to_options(query: CallbackQuery):
    await query.message.edit_text("Выберите, как вы хотите просматривать работы:",
                                  reply_markup=get_work_filter_options_kb())
    await query.answer()


@router.callback_query(WorkPaginationCallback.filter())
async def browse_works_paginated(query: CallbackQuery, callback_data: WorkPaginationCallback, session: AsyncSession):
    await show_work(
        query,
        session,
        work_id=callback_data.current_work_id,
        direction=callback_data.action,
        category_id=callback_data.category_id
    )


# --- ПРОСМОТР И ПОИСК МАСТЕРОВ ---

async def build_master_card_text(master_profile: MasterProfile, user_master: User) -> str:
    """Формирует текст карточки мастера."""
    username = user_master.username if user_master.username else "скрыт"
    rating_str = f"{master_profile.rating:.1f} ⭐" if master_profile.rating is not None and master_profile.rating > 0 else "еще нет оценок"

    text = (
        f"<b>Профиль мастера @{username}</b>\n\n"
        f"<b>Рейтинг:</b> {rating_str}\n"
        f"<b>Город:</b> {master_profile.city}\n"
        f"<b>О себе:</b> {master_profile.description}\n\n"
    )
    if master_profile.social_links:
        links = [f"<a href='{link['url']}'><b>{link['url']}</b></a>" for link in master_profile.social_links]
        text += "<b>Контакты для связи:</b>\n" + "\n".join(links)
    return text


async def show_masters_list(message: types.Message, session: AsyncSession, page: int = 1, city: Optional[str] = None):
    """Отображает список мастеров с пагинацией."""
    per_page = 1  # Показываем по одному мастеру
    offset = (page - 1) * per_page

    base_query = select(MasterProfile).join(User).where(MasterProfile.is_active == True)
    if city:
        # Поиск по городу без учета регистра
        base_query = base_query.where(func.lower(MasterProfile.city) == city.lower())

    # Считаем общее количество
    count_query = select(func.count()).select_from(base_query.subquery())
    total_masters = await session.scalar(count_query)

    if total_masters == 0:
        text = "Мастера не найдены."
        if city:
            text = f"Мастера из города '{city}' не найдены."
        # Проверяем, было ли это сообщение отправлено после ввода текста (не имеет reply_markup)
        if hasattr(message, 'edit_text'):
            await message.edit_text(text, reply_markup=None)
        else:
            await message.answer(text, reply_markup=None)
        return

    total_pages = ceil(total_masters / per_page)

    # Получаем мастера на текущей странице
    masters_query = base_query.order_by(desc(MasterProfile.rating)).limit(per_page).offset(offset)
    master_profile = await session.scalar(masters_query)

    user_master = await session.get(User, master_profile.user_id)
    card_text = await build_master_card_text(master_profile, user_master)

    keyboard = get_master_list_pagination_kb(total_pages, page, city)

    if hasattr(message, 'edit_text'):
        await message.edit_text(card_text, reply_markup=keyboard, disable_web_page_preview=True)
    else:
        # Это случай, когда пользователь ввел город текстом
        await message.answer(card_text, reply_markup=keyboard, disable_web_page_preview=True)


@router.message(F.text == "👥 Просмотр мастеров")
async def browse_masters_start(message: Message):
    await message.answer("Как вы хотите найти мастера?", reply_markup=get_master_search_options_kb())


@router.callback_query(MasterSearchCallback.filter(F.action == "show_all"))
async def search_all_masters(query: CallbackQuery, session: AsyncSession):
    await show_masters_list(query.message, session, page=1)
    await query.answer()


@router.callback_query(MasterSearchCallback.filter(F.action == "by_city"))
async def search_masters_by_city_start(query: CallbackQuery, state: FSMContext):
    await state.set_state(UserMasterSearch.waiting_for_city)
    await query.message.edit_text("Введите название города для поиска:")
    await query.answer()


@router.message(UserMasterSearch.waiting_for_city, F.text)
async def search_masters_by_city_process(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    await show_masters_list(message, session, page=1, city=message.text)


@router.callback_query(MasterListPagination.filter())
async def masters_list_paginated(query: CallbackQuery, callback_data: MasterListPagination, session: AsyncSession):
    await show_masters_list(query.message, session, page=callback_data.page, city=callback_data.city)
    await query.answer()


# --- ЛАЙКИ И ОТЗЫВЫ ---

@router.callback_query(LikeCallback.filter(F.action == "toggle"))
async def toggle_like(query: CallbackQuery, callback_data: LikeCallback, session: AsyncSession):
    user = await session.scalar(select(User).where(User.telegram_id == query.from_user.id))
    work = await session.get(TattooWork, callback_data.work_id)

    if not user or not work:
        await query.answer("Ошибка: пользователь или работа не найдены.", show_alert=True)
        return

    current_category_id = None
    if query.message.reply_markup:
        for row in query.message.reply_markup.inline_keyboard:
            for button in row:
                if button.callback_data and button.callback_data.startswith("work_pag:next"):
                    try:
                        parts = button.callback_data.split(':')
                        if len(parts) > 3 and parts[3] and parts[3] != 'None':
                            current_category_id = int(parts[3])
                    except (ValueError, IndexError):
                        pass
                    break
            if current_category_id is not None:
                break

    like = await session.scalar(select(Like).where(Like.user_id == user.id, Like.work_id == work.id))

    if like:
        await session.delete(like)
        work.likes_count -= 1
        is_liked_new = False
        await query.answer("Лайк убран")
    else:
        new_like = Like(user_id=user.id, work_id=work.id)
        session.add(new_like)
        work.likes_count += 1
        is_liked_new = True
        await query.answer("❤️")

    await session.commit()

    keyboard = get_pagination_kb(
        current_work_id=work.id,
        master_id=work.master_id,
        likes_count=work.likes_count,
        is_liked=is_liked_new,
        category_id=current_category_id
    )
    await query.message.edit_reply_markup(reply_markup=keyboard)


@router.callback_query(ReviewCallback.filter(F.action == "create"))
async def start_review(query: CallbackQuery, callback_data: ReviewCallback, state: FSMContext, session: AsyncSession):
    work = await session.get(TattooWork, callback_data.work_id)
    if not work:
        await query.answer("Работа не найдена.", show_alert=True)
        return

    await state.set_state(UserReviewing.waiting_for_rating)
    await state.update_data(work_id=work.id, master_id=work.master_id)

    await query.message.answer("Пожалуйста, оцените работу мастера от 1 до 5:", reply_markup=get_rating_kb())
    await query.answer()


@router.callback_query(UserReviewing.waiting_for_rating, F.data.startswith("rating_"))
async def process_rating(query: CallbackQuery, state: FSMContext):
    rating = int(query.data.split("_")[1])
    await state.update_data(rating=rating)
    await state.set_state(UserReviewing.waiting_for_text)

    await query.message.edit_text(f"Вы поставили оценку: {rating} ⭐\n\nТеперь напишите ваш отзыв:")
    await query.answer()


@router.message(UserReviewing.waiting_for_text, F.text)
async def process_review_text(message: Message, state: FSMContext, session: AsyncSession):
    review_text = message.text
    user_data = await state.get_data()

    current_user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))

    new_review = Review(
        work_id=user_data.get("work_id"),
        master_id=user_data.get("master_id"),
        client_id=current_user.id,
        rating=user_data.get("rating"),
        text=review_text
    )
    session.add(new_review)
    await session.commit()

    await update_master_rating(user_data.get("master_id"), session)

    await state.clear()
    await message.answer("✅ Спасибо! Ваш отзыв был успешно оставлен.")


# --- ПРОФИЛЬ МАСТЕРА (ОБЩИЙ ПРОСМОТР) ---

@router.callback_query(MasterCallback.filter(F.action == "view"))
async def show_master_profile(query: CallbackQuery, callback_data: MasterCallback, session: AsyncSession):
    master_profile = await session.get(MasterProfile, callback_data.master_id)
    if not master_profile:
        await query.answer("Профиль мастера не найден.", show_alert=True)
        return

    user_master = await session.get(User, master_profile.user_id)
    card_text = await build_master_card_text(master_profile, user_master)

    await query.message.answer(card_text, disable_web_page_preview=True)
    await query.answer()


# --- РАЗДЕЛЫ В РАЗРАБОТКЕ ---

@router.message(F.text.in_({"❓ FAQ", "📞 Контакты"}))
async def menu_in_development(message: Message):
    await message.answer("Этот раздел находится в разработке...")

