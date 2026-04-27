from sqlalchemy import Column, String, func, Integer, JSON, DateTime
from sqlalchemy.orm import declarative_base
from db import engine

Base = declarative_base()

class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    type = Column(String)
    payload = Column(JSON)
    status = Column(String)
    retries = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

Base.metadata.create_all(bind=engine)

