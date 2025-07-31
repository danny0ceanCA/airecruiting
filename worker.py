import os
import redis
from rq import Worker, Queue

# Grab your Redis URL from the environment
redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise RuntimeError("Missing REDIS_URL")

# Connect to Redis
redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
queue = Queue(connection=redis_client)
Worker([queue], connection=redis_client).work()
