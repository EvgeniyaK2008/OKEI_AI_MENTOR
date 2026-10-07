from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import create_engine
from config.config import Config
from sqlalchemy.orm import DeclarativeBase

cfg = Config.load()

DATABASE_URL = (
    f"postgresql+psycopg://{cfg.db_user}:{cfg.db_password}@{cfg.db_host}:{cfg.db_port}/{cfg.db_name}"
)

sync_engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

async_engine = create_async_engine(DATABASE_URL, echo=True)

async_session_factory = async_sessionmaker(
    bind=async_engine, 
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with async_session_factory() as session:
        yield session
