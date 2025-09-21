import asyncio
from datetime import timedelta
import os
import re

import httpx

from app.core.logging import get_logger
from app.db.redis_client import redis_client

logger = get_logger(__name__)

async def get_driving_distance_miles(
    orig_lat: float | list[tuple[float, float]],
    orig_lng: float | None = None,
    dest_lat: float | None = None,
    dest_lng: float | None = None,
) -> float | dict[tuple[float, float], float]:
    """Return driving distance(s) in miles using Google Distance Matrix.

    The function accepts a list of origin coordinates and batches requests to
    respect the Google API limit of 25 origins per call. Results are cached in
    Redis for 24 hours to avoid excessive API calls. When provided a single
    origin via the legacy signature, the return value remains the distance in
    miles for backward compatibility.
    """

    key = os.getenv("GOOGLE_KEY")
    if not key:
        raise RuntimeError("Missing GOOGLE_KEY")

    provided_list = isinstance(orig_lat, list)
    invalid_origins = 0
    if provided_list:
        valid_origins: list[tuple[float, float]] = []
        for lat, lng in orig_lat:
            if lat is None or lng is None:
                invalid_origins += 1
                continue
            try:
                lat_f = float(lat)
                lng_f = float(lng)
            except (TypeError, ValueError):
                invalid_origins += 1
                continue
            if lat_f == 0.0 and lng_f == 0.0:
                invalid_origins += 1
                continue
            valid_origins.append((lat_f, lng_f))
        origins = valid_origins
        if dest_lat is not None and dest_lng is not None:
            dest_latitude = float(dest_lat)
            dest_longitude = float(dest_lng)
        elif isinstance(orig_lng, (int, float)) and isinstance(dest_lat, (int, float)):
            dest_latitude = float(orig_lng)
            dest_longitude = float(dest_lat)
        else:
            raise ValueError("When passing a list of origins, provide destination coordinates")
    else:
        if not all(isinstance(v, (int, float)) for v in [orig_lat, orig_lng, dest_lat, dest_lng]):
            raise ValueError("Invalid coordinates provided")
        origins = [(float(orig_lat), float(orig_lng))]  # type: ignore[arg-type]
        dest_latitude = float(dest_lat)  # type: ignore[arg-type]
        dest_longitude = float(dest_lng)  # type: ignore[arg-type]

    results: dict[tuple[float, float], float] = {}
    missing: list[tuple[float, float]] = []
    ttl_seconds = int(timedelta(hours=24).total_seconds())

    if invalid_origins:
        logger.info("Skipping %s invalid origins before distance lookup", invalid_origins)

    for lat, lng in origins:
        cache_key = f"distance:{lat}:{lng}:{dest_latitude}:{dest_longitude}"
        cached = redis_client.get(cache_key)
        if cached is not None:
            try:
                miles = float(cached)
                logger.info("Distance cache hit for %s", cache_key)
                results[(lat, lng)] = miles
                continue
            except ValueError:
                logger.exception("Invalid cached distance for %s", cache_key)
        logger.info("Distance cache miss for %s", cache_key)
        missing.append((lat, lng))

    if missing:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        async with httpx.AsyncClient() as client:
            if len(missing) > 25:
                batches = [missing[i : i + 25] for i in range(0, len(missing), 25)]
            else:
                batches = [missing]

            for batch in batches:
                if not batch:
                    continue
                logger.info(
                    "Requesting Google API for batch of %s origins", len(batch)
                )
                origins_param = "|".join(f"{lat},{lng}" for lat, lng in batch)
                params = {
                    "origins": origins_param,
                    "destinations": f"{dest_latitude},{dest_longitude}",
                    "units": "imperial",
                    "key": key,
                }
                try:
                    logger.info("Requesting %s params=%s", url, params)
                    resp = await client.get(url, params=params)
                except Exception:
                    logger.exception("Error requesting distance matrix")
                    raise

                if resp.status_code != 200:
                    logger.warning(
                        "Distance matrix non-200 response %s: %s", resp.status_code, resp.text
                    )
                    resp.raise_for_status()

                try:
                    data = resp.json()
                    rows = data["rows"]
                except Exception:
                    logger.exception("Error parsing distance matrix response")
                    raise

                if len(rows) != len(batch):
                    raise ValueError("Distance matrix response row count mismatch")

                for origin, row in zip(batch, rows):
                    try:
                        element = row["elements"][0]
                        value_meters = element["distance"]["value"]
                    except Exception:
                        logger.exception("Error parsing distance for origin %s", origin)
                        raise

                    miles = value_meters / 1609.34
                    cache_key = f"distance:{origin[0]}:{origin[1]}:{dest_latitude}:{dest_longitude}"
                    redis_client.setex(cache_key, ttl_seconds, miles)
                    results[origin] = miles

    if provided_list:
        return results
    return results[origins[0]]
