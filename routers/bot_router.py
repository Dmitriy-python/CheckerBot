import logging

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import ChatMemberUpdatedFilter, LEAVE_TRANSITION, Command
from aiogram.types import ChatJoinRequest, CallbackQuery, ChatMemberUpdated
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database.database import SessionLocal, User, Channel, Message, PendingRequest
from routers.admin_router import get_target_channel

bot_router = Router()
logger = logging.getLogger(__name__)

import html

def entities_to_html(text: str, entities: list | None) -> str:
    """
    Конвертирует text + entities в HTML с учётом кириллицы.
    Исправляет баг Telegram с неверными offset/length при Unicode.
    """
    if not entities:
        return html.escape(text)

    html_parts = []
    last_byte_index = 0
    encoded = text.encode('utf-16-le')  # Telegram считает offset в UTF-16
    for ent in entities:
        start_b = ent["offset"] * 2
        end_b = (ent["offset"] + ent["length"]) * 2

        # Получаем символы из байтов
        before = encoded[last_byte_index:start_b].decode('utf-16-le', errors='ignore')
        entity_text = encoded[start_b:end_b].decode('utf-16-le', errors='ignore')
        html_parts.append(html.escape(before))

        t = ent["type"]
        if t == "text_link" and ent.get("url"):
            html_parts.append(f'<a href="{html.escape(ent["url"], quote=True)}">{html.escape(entity_text)}</a>')
        elif t == "url":
            html_parts.append(f'<a href="{html.escape(entity_text)}">{html.escape(entity_text)}</a>')
        elif t == "bold":
            html_parts.append(f"<b>{html.escape(entity_text)}</b>")
        elif t == "italic":
            html_parts.append(f"<i>{html.escape(entity_text)}</i>")
        elif t == "underline":
            html_parts.append(f"<u>{html.escape(entity_text)}</u>")
        elif t == "strikethrough":
            html_parts.append(f"<s>{html.escape(entity_text)}</s>")
        elif t == "code":
            html_parts.append(f"<code>{html.escape(entity_text)}</code>")
        else:
            html_parts.append(html.escape(entity_text))

        last_byte_index = end_b

    # добавляем остаток
    rest = encoded[last_byte_index:].decode('utf-16-le', errors='ignore')
    html_parts.append(html.escape(rest))

    return "".join(html_parts)

