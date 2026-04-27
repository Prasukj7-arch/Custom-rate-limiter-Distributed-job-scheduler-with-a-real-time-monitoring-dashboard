import redis
import time
import json
from db import SessionLocal
redis_client=redis.Redis(
    host="localhost",
    port=6379,
    db=0,
    decode_responses=True
)

JOB_QUEUE = "job_queue"

def execution(job):
    print(f"Start execution {job['id']}")
    time.sleep(2)
    print(f"Complete exection {job['id']}")

def worker():
    while True:
        result = redis_client.zpopmin(JOB_QUEUE, count=1)

        if not result:
            time.sleep(1)
            continue

        job_str,score = result[0]
        now = time.time()

        if score>now:
            redis_client.zadd(JOB_QUEUE, {job_str:score})
            time.sleep(2)
            continue

        job = json.loads(job_str)
        job_id = job["id"]

        db = SessionLocal()
        try:
            db.execute(
                "UPDATE jobs SET status = 'processing', updated_at = NOW() where id=%s", (job_id,)
            )
            db.commit()
            execution(job)
            db.execute(
                "UPDATE jobs SET status = 'completed', updated_at = NOW() where id=%s", (job_id,)
            )
            db.commit()
            
        except Exception as e:
            db.execute(
                "UPDATE jobs SET status = 'failed', retries= retries+1, updated_at = NOW() where id=%s", (job_id,)
            )
            db.commit()
            redis_client.zadd(JOB_QUEUE, {job_str:time.time()+5})

        finally:
            db.close()

if __name__ == "__main__":
    print("initialization...")
    worker()
