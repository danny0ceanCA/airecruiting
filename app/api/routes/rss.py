import asyncio
import json
import re
from html import unescape

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import ADMIN_ROLES, NURSING_NEWS_CACHE_KEY, NURSING_NEWS_TTL, RSS_HEADERS
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db.redis_client import redis_client
from app.services.rss import all_rss_feeds

router = APIRouter()

logger = get_logger(__name__)


class RSSFeedRequest(BaseModel):
    name: str
    url: str


class UpdateRSSFeedRequest(BaseModel):
    url: str

@router.get("/rss-feeds")
def list_rss_feeds():
    feeds = [{"name": n, "url": u} for n, u in all_rss_feeds().items()]
    return {"feeds": feeds}

@router.post("/admin/rss-feeds")
def add_rss_feed(req: RSSFeedRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"rss_feed:{req.name}"
    if redis_client.exists(key):
        raise HTTPException(status_code=400, detail="Feed already exists")
    redis_client.set(key, req.url)
    return {"message": "Feed added"}

@router.put("/admin/rss-feeds/{name}")
def update_rss_feed(name: str, req: UpdateRSSFeedRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"rss_feed:{name}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Feed not found")
    redis_client.set(key, req.url)
    return {"message": "Feed updated"}

@router.delete("/admin/rss-feeds/{name}")
def delete_rss_feed(name: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = f"rss_feed:{name}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="Feed not found")
    redis_client.delete(key)
    return {"message": "Feed deleted"}

@router.get("/nursing-news")
async def nursing_news(force_refresh: bool = False):
    """Fetch and return articles from popular nursing RSS feeds."""
    import xml.etree.ElementTree as ET
    if not force_refresh:
        cached = redis_client.get(NURSING_NEWS_CACHE_KEY)
        if cached:
            try:
                return json.loads(cached)
            except Exception:
                pass

    feeds = all_rss_feeds()

    async with httpx.AsyncClient(timeout=10, headers=RSS_HEADERS) as client:
        tasks = [client.get(url) for url in feeds.values()]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for (name, _), resp in zip(feeds.items(), responses):
        if isinstance(resp, Exception):
            results.append({"source": name, "articles": [], "error": str(resp)})
            continue
        try:
            root = ET.fromstring(resp.text)
            articles = []
            for item in root.findall(".//item")[:5]:
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                summary = item.findtext("description") or item.findtext("summary") or item.findtext("content:encoded") or ""
                summary = unescape(re.sub("<.*?>", "", summary))

                image = None
                media = item.find('{http://search.yahoo.com/mrss/}content')
                if media is not None and media.get('url'):
                    image = media.get('url')
                if not image:
                    encl = item.find('enclosure')
                    if encl is not None and encl.get('url') and encl.get('type', '').startswith('image'):
                        image = encl.get('url')
                if not image:
                    desc = item.findtext('description') or ''
                    m = re.search(r"<img[^>]+src=['\"]([^'\"]+)['\"]", desc)
                    if m:
                        image = m.group(1)

                articles.append({
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "image": image,
                })
            results.append({"source": name, "articles": articles})
        except Exception as e:
            results.append({"source": name, "articles": [], "error": str(e)})

    data = {"feeds": results}
    try:
        if hasattr(redis_client, "setex"):
            redis_client.setex(NURSING_NEWS_CACHE_KEY, NURSING_NEWS_TTL, json.dumps(data))
        else:
            redis_client.set(NURSING_NEWS_CACHE_KEY, json.dumps(data))
    except Exception:
        pass
    return data

