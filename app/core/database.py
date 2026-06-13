from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings


def _normalize_asyncpg_url(db_url: str) -> str:
    """Normalize Postgres URLs for asyncpg.

    asyncpg doesn't accept libpq-style query params like `sslmode`.
    Neon URLs often include `sslmode=require` and/or `channel_binding=require`.
    """
    # Neon / many providers hand out libpq-style URLs like:
    #   postgresql://.../?sslmode=require&channel_binding=require
    # For the async engine we need an async dialect.
    if db_url.startswith("postgresql://"):
        db_url = "postgresql+asyncpg://" + db_url[len("postgresql://") :]
    elif db_url.startswith("postgres://"):
        db_url = "postgresql+asyncpg://" + db_url[len("postgres://") :]

    if "+asyncpg" not in db_url:
        return db_url

    parts = urlsplit(db_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))

    if "ssl" not in query and "sslmode" in query:
        sslmode = (query.pop("sslmode") or "require").lower()
        # asyncpg expects `ssl` (bool or context); SQLAlchemy passes this as kwarg.
        # Using string values like "require" works for common setups.
        query["ssl"] = "require" if sslmode in {"require", "verify-full", "verify-ca"} else "require"

    # asyncpg doesn't support channel_binding kwarg
    query.pop("channel_binding", None)

    new_query = urlencode(query)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))

# Create declarative base
Base = declarative_base()

# Create async engine with NullPool to prevent connection pooling issues
engine = create_async_engine(
    _normalize_asyncpg_url(settings.DATABASE_URL),
    echo=settings.DB_ECHO_LOG,
    future=True,
    poolclass=NullPool,  # Disable connection pooling
    pool_pre_ping=True
)

# Create async session factory with expire_on_commit=False
async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def get_db() -> AsyncSession:
    """Get database session"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
