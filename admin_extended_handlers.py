from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from keyboards import (get_admin_category_manage_kb, AdminMenuCallback,
                       AdminCategoryCallback, get_admin_main_kb)
from database import Category
# Исправлено имя импортируемого класса
from states import AdminCategoryManagement
from admin_handlers import IsAdmin

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
    "work_management", "review_management", "payment_management", "statistics", "mailing"
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

    # Проверка на существование
    existing = await session.scalar(select(Category).where(Category.name == new_category_name))
    if existing:
        await message.answer(f"Категория '{new_category_name}' уже существует. Попробуйте другое название.")
        return

    new_category = Category(name=new_category_name)
    session.add(new_category)
    await session.commit()
    await state.clear()

    await message.answer(f"✅ Категория '{new_category_name}' успешно добавлена.")

    # Возвращаемся к списку
    categories = await session.scalars(select(Category).order_by(Category.name))
    await message.answer(
        "Управление категориями (стилями) татуировок:",
        reply_markup=get_admin_category_manage_kb(list(categories.all()))
    )


@router.callback_query(AdminCategoryCallback.filter(F.action == "delete"))
async def delete_category(query: CallbackQuery, callback_data: AdminCategoryCallback, session: AsyncSession):
    # TODO: Добавить проверку, что категория не используется ни в одной работе
    category_id = callback_data.category_id
    category_name = callback_data.category_name

    await session.execute(delete(Category).where(Category.id == category_id))
    await session.commit()

    await query.answer(f"Категория '{category_name}' удалена.", show_alert=True)

    # Обновляем список
    categories = await session.scalars(select(Category).order_by(Category.name))
    await query.message.edit_text(
        "Управление категориями (стилями) татуировок:",
        reply_markup=get_admin_category_manage_kb(list(categories.all()))
    )