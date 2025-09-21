import asyncio
from datetime import datetime
import json
import time
from typing import Any, Callable

import numpy as np
from fastapi import HTTPException

from app.core.config import client
from app.core.logging import get_logger
from app.db.redis_client import get_queue, redis_client
from app.services.core_utils import license_to_code, normalize_email, resolve_student_key
from app.services.description import extract_benefits
from app.services.distance import get_driving_distance_miles
from app.services.email import send_email
from app.services.embeddings import ensure_index, rebuild_vector_index, vector_emails, vector_index
from app.services.jobs import _normalize_notes

logger = get_logger(__name__)

async def _perform_match_async(
    job_code: str,
    send_emails: bool = False,
    enq_time: float | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
):
    key = f"job:{job_code}"
    raw = redis_client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    job = json.loads(raw)
    job.setdefault("uninterested_students", [])
    was_matched_before = bool(redis_client.exists(f"match_results:{job_code}"))

    required_license = license_to_code(job.get("required_license"))

    poster_code = None
    poster_raw = redis_client.get(f"user:{job.get('posted_by')}")
    if poster_raw:
        try:
            p_data = json.loads(poster_raw)
            poster_code = p_data.get("institutional_code") or p_data.get("school_code")
        except Exception:
            poster_code = None

    combined = job.get("job_description", "") + " " + ", ".join(job.get("desired_skills", []))
    embed_start = time.perf_counter()
    try:
        resp = client.embeddings.create(input=combined, model="text-embedding-3-small")
        job_emb = resp.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")
    embed_elapsed = time.perf_counter() - embed_start
    if progress_callback:
        try:
            progress_callback(
                "embeddings_complete",
                {"job_code": job_code, "elapsed": embed_elapsed},
            )
        except Exception:
            logger.exception("Progress callback failed during embeddings event")

    ensure_index(len(job_emb))
    search_start = time.perf_counter()
    if vector_index is None:
        if progress_callback:
            try:
                progress_callback(
                    "search_complete",
                    {"job_code": job_code, "elapsed": 0.0, "candidate_count": 0},
                )
            except Exception:
                logger.exception("Progress callback failed during search event")
        return []

    matches = []
    if vector_index.ntotal == 0:
        rebuild_vector_index()
    search_vec = np.array([job_emb], dtype="float32")
    k = min(50, vector_index.ntotal)
    if k > 0:
        sims, idxs = vector_index.search(search_vec, k)
        candidate_emails = [vector_emails[i] for i in idxs[0] if i != -1]
    else:
        candidate_emails = []
    search_elapsed = time.perf_counter() - search_start
    if progress_callback:
        try:
            progress_callback(
                "search_complete",
                {
                    "job_code": job_code,
                    "elapsed": search_elapsed,
                    "candidate_count": len(candidate_emails),
                },
            )
        except Exception:
            logger.exception("Progress callback failed during search event")

    candidates: list[tuple[dict, list, tuple[float, float]]] = []
    candidate_coords: list[tuple[float, float]] = []
    for email in candidate_emails:
        skey = resolve_student_key(email)
        student_raw = redis_client.get(skey) if skey else None
        if not student_raw:
            continue
        try:
            student = json.loads(student_raw)
            emb = student.get("embedding")
            if not emb:
                continue
            if student.get("email") in job.get("uninterested_students", []):
                continue
            student_license = license_to_code(student.get("license") or student.get("education_level"))
            if required_license and student_license != required_license:
                continue
            student_user_raw = redis_client.get(f"user:{student.get('email')}")
            if student_user_raw and poster_code:
                try:
                    su = json.loads(student_user_raw)
                    stu_code = su.get("institutional_code") or su.get("school_code")
                    if su.get("role") == "applicant" and stu_code != poster_code:
                        continue
                except Exception:
                    pass
            coord = (float(student.get("lat")), float(student.get("lng")))
            candidate_coords.append(coord)
            candidates.append((student, emb, coord))
        except Exception:
            continue

    if progress_callback:
        try:
            progress_callback(
                "start",
                {"job_code": job_code, "candidate_count": len(candidates)},
            )
        except Exception:
            logger.exception("Progress callback failed during start event")

    distances: dict[tuple[float, float], float] = {}
    distance_elapsed = 0.0
    if candidate_coords:
        try:
            distance_start = time.perf_counter()
            coro = get_driving_distance_miles(
                candidate_coords,
                dest_lat=job.get("lat"),
                dest_lng=job.get("lng"),
            )
            result = await coro if asyncio.iscoroutine(coro) else coro
            if isinstance(result, dict):
                distances = result
            elif isinstance(result, (int, float)):
                distances = {coord: float(result) for coord in candidate_coords}
        except Exception:
            distances = {}
        finally:
            distance_elapsed = time.perf_counter() - distance_start
    if progress_callback:
        try:
            progress_callback(
                "distances_complete",
                {
                    "job_code": job_code,
                    "elapsed": distance_elapsed,
                    "candidate_count": len(candidate_coords),
                },
            )
        except Exception:
            logger.exception("Progress callback failed during distance completion event")

    for student, emb, coord in candidates:
        dist = distances.get(coord)
        if dist is None:
            continue
        if dist > float(student.get("max_travel", 0)):
            continue
        score = float(np.dot(job_emb, emb))
        matches.append(
            {
                "name": f"{student.get('first_name', '')} {student.get('last_name', '')}",
                "first_name": student.get("first_name", ""),
                "last_name": student.get("last_name", ""),
                "email": student.get("email"),
                "score": score,
                "distance_miles": round(dist, 1),
            }
        )

    # Deduplicate by email
    dedup: dict[str, dict] = {}
    for m in matches:
        dedup[m["email"]] = m
    matches = list(dedup.values())

    # Include applicant user records with a matching institutional code when no
    # student profile exists for them
    for ukey in redis_client.scan_iter("user:*"):
        u_raw = redis_client.get(ukey)
        if not u_raw:
            continue
        try:
            udata = json.loads(u_raw)
        except Exception:
            continue
        if udata.get("role") != "applicant" or not poster_code:
            continue
        ucode = udata.get("institutional_code") or udata.get("school_code")
        if ucode != poster_code:
            continue
        user_license = license_to_code(udata.get("license") or udata.get("education_level"))
        if required_license and user_license != required_license:
            continue
        email = ukey.split("user:", 1)[1]
        if email in job.get("uninterested_students", []):
            continue
        if resolve_student_key(email):
            continue
        matches.append(
            {
                "name": f"{udata.get('first_name', '')} {udata.get('last_name', '')}",
                "first_name": udata.get("first_name", ""),
                "last_name": udata.get("last_name", ""),
                "email": email,
                "score": 0.0,
                "distance_miles": None,
            }
        )

    matches.sort(key=lambda x: x["score"], reverse=True)

    assigned = set(job.get("assigned_students", []))
    # Exclude already assigned students from the match limit so recruiters
    # can always receive up to 10 new candidates regardless of how many
    # students have been assigned.
    filtered_matches = [m for m in matches if m["email"] not in assigned]
    top_matches = filtered_matches[:10]

    placed = set(job.get("placed_students", []))
    rejected = set(job.get("rejected_students", []))

    # Only store unassigned/unplaced/unrejected matches and keep
    # the list length at a maximum of 10. Assigned candidates will be
    # reattached when retrieving match results.
    filtered = [
        m
        for m in matches
        if m["email"] not in assigned
        and m["email"] not in placed
        and m["email"] not in rejected
    ]

    top_matches = filtered[:10]

    for m in top_matches:
        if m["email"] in placed:
            m["status"] = "placed"
        elif m["email"] in rejected:
            m["status"] = "rejected"
        else:
            m["status"] = None




    redis_client.set(
        f"match_results:{job_code}", json.dumps(top_matches)
    )
    if progress_callback:
        try:
            progress_callback(
                "stored",
                {"job_code": job_code, "match_count": len(top_matches)},
            )
        except Exception:
            logger.exception("Progress callback failed during stored event")

    if send_emails:
        for m in top_matches:
            send_email(
                m["email"],
                f"New Job Match: {job.get('job_title')}",
                (
                    f"Hello {m['name']},\n\n"
                    f"You have been matched with the job '{job.get('job_title')}'. "
                    "This means that your resume is being reviewed by a recruiter to determine compatibility with any open assignments within their organization."
                ),
            )

    # Metrics tracking
    try:
        avg_score = (
            sum(m["score"] for m in matches) / len(matches)
            if matches
            else 0.0
        )
        if was_matched_before:
            redis_client.incr("metrics:total_rematches")
        else:
            redis_client.incr("metrics:total_matches")
        redis_client.incrbyfloat("metrics:total_match_score", avg_score)
        redis_client.set(
            "metrics:last_match_timestamp", datetime.now().isoformat()
        )
    except Exception:
        pass

    return top_matches

