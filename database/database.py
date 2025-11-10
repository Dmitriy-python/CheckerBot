import logging
from sqlalchemy import (
    Column, Integer, String, BigInteger, create_engine, Boolean, JSON
)
from sqlalchemy.orm import declarative_base, sessionmaker
from config import DATABASE_URL

# Логгер
logger = logging.getLogger(__name__)

Base = declarative_base()



class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(100), nullable=False, server_default="None")  # @username
    first_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class PendingRequest(Base):
    __tablename__ = "pending_requests"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)

class Channel(Base):
    __tablename__ = 'channels'
    id = Column(Integer, primary_key=True)
    channel_id = Column(BigInteger, unique=True, nullable=False)
    name = Column(String, nullable=True, server_default="Неизвестно")
    link = Column(String(255), nullable=False)



class TargetChannel(Base):
    __tablename__ = 'target_channels'
    id = Column(Integer, primary_key=True)
    channel_id = Column(BigInteger, unique=True, nullable=False)
    name = Column(String, nullable=True, server_default="Неизвестно")
    link = Column(String(255), nullable=False)



class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    text = Column(String, nullable=False)
    entities = Column(JSON, nullable=True)


engine = create_engine(DATABASE_URL, echo=False)


def init_db():
    try:
        Base.metadata.create_all(engine)
        logger.info("✅ Таблицы базы данных успешно созданы или уже существуют")
        return engine
    except Exception as e:
        logger.error(f"❌ Ошибка создания таблиц: {e}")
        raise

SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_sample_messages():
    """Добавляем стандартные сообщения при первом запуске"""
    db = SessionLocal()
    try:
        # Проверяем, есть ли уже сообщения
        existing_messages = db.query(Message).count()
        if existing_messages == 0:
            sample_messages = [
                Message(
                    title="Самое первое с командой /start",
                    text="отправьте команду /start"
                ),
                Message(
                    title="Приветственное",
                    text="👋 Добро пожаловать в наш бот!\n\nМы рады видеть вас здесь!"
                ),
                Message(
                    title="Ошибка проверки",
                    text="❌ Не удалось проверить подписку.\n\nПожалуйста, убедитесь что вы подписались на все каналы и попробуйте снова."
                ),
                Message(
                    title="Подписка на канал",
                    text="✅ Вы успешно подписались на канал!\n\nТеперь у вас есть доступ ко всем материалам."
                ),
                Message(
                    title="Отписка от канала",
                    text="📤 Вы отписались от канала.\n\nЕсли это произошло случайно, вы можете подписаться снова."
                )
            ]

            db.add_all(sample_messages)
            db.commit()
            logger.info("✅ Добавлены стандартные сообщения в БД")
        else:
            logger.info("✅ Сообщения уже существуют в БД")

    except Exception as e:
        logger.error(f"❌ Ошибка добавления сообщений: {e}")
        db.rollback()
    finally:
        db.close()
