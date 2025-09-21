from app.core.config import NURSING_FEEDS
from app.db.redis_client import redis_client

def all_rss_feeds() -> dict[str, str]:
    """Return mapping of all configured RSS feeds."""
    feeds = {}
    for key in redis_client.scan_iter("rss_feed:*"):
        url = redis_client.get(key)
        if url is not None:
            name = key.split("rss_feed:", 1)[1]
            feeds[name] = url
    for n, u in NURSING_FEEDS.items():
        feeds.setdefault(n, u)
    return feeds
