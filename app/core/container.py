from typing import Dict, Type
from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings
from app.infrastructure.database import Base

class Container(containers.DeclarativeContainer):
    """Dependency injection container"""

    # Database configuration
    db_engine = providers.Singleton(
        create_async_engine,
        settings.SQLALCHEMY_DATABASE_URI,
        echo=settings.DB_ECHO_LOG,
        future=True
    )

    db_session_factory = providers.Singleton(
        async_sessionmaker,
        db_engine,
        expire_on_commit=False,
        class_=AsyncSession
    )

    # Repositories
    repositories = providers.Dict()

    # Services
    services = providers.Dict()

    # Add repositories and services here as they are created
    # Example:
    # repositories = providers.Dict(
    #     user=providers.Factory(UserRepository, session=db_session_factory),
    #     product=providers.Factory(ProductRepository, session=db_session_factory)
    # )

    # services = providers.Dict(
    #     user=providers.Factory(UserService, repository=repositories.user),
    #     product=providers.Factory(ProductService, repository=repositories.product)
    # )

    @classmethod
    def register_repository(cls, name: str, repository_class: Type):
        """Register a repository in the container"""
        cls.repositories[name] = providers.Factory(
            repository_class,
            session=cls.db_session_factory
        )

    @classmethod
    def register_service(cls, name: str, service_class: Type):
        """Register a service in the container"""
        cls.services[name] = providers.Factory(
            service_class,
            repository=cls.repositories[name]
        )

    @classmethod
    async def init_resources(cls):
        """Initialize resources"""
        async with cls.db_engine() as engine:
            await Base.metadata.create_all(engine)

    @classmethod
    async def close_resources(cls):
        """Close resources"""
        await cls.db_engine().dispose()

# Create container instance
container = Container()
