# --- file: admin_handlers.py ---

from aiogram import Router, F, types
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database import TattooWork, MasterProfile, User, Category # Добавили Category
from keyboards import AdminModerationCallback, get_admin_main_kb, get_admin_user_manage_kb, AdminUserActionCallback, AdminMenuCallback
from states import AdminUserSearch

router = Router()


class IsAdmin(Filter):
    def __init__(self) -> None:
        self.admin_ids = [int(i) for i in settings.admin_ids.split(',')]

    async def __call__(self, message: types.TelegramObject) -> bool:
        return message.from_user.id in self.admin_ids


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("admin"))
async def cmd_admin_panel(message: Message):
    await message.answer("Добро пожаловать в админ-панель!", reply_markup=get_admin_main_kb())


# --- ОБНОВЛЕННЫЙ БЛОК УПРАВЛЕНИЯ ПОЛЬЗОВАТЕЛЯМИ ---

@router.callback_query(AdminMenuCallback.filter(F.action == "user_management"))
async def start_user_search(query: CallbackQuery, state: FSMContext):
    await state.set_state(AdminUserSearch.waiting_for_user_id)
    await query.message.edit_text("Введите Telegram ID пользователя, которого хотите найти.")
    await query.answer()


@router.message(AdminUserSearch.waiting_for_user_id, F.text)
async def process_user_search(message: Message, state: FSMContext, session: AsyncSession):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите корректный Telegram ID (только цифры).")
        return

    user_id = int(message.text)
    user = await session.scalar(select(User).where(User.telegram_id == user_id))

    if not user:
        await message.answer(f"Пользователь с ID `{user_id}` не найден в базе данных.")
        await state.clear()
        return

    is_active = True
    keyboard = None

    user_info = (
        f"<b>Пользователь найден:</b>\n\n"
        f"Telegram ID: `{user.telegram_id}`\n"
        f"Username: @{user.username if user.username else 'не указан'}\n"
        f"Полное имя: {user.full_name}\n"
        f"Роль: <b>{user.role.upper()}</b>"
    )

    if user.role == 'master':
        master_profile = await session.scalar(select(MasterProfile).where(MasterProfile.user_id == user.id))
        if master_profile:
            is_active = master_profile.is_active
            user_info += f"\nСтатус: {'Активен' if is_active else 'Заблокирован'}"
            keyboard = get_admin_user_manage_kb(user_id=user.id, is_active=is_active, role=user.role)

    await message.answer(user_info, reply_markup=keyboard)
    await state.clear()


@router.callback_query(AdminUserActionCallback.filter(F.action.in_(['block', 'unblock', 'revoke_master'])))
async def block_unblock_user(query: CallbackQuery, callback_data: AdminUserActionCallback, session: AsyncSession):
    user_to_manage = await session.get(User, callback_data.user_id)
    if not user_to_manage or user_to_manage.role != 'master':
        await query.answer("Можно заблокировать только мастера.", show_alert=True)
        return

    master_profile = await session.scalar(select(MasterProfile).where(MasterProfile.user_id == user_to_manage.id))
    if not master_profile:
        await query.answer("Профиль мастера не найден.", show_alert=True)
        return

    if callback_data.action == 'block':
        master_profile.is_active = False
        action_text = "заблокирован"
    else:  # unblock
        master_profile.is_active = True
        action_text = "разблокирован"

    await session.commit()
    await query.answer(f"Мастер успешно {action_text}.")

    keyboard = get_admin_user_manage_kb(user_id=user_to_manage.id, is_active=master_profile.is_active)
    await query.message.edit_reply_markup(reply_markup=keyboard)

    try:
        await query.bot.send_message(user_to_manage.telegram_id,
                                     f"Ваш профиль мастера был {action_text} администратором.")
    except Exception as e:
        print(f"Не удалось уведомить пользователя {user_to_manage.telegram_id}: {e}")

    if callback_data.action == 'revoke_master':
        user_to_manage.role = 'client'
        if master_profile:
            # Удаляем работы мастера и его профиль
            await session.execute(delete(TattooWork).where(TattooWork.master_id == master_profile.id))
            await session.delete(master_profile)
        action_text = "лишен статуса мастера"

        await session.commit()
        await query.answer("Пользователь лишен статуса мастера.", show_alert=True)
        await query.message.edit_text("Профиль пользователя обновлен. Он больше не является мастером.")

        try:
            await query.bot.send_message(user_to_manage.telegram_id, "Администратор лишил вас статуса мастера.")
        except Exception as e:
            logging.error(f"Не удалось уведомить пользователя {user_to_manage.telegram_id}: {e}")
        return

    await session.commit()
    await query.answer(f"Мастер успешно {action_text}.")
    # 👇 ИЗМЕНЯЕМ ВЫЗОВ, ДОБАВЛЯЕМ user_to_manage.role
    keyboard = get_admin_user_manage_kb(user_id=user_to_manage.id, is_active=master_profile.is_active,
                                        role=user_to_manage.role)
    await query.message.edit_reply_markup(reply_markup=keyboard)



# --- БЛОК МОДЕРАЦИИ РАБОТ (без изменений) ---
@router.callback_query(AdminModerationCallback.filter(F.action == "approve"))
async def approve_work(query: CallbackQuery, callback_data: AdminModerationCallback, session: AsyncSession):
    work = await session.get(TattooWork, callback_data.work_id)
    if not work:
        await query.answer("Работа не найдена!", show_alert=True)
        return
    work.status = 'published'
    await session.commit()
    await query.message.edit_caption(
        caption=query.message.caption + f"\n\n✅ Одобрено @{query.from_user.username}",
        reply_markup=None
    )
    master_profile = await session.get(MasterProfile, work.master_id)
    user = await session.get(User, master_profile.user_id)
    try:
        await query.bot.send_message(
            chat_id=user.telegram_id,
            text="🎉 Ваша работа прошла модерацию и опубликована в каталоге!"
        )
    except Exception as e:
        print(f"Не удалось отправить уведомление мастеру {user.telegram_id}: {e}")
    await query.answer("Работа одобрена.")


@router.callback_query(AdminModerationCallback.filter(F.action == "reject"))
async def reject_work(query: CallbackQuery, callback_data: AdminModerationCallback, session: AsyncSession):
    work = await session.get(TattooWork, callback_data.work_id)
    if not work:
        await query.answer("Работа не найдена!", show_alert=True)
        return
    work.status = 'rejected'
    await session.commit()
    await query.message.edit_caption(
        caption=query.message.caption + f"\n\n❌ Отклонено @{query.from_user.username}",
        reply_markup=None
    )
    master_profile = await session.get(MasterProfile, work.master_id)
    user = await session.get(User, master_profile.user_id)
    try:
        await query.bot.send_message(
            chat_id=user.telegram_id,
            text="К сожалению, ваша работа была отклонена модератором."
        )
    except Exception as e:
        print(f"Не удалось отправить уведомление мастеру {user.telegram_id}: {e}")
    await query.answer("Работа отклонена.")
