import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# Load .env file from project root
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://chintugoddanti@localhost:5432/patchwork"
)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
