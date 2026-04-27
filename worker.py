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
        
        try:
            execution(job)
        except Exception as e:
            print(f"there is an errror {str(e)}")
            redis_client.zadd(JOB_QUEUE, {job_str:time.time()+5})

if __name__ == "__main__":
    print("initialization...")
    worker()
