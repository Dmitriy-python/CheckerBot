from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database.database import SessionLocal, Channel


def admin_menu_kb():
    """Главное меню администратора"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Целевой канал", callback_data="target_channel")],
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")],
        [InlineKeyboardButton(text="❌ Удалить канал", callback_data="delete_channel")],
        [InlineKeyboardButton(text="📜 Список каналов", callback_data="list_channels")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="announcement")],
        [InlineKeyboardButton(text="📢 Премиум рассылка", callback_data="prem_announcement")],
        [InlineKeyboardButton(text="Редактировать сообщения", callback_data="edit_messages")],
        [InlineKeyboardButton(text="Статистика", callback_data="total_users")],
    ])
    return kb




target_menu = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить канал", callback_data="change_target_channel")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_menu")]
    ])




main_menu_btn = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_menu")]
        ])


choose_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, с фото", callback_data="broadcast_photo_yes")],
        [InlineKeyboardButton(text="Нет, только текст", callback_data="broadcast_photo_no")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_menu")]
    ])


push_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Разослать", callback_data="send_broadcast")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_menu")]
    ])



check_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
    ])


def delete_channels_kb():
    db = SessionLocal()
    channels = db.query(Channel).all()
    db.close()

    if not channels:
        return None

    buttons = [
        [InlineKeyboardButton(
            text=f"{ch.name}",
            callback_data=f"delch_{ch.channel_id}"
        )]
        for ch in channels
    ]

    # Добавляем кнопку "Главное меню" в конец
    buttons.append([InlineKeyboardButton(
        text="🔙 Главное меню",
        callback_data="admin_menu"
    )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    return kb