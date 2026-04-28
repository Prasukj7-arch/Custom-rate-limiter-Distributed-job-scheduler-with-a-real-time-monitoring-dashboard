from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker 

DATABASE_URL = "postgresql://prasukjain@localhost:5432/jobs_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
