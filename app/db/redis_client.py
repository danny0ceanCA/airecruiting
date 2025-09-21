import redis
from rq import Queue

from app.core.config import REDIS_URL

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
rq_redis_client = redis.Redis.from_url(REDIS_URL)


def get_queue() -> Queue:
    return Queue(connection=rq_redis_client)
