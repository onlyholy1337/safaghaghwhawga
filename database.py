# database.py

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import (BigInteger, String, Text, ForeignKey, Integer, DECIMAL,
                        JSON as SA_JSON, DateTime, func, PrimaryKeyConstraint)
from typing import List
from datetime import datetime

from config import settings

engine = create_async_engine(settings.db_dsn, echo=True)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    full_name: Mapped[str] = mapped_column(String(150))
    role: Mapped[str] = mapped_column(String(50), default='client')
    master_profile: Mapped["MasterProfile"] = relationship(back_populates="user")


class MasterProfile(Base):
    __tablename__ = 'master_profiles'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    description: Mapped[str] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=True)
    social_links: Mapped[List[dict]] = mapped_column(SA_JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    rating: Mapped[float] = mapped_column(DECIMAL(3, 2), nullable=True, default=0.0)
    user: Mapped["User"] = relationship(back_populates="master_profile")
    works: Mapped[List["TattooWork"]] = relationship(back_populates="master")


class Category(Base):
    __tablename__ = 'categories'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class TattooWork(Base):
    __tablename__ = 'tattoo_works'
    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey('master_profiles.id'))
    category_id: Mapped[int] = mapped_column(ForeignKey('categories.id'))
    image_file_id: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[int] = mapped_column(DECIMAL(10, 2))
    status: Mapped[str] = mapped_column(String(50), default='pending_payment')
    likes_count: Mapped[int] = mapped_column(Integer, default=0)
    invoice_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    master: Mapped["MasterProfile"] = relationship(back_populates="works")
    category: Mapped["Category"] = relationship()
    comments: Mapped[List["Comment"]] = relationship(back_populates="work", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = 'reviews'
    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey('tattoo_works.id'), nullable=True)
    master_id: Mapped[int] = mapped_column(ForeignKey('master_profiles.id'))
    client_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    admin_reply: Mapped[str] = mapped_column(Text, nullable=True)


class Like(Base):
    __tablename__ = 'likes'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    work_id: Mapped[int] = mapped_column(ForeignKey('tattoo_works.id'))

    __table_args__ = (
        PrimaryKeyConstraint('user_id', 'work_id'),
    )


# --- НОВАЯ ТАБЛИЦА ДЛЯ КОММЕНТАРИЕВ ---
class Comment(Base):
    __tablename__ = 'comments'
    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey('tattoo_works.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    work: Mapped["TattooWork"] = relationship(back_populates="comments")
    user: Mapped["User"] = relationship()


class BotSettings(Base):
    __tablename__ = 'bot_settings'
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_setting(session: AsyncSession, key: str, default: Optional[str] = None) -> Optional[str]:
    setting = await session.get(BotSettings, key)
    return setting.value if setting else default
