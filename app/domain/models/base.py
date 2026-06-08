from datetime import datetime
from sqlalchemy import Column, Integer, DateTime
from app.core.database import Base

class BaseModel(Base):
    __abstract__ = True

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id})>"
