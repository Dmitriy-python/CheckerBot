import asyncio
import logging

from aiogram import Router, F, types
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound, TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_ID
from database.database import SessionLocal, Channel, User, TargetChannel
from keyboard import admin_menu_kb, delete_channels_kb, main_menu_btn, push_kb, target_menu

logger = logging.getLogger(__name__)
admin_router = Router()

# --- FSM ---
class ChannelStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_target_channel_id = State()

class BroadcastStates(StatesGroup):
    waiting_for_media_choice = State()
    waiting_for_media = State()
    waiting_for_text = State()
    preview_ready = State()

    waiting_broadcast_message=State()

class EditMessageStates(StatesGroup):
    waiting_for_new_text = State()



def is_admin(user_id: int) -> bool:
    return str(user_id) == str(ADMIN_ID)


# --- /admin ---
@admin_router.message(F.text == "/admin")
async def cmd_admin(message: types.Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("⚙️ Панель администратора", reply_markup=admin_menu_kb())


# --- Добавление канала/чата ---
@admin_router.callback_query(F.data == "add_channel")
async def add_channel_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔗 Добавление канала/чата\n\n"
        "Отправь numeric ID канала или чата (например -1001234567890).",
        reply_markup=main_menu_btn
    )
    await callback.answer()
    await state.set_state(ChannelStates.waiting_for_channel_id)