@bot_router.message(Command("start"))
async def cmd_start(message: Message):
    """Приветственное сообщение после /start"""
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    username = message.from_user.username or "None"

    db = SessionLocal()

    # --- Создаём пользователя, если его нет ---
    existing_user = db.query(User).filter_by(user_id=user_id).first()
    if not existing_user:
        new_user = User(user_id=user_id, first_name=first_name, username=username)
        db.add(new_user)
        db.commit()

    channels = db.query(Channel).all()
    db.close()

    # --- Клавиатура ---
    buttons = [
        [InlineKeyboardButton(text=f"📢 Канал {i+1}", url=ch.link)]
        for i, ch in enumerate(channels)
    ]
    buttons.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    # --- Получаем приветственное сообщение ---
    db = SessionLocal()
    welcome = db.query(Message).filter_by(title="Приветственное").first()
    db.close()

    if welcome:
        # Конвертируем entities → HTML
        html_text = entities_to_html(welcome.text, welcome.entities)
        await message.answer(html_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

@bot_router.chat_join_request()
async def handle_join_request(update: ChatJoinRequest, bot):
    """Обрабатывает заявки на вступление в закрытый канал и отправляет приветственное сообщение."""
    TARGET_CHANNEL_ID = get_target_channel()
    user_id = update.from_user.id
    first_name = update.from_user.first_name
    username = update.from_user.username or "None"
    chat_id = update.chat.id

    # --- Сохраняем заявку в pending ---
    db = SessionLocal()
    try:
        if not db.query(PendingRequest).filter_by(user_id=user_id, chat_id=chat_id).first():
            db.add(PendingRequest(user_id=user_id, chat_id=chat_id))
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    # --- Игнорируем заявки не в основной канал ---
    if chat_id != TARGET_CHANNEL_ID.channel_id:
        return

    # --- Получаем текст "Самое первое" из БД ---
    db = SessionLocal()
    try:
        first_msg = db.query(Message).filter_by(title="Самое первое с командой /start").first()
    finally:
        db.close()

    # --- Формируем сообщение ---
    if first_msg:
        text = entities_to_html(first_msg.text, first_msg.entities)
    else:
        text = (
            f"👋 Привет, {first_name}!\n\n"
            f"Чтобы попасть в закрытый канал, сначала напиши мне в личные сообщения: /start"
        )
    text+= "\n\n➡️ <b>Нажмите /start</b>"
    # --- Отправляем пользователю ---
    try:
        await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
    except Exception:
        pass




@bot_router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery):
    """Проверка подписки и автоматическое одобрение заявки в основной канал."""
    TARGET_CHANNEL_ID = get_target_channel()
    user_id = callback.from_user.id

    db = SessionLocal()
    try:
        channels = db.query(Channel).all()
        success_message = db.query(Message).filter_by(title="Подписка на канал").first()
        error_message = db.query(Message).filter_by(title="Ошибка проверки").first()
    finally:
        db.close()

    missing_channels = []

    # --- Проверяем подписку на каждый канал ---
    for ch in channels:
        chat_id = int(ch.channel_id)

        try:
            member = await callback.bot.get_chat_member(chat_id=chat_id, user_id=user_id)

            if member.status in ["member", "administrator", "creator", "restricted"]:
                continue  # уже в канале

            # Проверяем pending-заявку
            db = SessionLocal()
            try:
                pending = db.query(PendingRequest).filter_by(user_id=user_id, chat_id=chat_id).first()
            finally:
                db.close()

            if not pending:
                missing_channels.append(ch)

        except Exception:
            # Если не удалось проверить, всё равно пробуем через pending
            db = SessionLocal()
            try:
                pending = db.query(PendingRequest).filter_by(user_id=user_id, chat_id=chat_id).first()
            finally:
                db.close()

            if not pending:
                missing_channels.append(ch)

    # --- Если есть неподписанные каналы ---
    if missing_channels:
        buttons = [
            [InlineKeyboardButton(text=f"📢 Канал {i+1}", url=ch.link)]
            for i, ch in enumerate(missing_channels)
        ]
        buttons.append([InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        error_text = entities_to_html(error_message.text, error_message.entities)
        await callback.message.answer(error_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        await callback.answer("Нужно подписаться на все каналы")
        return

    # --- Все подписки подтверждены ---
    try:
        await callback.bot.approve_chat_join_request(chat_id=TARGET_CHANNEL_ID.channel_id, user_id=user_id)

        db = SessionLocal()
        try:
            db.query(PendingRequest).filter_by(user_id=user_id, chat_id=TARGET_CHANNEL_ID.channel_id).delete()
            db.commit()
        finally:
            db.close()

        response_text = entities_to_html(success_message.text, success_message.entities) \
            if success_message else "✅ Подписка успешно подтверждена!"
        await callback.message.edit_text(response_text, parse_mode=ParseMode.HTML)
        await callback.answer("Вы приняты в канал")

    except Exception as e:
        err_msg = str(e)
        # --- Если пользователь уже участник ---
        if "USER_ALREADY_PARTICIPANT" in err_msg:
            db = SessionLocal()
            try:
                db.query(PendingRequest).filter_by(user_id=user_id, chat_id=TARGET_CHANNEL_ID.channel_id).delete()
                db.commit()
            finally:
                db.close()
            await callback.message.edit_text(text="✅ Вы уже в канале!", parse_mode=ParseMode.HTML)
            await callback.answer("Вы уже участник канала")
            return

        # --- Прочие ошибки ---
        logger.error(f"Ошибка при одобрении заявки user={user_id}: {err_msg}")
        await callback.message.edit_text(text="Ошибка одобрения заявки\n"
                                              "ваша заявка не найдена", parse_mode=ParseMode.HTML)
        await callback.answer("Ошибка")



@bot_router.chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION))
async def handle_user_left_channel(event: ChatMemberUpdated):
    user_id = event.from_user.id
    user_name = event.from_user.first_name
    chat_id = event.chat.id
    logger.info(f"📤 Пользователь {user_id} ({user_name}) отписался от канала {event.chat.first_name}")
    db = SessionLocal()
    try:
        deleted_count = db.query(PendingRequest).filter(
            PendingRequest.user_id == user_id,
            PendingRequest.chat_id == chat_id
        ).delete()
        db.commit()
        if deleted_count > 0:
            logger.info(f"🗑️ Удалено {deleted_count} pending-запрос(ов) для пользователя {user_id} из чата {chat_id}")
        unsubscribe_message = db.query(Message).filter(Message.title == "Отписка от канала").first()
        if unsubscribe_message:
            text = entities_to_html(unsubscribe_message.text, unsubscribe_message.entities)
        else:
            text = (
                f"📤 {user_name}, вы отписались от нашего канала.\n\n"
                f"Если это произошло случайно, вы можете подписаться снова."
            )
        await event.bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
        logger.info(f"✅ Сообщение об отписке отправлено пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при обработке отписки пользователя {user_id}: {e}")
        db.rollback()
    finally:
        db.close()

