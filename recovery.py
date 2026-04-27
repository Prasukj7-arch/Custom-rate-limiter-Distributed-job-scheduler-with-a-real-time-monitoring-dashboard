from sqlalchemy import text, func
from db import SessionLocal
from models import Job
import time

def recover_stuck_jobs():
    db = SessionLocal()
    db.query(Job).filter(
        Job.status == "processing",
        Job.updated_at < func.now() - text("INTERVAL '5 minutes'")
    ).update({"status": "queued"})
    db.commit()
    db.close()

if __name__ == "__main__":
    print("Recovery service started...")
    while True:
        recover_stuck_jobs()
        time.sleep(60) 