def _perform_match(
    job_code: str,
    send_emails: bool = False,
    enq_time: float | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
):
    """Synchronous wrapper for background execution."""
    return asyncio.run(
        _perform_match_async(job_code, send_emails, enq_time, progress_callback)
    )

def match_worker(job_code: str, send_emails: bool = False, enq_time: float | None = None):
    logger.info(f"🔎 Match worker started for job {job_code}")
    start = datetime.now()
    timings: dict[str, float] = {}

    def progress_callback(event: str, payload: dict[str, Any]) -> None:
        job = payload.get("job_code", job_code)
        if event == "embeddings_complete":
            elapsed = payload.get("elapsed")
            if elapsed is not None:
                timings["embeddings"] = float(elapsed)
                logger.info(
                    "⏱️ Embeddings completed in %.2fs for job %s",
                    float(elapsed),
                    job,
                )
            return
        if event == "search_complete":
            elapsed = payload.get("elapsed")
            if elapsed is not None:
                timings["search"] = float(elapsed)
                logger.info(
                    "⏱️ Candidate similarity search completed in %.2fs for job %s (%s candidates)",
                    float(elapsed),
                    job,
                    payload.get("candidate_count", 0),
                )
            return
        if event == "start":
            logger.info(
                "Starting match job %s with %s candidates",
                job,
                payload.get("candidate_count", 0),
            )
        elif event == "distances_complete":
            elapsed = payload.get("elapsed")
            if elapsed is not None:
                timings["distances"] = float(elapsed)
                logger.info(
                    "⏱️ Distance lookups completed in %.2fs for job %s (%s origins)",
                    float(elapsed),
                    job,
                    payload.get("candidate_count", 0),
                )
            else:
                logger.info("Completed distance lookups for %s", job)
        elif event == "stored":
            logger.info(
                "✅ Stored %s matches for job %s",
                payload.get("match_count", 0),
                job,
            )

    if enq_time is not None:
        queue_time = start - datetime.fromtimestamp(enq_time)
        redis_client.incrbyfloat("metrics:match_queue_time", queue_time.total_seconds())
    result = _perform_match(job_code, send_emails, enq_time, progress_callback)
    process_time = datetime.now() - start
    redis_client.incrbyfloat("metrics:match_process_time", process_time.total_seconds())
    breakdown_parts = []
    if "embeddings" in timings:
        breakdown_parts.append(f"embeddings {timings['embeddings']:.2f}s")
    if "search" in timings:
        breakdown_parts.append(f"search {timings['search']:.2f}s")
    if "distances" in timings:
        breakdown_parts.append(f"distances {timings['distances']:.2f}s")
    breakdown = f" ({', '.join(breakdown_parts)})" if breakdown_parts else ""
    logger.info(
        "✅ Finished match job %s in %.2fs%s",
        job_code,
        process_time.total_seconds(),
        breakdown,
    )
    logger.info(f"⬅️ match_worker returning results for job {job_code} at {time.time()}")
    return result
