import redis
import time
import json
from db import SessionLocal
from models import Job

redis_client=redis.Redis(
    host="localhost",
    port=6379,
    db=0,
    decode_responses=True
)

JOB_QUEUE = "job_queue"

def execution(job):
    print(f"Start execution {job['id']}", flush=True)
    if job.get('title') == 'fail':
        raise Exception("forced error")
    time.sleep(2)
    print(f"Complete exection {job['id']}", flush=True)

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

        try:
            job = json.loads(job_str)
        except:
            print("[ERROR] Invalid job JSON")
            continue       
        
        job_id = job["id"]

        db = SessionLocal()
        updated = db.query(Job).filter(
            Job.id == job_id,
            Job.status.in_(["queued", "failed"])
        ).update({
            "status": "processing"}, 
            synchronize_session=False
            )

        db.commit()

        if updated == 0:
            db.close()
            continue

        job_obj = db.query(Job).filter(Job.id == job_id).first()
        if not job_obj:
            print(f"[WARNING] Missing DB job for id={job_id}")
            db.close()
            continue

        try:
            # db.execute(
            #     "UPDATE jobs SET status = 'processing', updated_at = NOW() where id=%s", (job_id,)
            # )
            execution(job)
            # db.execute(
            #     "UPDATE jobs SET status = 'completed', updated_at = NOW() where id=%s", (job_id,)
            # )
            job_obj.status = "completed"
            db.commit()
            
        except Exception as e:
            # db.execute(
            #     "UPDATE jobs SET status = 'failed', retries= retries+1, updated_at = NOW() where id=%s", (job_id,)
            # )
            db.rollback()

            job_obj = db.query(Job).filter(Job.id == job_id).first()

            job_obj.status = "failed"
            job_obj.retries += 1

            if job_obj.retries >= 5:
                job_obj.status = "dead"
                db.commit()
            else:
                db.commit()
                delay = min(2 ** job_obj.retries, 300)
                print(f"Retrying in {delay} seconds", flush=True)
                redis_client.zadd(JOB_QUEUE, {job_str: time.time() + delay})

        finally:
            db.close()


if __name__ == "__main__":
    print("initialization...")
    worker()
