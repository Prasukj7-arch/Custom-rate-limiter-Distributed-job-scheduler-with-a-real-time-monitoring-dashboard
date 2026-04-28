from fastapi import FastAPI # create web server
from pydantic import BaseModel
import logging
from fastapi import status
from fastapi import HTTPException
import redis 
import time
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
import json
from db import SessionLocal
from models import Job
from fastapi.responses import StreamingResponse
import asyncio
from fastapi.middleware.cors import CORSMiddleware


# Phase 3 where we built a custom token bucket but not being used in present.

# class TokenBucket:
#     def __init__ (self, token_capacity=5, refill_rate=1):
#         self.token_capacity = token_capacity
#         self.tokens = token_capacity
#         self.refill_rate = refill_rate
#         self.last_refill = time.time()

#     def consume_fill(self) -> bool: 
#         now = time.time()
#         time_elapsed = now - self.last_refill
#         self.tokens = min(self.token_capacity, self.tokens+time_elapsed*self.refill_rate)
#         self.last_refill = now
#         if(self.tokens>=1):
#             self.tokens -= 1
#             return True
#         return False

redis_client = redis.Redis(
    host='localhost',
    port=6379,
    db=0,
    decode_responses=True,
)

lua_script = """
    local key = KEYS[1]

    local capacity = tonumber(ARGV[1])
    local refill_rate = tonumber(ARGV[2])
    local current_time = tonumber(ARGV[3])

    local data = redis.call("HMGET", key, "tokens", "last_refill")
    local tokens = tonumber(data[1])
    local last_refill = tonumber(data[2])

    if tokens == nil then
        tokens = capacity
        last_refill = current_time
    end

    local time_elapsed = current_time - last_refill
    tokens = math.min(capacity, tokens+(time_elapsed * refill_rate))

    local allowed = 0
    if tokens>=1 then 
        tokens=tokens-1
        allowed = 1
    end

    redis.call("HMSET", key, "tokens",tokens, "last_refill", current_time)
    redis.call("EXPIRE", key, 60)
 
    
    return allowed
"""
rate_limiter = redis_client.register_script(lua_script)
logging.basicConfig(level=logging.INFO)

ROUTE_LIMITS = {
        "/login": (5, 1),
        "/upload-story": (10, 2),
}

METRICS = {
    "allowed": "metrics:allowed",
    "blocked": "metrics:blocked",
    "processed": "metrics:processed",
    "failed": "metrics:failed"
}

class RateLimiterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request:Request, call_next):
        if request.url.path.rstrip("/") in ["/health/redis", "/redis-test", "/metrics/stream"]:
            return await call_next(request)
        user = request.headers.get("user") or request.client.host
        key = f"rate_limiter:{user}:{request.url.path}"
        current_time = time.time()
       
        capacity, refill = ROUTE_LIMITS.get(request.url.path.rstrip("/"), (5,1))

        try:
            allowed = rate_limiter(
                keys = [key],
                args = [capacity,refill,current_time]
            )
        except Exception as e:
            logging.error(f"Rate limiter error: {str(e)}")
            return await call_next(request)

        if allowed == 0:
            logging.warning(f"[RATE_LIMIT] user={user} allowed=0 path={request.url.path}")
            redis_client.incr("metrics:blocked")
            return JSONResponse(
                status_code = 429,
                content = {"detail": "Too many requests"}
            )
        logging.info(f"[RATE_LIMIT] user={user} allowed=1 path={request.url.path}")
        redis_client.incr("metrics:allowed")
        response = await call_next(request)
        return response

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for demo (restrict later)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimiterMiddleware)
class LoginRequest(BaseModel):
    username: str
    password: str

class StoryUploadRequest(BaseModel):
    title: str
    content: str

# storeBucket = {}

