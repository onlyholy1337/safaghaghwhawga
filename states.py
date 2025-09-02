# states.py

from aiogram.fsm.state import State, StatesGroup


class MasterRegistration(StatesGroup):
    waiting_for_city = State()
    waiting_for_description = State()
    waiting_for_socials = State()


class WorkSubmission(StatesGroup):
    waiting_for_photo = State()
    waiting_for_description = State()
    waiting_for_style = State()  # Теперь это выбор категории
    waiting_for_price = State()
    waiting_for_payment_check = State()


class AdminMailing(StatesGroup):
    waiting_for_message_content = State()
    waiting_for_confirmation = State()


class AdminUserSearch(StatesGroup):
    waiting_for_user_id = State()


class MasterProfileEdit(StatesGroup):
    waiting_for_choice = State()
    waiting_for_new_city = State()
    waiting_for_new_description = State()
    waiting_for_new_socials = State()


class AdminCategoryManagement(StatesGroup):
    waiting_for_name = State()


# --- НОВЫЕ СОСТОЯНИЯ ДЛЯ УПРАВЛЕНИЯ ОТЗЫВАМИ ---
class AdminReviewManagement(StatesGroup):
    waiting_for_reply = State()


class UserReviewing(StatesGroup):
    waiting_for_rating = State()
    waiting_for_text = State()


class UserMasterSearch(StatesGroup):
    waiting_for_city = State()