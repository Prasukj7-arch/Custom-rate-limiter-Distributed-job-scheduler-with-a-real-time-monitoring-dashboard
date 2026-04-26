import redis
import time
import json

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
        now = time.time()
        jobs = redis_client.zrangebyscore(
            JOB_QUEUE,
            '-inf',
            now,
            start=0,
            num=1
        )
        if not jobs:
            time.sleep(1)
            continue

        job_str = jobs[0]
        job = json.loads(job_str)
        redis_client.zrem(JOB_QUEUE, job_str)

        execution(job)



if __name__ == "__main__":
    print("initialization...")
    worker()
