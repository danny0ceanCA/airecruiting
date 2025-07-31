import os
import redis
from rq import Worker, Queue

# Grab your Redis URL from the environment
redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise RuntimeError("Missing REDIS_URL")

# Connect to Redis
# RQ expects raw bytes, so disable automatic response decoding
redis_client = redis.Redis.from_url(redis_url)
queue = Queue(connection=redis_client)
Worker([queue], connection=redis_client).work()