@app.post("/login", status_code = status.HTTP_200_OK)
def login(data: LoginRequest):
    user = data.username
    # key = f"rate_limit:{user}"
    # current_time = time.time()

    # allowed = rate_limiter(
    #     keys = [key],
    #     args = [5,1,current_time]
    # )

    # if user not in storeBucket:
    #     storeBucket[user] = TokenBucket(5,1)

    logging.info(f"Login attempt: {data.username}")

    # bucket  = storeBucket[user]

    # if not allowed:
    #     logging.warning(f"Rate limit exceeded for {user}")
    #     raise HTTPException(
    #         status_code = 429,
    #         detail = "Too many requests"
    #     )
        
    # fastapi reads the JSON body, validates the data, coverts it in python object. (3 stages in one arguemnt entry above)
    return {
        "status": "success",
        "message": "login successful",
        "data": {"user": user}
    }
    
# This piece of code is used for testing whether redis is installed and running.
@app.get("/redis-test")
def redis_test():
    try:
        redis_client.set("name", "prasuk")
        value = redis_client.get("name")
        return{
            "status" : "success",
            "message" : "value stored and retrieved",
            "data" : {
                "redis_value" : value
            }
        }
    except Exception as e:
        return{
            "status" : "error",
            "message" : str(e)
        }

@app.get("/health/redis")
def redis_health():
    try:
        redis_client.ping()
        return{
            "status" : "healthy"
        }
    except Exception as e:
        logging.error(f"Redis error: {str(e)}")
        return{
            "status" : "unhealthy"
        }
        
# The below APIs are not being used currently
@app.post("/upload-story")
def upload_story(data: StoryUploadRequest):
    job = {
        "id" : str(time.time()),
        "type" : "upload_story",
        "title" : data.title,
        "content" : data.content,
        "create_at" : time.time()
    }
    job_id = job["id"]
    db = SessionLocal()

    job_obj = Job(
        id = job_id,
        type = "upload_story",
        payload = job,
        status = "queued"
    )
#    " db.execute(
#         """
#         INSERT INTO jobs(id, type, payload, status, created_at, updated_at) VALUES(%s, %s, %s, %s, NOW(), NOW())
#         """,
#         (job_id, "upload_story", json.dumps(job), "queued")
#     )"
    try:
        db.add(job_obj)
        db.commit()
    finally:
        db.close()

    redis_client.zadd(
        "job_queue",
        {
            json.dumps(job):time.time()
        }
    )

    return{
        "status": "success",
        "message": "story queued",
        "job_id": job_id
    }

@app.get("/jobs")
def story():
    response = redis_client.zrange("job_queue", 0, -1, withscores=True)
    return response

@app.post("/delayed-story-upload")
def delayed_story_upload(data: StoryUploadRequest):
    execution_time = time.time() + 5
    job = {
        "id" : str(time.time()),
        "type" : "upload_story",
        "title" : data.title,
        "content" : data.content,
        "create_at" : time.time()
    }

    db = SessionLocal()
    job_id = job["id"]

    job_obj = Job(
        id=job_id,
        type="upload_story",
        payload=job,
        status="queued"
    )
    try:
        db.add(job_obj)
        db.commit()

    finally:
        db.close()

    redis_client.zadd(
        "job_queue",
        {
            json.dumps(job):execution_time
        }
    )
    return {
        "status" : "resolved"
    }


# @app.get("/metrics/stream") 
# def metrics():
#     return {
#         "allowed": 10,
#         "blocked": 2,
#         "jobs_processed": 5
#     }
async def event_generator():
    try:
        while True:
            data = {
                "allowed": int(redis_client.get(METRICS["allowed"]) or 0),
                "blocked": int(redis_client.get(METRICS["blocked"]) or 0),
                "processed": int(redis_client.get(METRICS["processed"]) or 0),
                "failed": int(redis_client.get(METRICS["failed"]) or 0),
                "queue_depth": redis_client.zcard("job_queue")
            }

            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(2)

    except asyncio.CancelledError:
        print("SSE connection closed")


@app.get("/metrics/stream")
async def stream_metrics():
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )