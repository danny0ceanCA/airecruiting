import os
import redis
from rq import Worker, Queue
from rq.connections import Connection

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise RuntimeError("Missing REDIS_URL")

redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
queue = Queue(connection=redis_client)

with Connection(redis_client):
    worker = Worker([queue.name])
    worker.work()

redis_url = os.getenv("REDIS_URL")
if not redis_url:
    raise RuntimeError("Missing REDIS_URL")

redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
queue = Queue(connection=redis_client)

with Connection(redis_client):
    worker = Worker([queue.name])
    worker.work()