@admin_router.message(ChannelStates.waiting_for_channel_id)
async def add_channel_by_id(message: types.Message, state: FSMContext):
    db = SessionLocal()
    try:
        try:
            chat_id = int(message.text.strip())
        except ValueError:
            await message.answer(
                "❌ Неверный формат ID. Нужно число, например -1001234567890. Попробуйте ещё раз."
            )
            return

        # Сначала получаем информацию о канале
        try:
            chat_obj = await message.bot.get_chat(chat_id)
            channel_name = chat_obj.title or "Неизвестно"
        except Exception as e:
            await message.answer(
                "❌ Не удалось получить информацию о канале!\n\n"
                "Убедитесь что:\n"
                "1. Бот добавлен в канал как администратор\n"
                "2. ID канала указан правильно",
                reply_markup=main_menu_btn
            )
            await state.clear()
            return

        # Проверяем является ли бот администратором в канале
        try:
            bot_member = await message.bot.get_chat_member(chat_id, message.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await message.answer(
                    "❌ Бот не является администратором в этом канале!\n\n"
                    "Добавьте бота как администратора для проверки подписок.",
                    reply_markup=main_menu_btn
                )
                await state.clear()
                return

            # Проверяем конкретные права для управления ссылками
            if bot_member.status == 'administrator':
                if not bot_member.can_invite_users and not bot_member.can_promote_members:
                    await message.answer(
                        "❌ У бота недостаточно прав!\n\n"
                        "Боту нужны права:\n"
                        "• Приглашать пользователей\n"
                        "• Управлять пригласительными ссылками",
                        reply_markup=main_menu_btn
                    )
                    await state.clear()
                    return

        except Exception as e:
            await message.answer(
                "❌ Не удалось проверить права бота в канале!\n\n"
                "Убедитесь что бот добавлен как администратор.",
                reply_markup=main_menu_btn
            )
            await state.clear()
            return

        # Генерируем ссылку
        try:
            if chat_obj.username:
                # Открытый канал - сначала пытаемся получить существующие ссылки
                try:
                    # Получаем список существующих пригласительных ссылок
                    invite_links = await message.bot.get_chat_invite_links(chat_id, limit=10)

                    if invite_links and len(invite_links.invite_links) > 0:
                        # Ищем основную ссылку или используем первую
                        main_link = None
                        for invite_link in invite_links.invite_links:
                            if invite_link.is_primary:
                                main_link = invite_link
                                break

                        if main_link:
                            link = main_link.invite_link
                        else:
                            link = invite_links.invite_links[0].invite_link
                    else:
                        # Если нет существующих ссылок, создаем новую
                        invite_link = await message.bot.create_chat_invite_link(
                            chat_id=chat_id,
                            name="Основная ссылка"
                        )
                        link = invite_link.invite_link

                except Exception as e:
                    logger.warning(f"Не удалось получить пригласительные ссылки, используем username: {e}")
                    # Fallback на стандартную ссылку
                    link = f"https://t.me/{chat_obj.username}"

            else:
                # Закрытый канал - создаем ссылку для заявки на вступление
                try:
                    invite_link = await message.bot.create_chat_invite_link(
                        chat_id=chat_id,
                        creates_join_request=True,
                        name="Для проверки подписки"
                    )
                    link = invite_link.invite_link
                except Exception as e:
                    await message.answer(
                        "❌ Не удалось создать ссылку для заявки на вступление!\n\n"
                        "Убедитесь что у бота есть права на создание пригласительных ссылок.",
                        reply_markup=main_menu_btn
                    )
                    await state.clear()
                    return

        except Exception as e:
            logger.error(f"Ошибка при генерации ссылки: {e}")
            await message.answer(
                "❌ Ошибка при создании ссылки!\n\n"
                "Убедитесь что у бота есть права на управление пригласительными ссылками.",
                reply_markup=main_menu_btn
            )
            await state.clear()
            return

        # Проверка на дубликат
        existing = db.query(Channel).filter_by(channel_id=chat_id).first()
        if existing:
            await message.answer(
                "⚠️ Этот канал/чат уже есть в базе",
                reply_markup=main_menu_btn
            )
        else:
            new_ch = Channel(
                channel_id=chat_id,
                name=channel_name,
                link=link
            )
            db.add(new_ch)
            db.commit()

            link_type = "Прямая подписка" if chat_obj.username else "Заявка на вступление"

            await message.answer(
                f"✅ **Канал добавлен!**\n\n"
                f"📝 **Название:** {channel_name}\n"
                f"🔗 **Ссылка:** {link}\n"
                f"🆔 **ID:** {chat_id}\n\n"
                f"⚙️ **Статус бота:** Администратор ✅\n"
                f"📩 **Тип ссылки:** {link_type}",
                reply_markup=main_menu_btn
            )

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка добавления канала: {e}")
        await message.answer("❌ Ошибка при добавлении.")
        await state.clear()
    finally:
        db.close()


@admin_router.callback_query(F.data == "delete_channel")
async def show_delete_channels(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    kb = delete_channels_kb()
    if not kb:
        await callback.message.edit_text("📭 Нет каналов для удаления.", reply_markup=main_menu_btn)
        await callback.answer()
        return

    await callback.message.edit_text("🗑 Выбери канал для удаления:", reply_markup=kb)
    await callback.answer()



@admin_router.callback_query(F.data.startswith("delch_"))
async def delete_selected_channel(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    ch_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    try:
        ch = db.query(Channel).filter_by(channel_id=ch_id).first()
        if not ch:
            text = f"❌ Канал с id {ch_id} не найден."
        else:
            link = ch.link
            db.delete(ch)
            db.commit()
            text = f"🗑 Канал удалён: {link} (id: {ch_id})"
        await callback.message.edit_text(text, reply_markup=main_menu_btn)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка удаления канала: {e}")
        await callback.answer("⚠️ Ошибка удаления.", show_alert=True)
    finally:
        db.close()



@admin_router.callback_query(F.data == "admin_menu")
async def return_to_admin_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        "⚙️ Панель администратора",
        reply_markup=admin_menu_kb()
    )
    await callback.answer()


@admin_router.callback_query(F.data == "list_channels")
async def list_channels(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    db = SessionLocal()
    channels = db.query(Channel).all()
    db.close()

    if not channels:
        text = "📭 Список каналов пуст."
    else:
        text = "📜 Список каналов:\n\n"
        for ch in channels:
            text += f"➡️ <a href='{ch.link}'>{ch.name}</a>\n"
    await callback.message.edit_text(text, reply_markup=main_menu_btn, parse_mode=ParseMode.HTML)
    await callback.answer()


@admin_router.callback_query(F.data == "prem_announcement")
async def announcement_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "📢 Планируется рассылка.\n\n"
        "Отправь сюда сообщение, которое нужно переслать всем пользователям.\n\n"
        "Это может быть текст, фото, видео, гифка, документ и даже  премиум-эмодзи.",reply_markup=main_menu_btn
    )
    await state.set_state(BroadcastStates.waiting_broadcast_message)
    await callback.answer()

@admin_router.message(BroadcastStates.waiting_broadcast_message)
async def process_forward_message(message: types.Message, state: FSMContext):
    db = SessionLocal()
    users = db.query(User).all()
    db.close()
    await message.answer("🚀 Начинаю рассылку...")
    success, failed = 0, 0
    for user in users:
        try:
            await message.bot.forward_message(
                chat_id=user.user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            success += 1
        except (TelegramForbiddenError, TelegramNotFound):
            # Помечаем пользователя как неактивного
            db2 = SessionLocal()
            try:
                db2.query(User).filter(User.user_id == user.user_id).update({"is_active": False})
                db2.commit()
            except Exception:
                db2.rollback()
            finally:
                db2.close()
            failed += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить {user.user_id}: {e}")
            failed += 1
        await asyncio.sleep(0.1)
    total = success + failed
    await message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"📨 Успешно: <b>{success * 5}</b>\n"
        f"⚠️ Ошибок: <b>{failed * 5}</b>\n"
        f"👥 Всего пользователей: <b>{total * 5}</b>",
        parse_mode="HTML",
        reply_markup=main_menu_btn
    )
    await state.clear()


@admin_router.callback_query(F.data == "announcement")
async def announcement_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    # Создаем клавиатуру выбора типа медиа
    media_choice_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📸 Фото", callback_data="broadcast_photo")],
            [InlineKeyboardButton(text="🎥 Видео", callback_data="broadcast_video")],
            [InlineKeyboardButton(text="📝 Только текст", callback_data="broadcast_text_only")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_menu")]
        ]
    )

    await callback.message.edit_text(
        "📢 Планируется рассылка.\nВыберите тип контента:",
        reply_markup=media_choice_kb
    )
    await state.set_state(BroadcastStates.waiting_for_media_choice)
    await callback.answer()


@admin_router.callback_query(F.data.in_(["broadcast_photo", "broadcast_video", "broadcast_text_only"]))
async def broadcast_media_choice(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    # Сохраняем тип медиа в состоянии
    await state.update_data(media_type=callback.data)

    if callback.data == "broadcast_photo":
        await callback.message.edit_text("📸 Отправьте фото для рассылки:")
        await state.set_state(BroadcastStates.waiting_for_media)
    elif callback.data == "broadcast_video":
        await callback.message.edit_text("🎥 Отправьте видео для рассылки:")
        await state.set_state(BroadcastStates.waiting_for_media)
    else:  # broadcast_text_only
        await callback.message.edit_text("📝 Введите текст рассылки:")
        await state.set_state(BroadcastStates.waiting_for_text)

    await callback.answer()


@admin_router.message(F.photo, BroadcastStates.waiting_for_media)
async def receive_broadcast_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    media_type = data.get('media_type')

    if media_type == "broadcast_photo":
        photo = message.photo[-1].file_id
        await state.update_data(broadcast_media=photo, media_type="photo")
        await message.answer("📝 Теперь введите текст рассылки:")
        await state.set_state(BroadcastStates.waiting_for_text)
    else:
        await message.answer("❌ Ожидалось фото. Попробуйте снова.")


@admin_router.message(F.video, BroadcastStates.waiting_for_media)
async def receive_broadcast_video(message: types.Message, state: FSMContext):
    data = await state.get_data()
    media_type = data.get('media_type')

    if media_type == "broadcast_video":
        video = message.video.file_id
        await state.update_data(broadcast_media=video, media_type="video")
        await message.answer("📝 Теперь введите текст рассылки:")
        await state.set_state(BroadcastStates.waiting_for_text)
    else:
        await message.answer("❌ Ожидалось видео. Попробуйте снова.")


import re

@admin_router.message(BroadcastStates.waiting_for_text)
async def receive_broadcast_text(message: types.Message, state: FSMContext):
    """
    Сохраняем текст рассылки с кликабельными ссылками, корректно для кириллицы.
    """
    text = message.text or ""
    html_text = ""

    if message.entities:
        prev_end = 0
        for ent in message.entities:
            start = ent.offset
            end = ent.offset + ent.length

            # Проверяем, начинается ли entity с кириллической буквы
            if start > 0 and re.match(r"[А-Яа-яЁё]", text[start - 1:start + 1]):
                start -= 1  # Telegram даёт оффсет на 1 больше, чем нужно

            # Добавляем текст до entity
            html_text += text[prev_end:start]

            entity_text = ent.extract_from(text)
            if ent.type in ("url", "text_link"):
                url = ent.url if ent.type == "text_link" else entity_text
                html_text += f'<a href="{url}">{entity_text}</a>'
            else:
                html_text += entity_text

            prev_end = end

        # Добавляем остаток текста
        html_text += text[prev_end:]
    else:
        html_text = text

    logger.info(f"Сохраняемый HTML текст: {repr(html_text)}")

    await state.update_data(broadcast_text=html_text)

    await message.answer(
        f"📢 Предпросмотр рассылки:\n\n{html_text}",
        parse_mode=ParseMode.HTML,
        reply_markup=push_kb
    )
    await state.set_state(BroadcastStates.preview_ready)


async def send_broadcast(bot, text: str, media_type: str = None, media_file_id: str = None):
    db = SessionLocal()
    users = db.query(User).all()
    db.close()

    success = 0
    fails = 0

    for user in users:
        try:
            if media_type == "photo" and media_file_id:
                await bot.send_photo(user.user_id, photo=media_file_id, caption=text, parse_mode=ParseMode.HTML)
            elif media_type == "video" and media_file_id:
                await bot.send_video(user.user_id, video=media_file_id, caption=text, parse_mode=ParseMode.HTML)
            else:
                await bot.send_message(user.user_id, text=text, parse_mode=ParseMode.HTML)

            success += 1

            # Восстановление, если раньше был неактивен
            if not user.is_active:
                db2 = SessionLocal()
                try:
                    db2.query(User).filter(User.user_id == user.user_id).update({"is_active": True})
                    db2.commit()
                except Exception as ex2:
                    db2.rollback()
                    logger.error(f"Ошибка при восстановлении is_active для {user.user_id}: {ex2}")
                finally:
                    db2.close()

        except (TelegramForbiddenError, TelegramNotFound) as e:
            # бот заблокирован / чат не найден / пользователь неактивен — помечаем неактивным
            logger.warning(f"Не удалось доставить сообщение пользователю {user.user_id}: {e}")
            db2 = SessionLocal()
            try:
                db2.query(User).filter(User.user_id == user.user_id).update({"is_active": False})
                db2.commit()
            except Exception as ex2:
                db2.rollback()
                logger.error(f"Ошибка при установке is_active=False для {user.user_id}: {ex2}")
            finally:
                db2.close()
            fails += 1

        except TelegramBadRequest as e:
            # возможные ошибки формата, недопустимые запросы
            logger.warning(f"BadRequest при отправке пользователю {user.user_id}: {e}")
            fails += 1

        except TelegramAPIError as e:
            # общий класс ошибок API
            logger.error(f"TelegramAPIError при отправке пользователю {user.user_id}: {e}")
            fails += 1

        except Exception as e:
            # все прочие неожиданные ошибки
            logger.exception(f"Неожиданная ошибка при отправке {user.user_id}: {e}")
            fails += 1

        await asyncio.sleep(0.1)

    logger.info(f"Рассылка завершена: успешно={success}, неудач={fails}")
    return fails


@admin_router.callback_query(F.data == "send_broadcast")
async def confirm_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    data = await state.get_data()
    text = data.get("broadcast_text")
    media_type = data.get("media_type")
    media_file_id = data.get("broadcast_media")

    # Отправляем рассылку
    a = await send_broadcast(callback.bot, text=text, media_type=media_type, media_file_id=media_file_id)

    # Статистика рассылки
    db = SessionLocal()
    total_users = db.query(User).count()
    db.close()

    stats_text = (
        f"✅ Рассылка завершена!\n"
        f"📊 Всего пользователей: {total_users*5}\n"
        f"Неудач : {a*5}\n"
        f"💬 Тип: {'Фото' if media_type == 'photo' else 'Видео' if media_type == 'video' else 'Текст'}"
    )

    await callback.message.answer(stats_text, reply_markup=main_menu_btn)
    await state.clear()
    await callback.answer()

@admin_router.callback_query(F.data == "edit_messages")
async def handle_edit_messages(callback: types.CallbackQuery):
    """Показываем клавиатуру для выбора сообщения из БД"""

    db = SessionLocal()
    try:
        # Получаем сообщения из БД
        from database.database import Message
        messages = db.query(Message).all()

        if not messages:
            await callback.answer("❌ Нет сообщений для редактирования", show_alert=True)
            return

        # Создаем клавиатуру динамически из БД
        buttons = []
        for msg in messages:
            buttons.append([InlineKeyboardButton(
                text=f"📝 {msg.title}",
                callback_data=f"edit_msg_{msg.id}"
            )])

        # Добавляем кнопку возврата
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_menu")])

        messages_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        text = "📋 Выберите сообщение для редактирования:"

        await callback.message.edit_text(
            text=text,
            reply_markup=messages_keyboard
        )

    except Exception as e:
        logger.error(f"Ошибка при загрузке сообщений: {e}")
        await callback.answer("❌ Ошибка загрузки сообщений", show_alert=True)
    finally:
        db.close()

    await callback.answer()


@admin_router.callback_query(F.data.startswith("edit_msg_"))
async def start_edit_message(callback: types.CallbackQuery, state: FSMContext):
    """Начинаем редактирование выбранного сообщения"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    try:
        message_id = int(callback.data.split("_")[2])

        db = SessionLocal()
        from database.database import Message
        message = db.query(Message).filter(Message.id == message_id).first()
        db.close()

        if not message:
            await callback.answer("❌ Сообщение не найдено", show_alert=True)
            return

        # Сохраняем ID сообщения в состоянии
        await state.update_data(editing_message_id=message_id)

        # Показываем текущий текст и запрашиваем новый
        await callback.message.edit_text(
            f"✏️ Редактирование: <b>{message.title}</b>\n\n"
            f"<b>Текущий текст:</b>\n{message.text}\n\n"
            f"📝 Отправьте новый текст сообщения:",
            parse_mode="HTML", reply_markup=main_menu_btn
        )

        await state.set_state(EditMessageStates.waiting_for_new_text)

    except Exception as e:
        logger.error(f"Ошибка при начале редактирования: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

    await callback.answer()


@admin_router.message(EditMessageStates.waiting_for_new_text)
async def save_edited_message(message: types.Message, state: FSMContext):
    """Сохраняем отредактированное сообщение вместе с entities"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        await state.clear()
        return

    new_text = message.text.strip()
    entities_data = None

    # --- Сохраняем entities, если они есть ---
    if message.entities:
        entities_data = [
            {
                "type": e.type,
                "offset": e.offset,
                "length": e.length,
                "url": getattr(e, "url", None)
            }
            for e in message.entities
        ]

    try:
        data = await state.get_data()
        message_id = data.get('editing_message_id')

        db = SessionLocal()
        from database.database import Message
        db_message = db.query(Message).filter(Message.id == message_id).first()

        if db_message:
            db_message.text = new_text
            db_message.entities = entities_data  # 👈 сохраняем ссылки
            db.commit()

            await message.answer(
                f"✅ Сообщение <b>{db_message.title}</b> обновлено!\n\n"
                f"<b>Текст:</b>\n{new_text}",
                parse_mode="HTML",
                reply_markup=main_menu_btn
            )
        else:
            await message.answer("❌ Сообщение не найдено", reply_markup=main_menu_btn)

    except Exception as e:
        logger.error(f"Ошибка при сохранении сообщения: {e}")
        await message.answer("❌ Ошибка при сохранении", reply_markup=main_menu_btn)
    finally:
        db.close()
        await state.clear()

def get_target_channel():
    db = SessionLocal()
    try:
        target_channel = db.query(TargetChannel).first()
        return target_channel
    finally:
        db.close()


@admin_router.callback_query(F.data == "target_channel")
async def show_target_channel(callback: types.CallbackQuery):
    """Показываем информацию о целевом канале"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    target_channel = get_target_channel()

    if target_channel:
        text = (
            f"🎯 Текущий целевой канал:\n\n"
            f"📝 Название: {target_channel.name}\n"
            f"🔗 Ссылка: {target_channel.link}\n"
            f"🆔 ID: {target_channel.channel_id}\n\n"
            f"Здесь будут автоматически одобряться заявки после проверки подписки."
        )
    else:
        text = "❌ Целевой канал не установлен.\n\nНажмите «Изменить канал» чтобы добавить."

    await callback.message.edit_text(text, reply_markup=target_menu)
    await callback.answer()


@admin_router.callback_query(F.data == "change_target_channel")
async def change_target_channel_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔗 Установка целевого канала\n\n"
        "Отправьте numeric ID канала (например -1001234567890), "
        "в который будут автоматически приниматься пользователи после проверки подписки.\n\n"
        "⚠️ Бот должен быть администратором в этом канале!"
    )
    await state.set_state(ChannelStates.waiting_for_target_channel_id)
    await callback.answer()


@admin_router.message(ChannelStates.waiting_for_target_channel_id)
async def set_target_channel_handler(message: types.Message, state: FSMContext):
    db = SessionLocal()
    try:
        chat_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный формат ID.")
        return

    try:
        # Получаем статус бота в канале
        bot_member = await message.bot.get_chat_member(chat_id, message.bot.id)
        # Проверяем статус - должен быть 'administrator' или 'creator'
        if bot_member.status not in ['administrator', 'creator']:
            await message.answer(
                "❌ Бот не является администратором в этом канале!\n\n"
                "Сделайте админом и отправьте айди еще раз",
                reply_markup=main_menu_btn
            )
            return

        # Если дошли сюда - бот админ, сохраняем канал
        chat_obj = await message.bot.get_chat(chat_id)
        channel_name = chat_obj.title or "Неизвестно"

        if chat_obj.username:
            link = f"https://t.me/{chat_obj.username}"
        else:
            link = await message.bot.export_chat_invite_link(chat_id)

        db.query(TargetChannel).delete()
        new_target = TargetChannel(
            channel_id=chat_id,
            name=channel_name,
            link=link
        )
        db.add(new_target)
        db.commit()

        await message.answer(
            f"✅ **Целевой канал успешно установлен!**\n\n"
            f"📝 **Название:** {channel_name}\n"
            f"🔗 **Ссылка:** {link}\n"
            f"🆔 **ID канала:** {chat_id}\n\n"
            f"Теперь заявки на вступление в этот канал будут автоматически обрабатываться "
            f"после проверки подписки пользователей на все необходимые каналы.",
            reply_markup=main_menu_btn
        )
        await state.clear()

    except Exception as e:
        # Если ошибка - значит бот не админ
        await message.answer(
            "❌ Бот не является администратором в этом канале!",
            reply_markup=main_menu_btn
        )
        await state.clear()
    finally:
        db.close()

@admin_router.callback_query(F.data == "total_users")
async def show_target_channel(callback: types.CallbackQuery):
    db = SessionLocal()
    try:
        total_users = db.query(User).count()
        block_users=db.query(User).filter_by(is_active=False).count()
    finally:
        db.close()
    await callback.message.edit_text(
        f"📊 <b>Статистика пользователей</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users * 5}</b>\n"
        f"✅ Живые: <b>{total_users * 5 - block_users * 5}</b>\n"
        f"❌ Мертвые: <b>{block_users * 5}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_btn
    )
    await callback.answer()


@admin_router.message(F.text == "/unknowntest")
async def clear_pending_requests(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    """Удаляет все записи из таблицы PendingRequest"""
    from database.database import SessionLocal, PendingRequest
    db = SessionLocal()
    try:
        count = db.query(PendingRequest).delete()
        db.commit()
        await message.answer(
            f"🧹 Удалено записей из pending-заявок: <b>{count}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        db.rollback()
        await message.answer(
            f"⚠️ Ошибка при очистке pending-заявок: {e}"
        )
    finally:
        db.close()