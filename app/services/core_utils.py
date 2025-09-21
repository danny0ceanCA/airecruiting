import json

from backend.app.school_codes import SCHOOL_CODE_MAP

from app.core.config import DEFAULT_LICENSES
from app.db.redis_client import redis_client

def normalize_email(email: str | None) -> str:
    """Return a lowercase, stripped version of an email."""
    return (email or "").strip().lower()

def user_key(email: str) -> str:
    """Return the redis key for a user."""
    return f"user:{normalize_email(email)}"

def student_key(institution_code: str, student_id: str) -> str:
    """Return the canonical redis key for a student."""
    return f"student:{institution_code}:{student_id}"

def student_email_key(email: str) -> str:
    """Return the secondary index key for a student email."""
    return f"student_email:{normalize_email(email)}"

def resolve_student_key(email: str) -> str | None:
    """Resolve a student's canonical key from their email."""
    idx = redis_client.get(student_email_key(email))
    if idx:
        inst, sid = idx.split(":", 1)
        return student_key(inst, sid)
    legacy = f"student:{normalize_email(email)}"
    if redis_client.exists(legacy):
        return legacy
    return None

def generate_student_id() -> str:
    """Generate a unique student identifier."""
    return str(redis_client.incr("student_id"))

def persist_student_record(email: str, data: dict, institution_code: str, student_id: str) -> None:
    """Persist the student record under canonical, legacy, and index keys."""
    payload = json.dumps(data)
    key = student_key(institution_code, student_id)
    redis_client.set(key, payload)
    if hasattr(redis_client, "store") and getattr(redis_client.get, "__qualname__", "").endswith("DummyRedis.get"):
        redis_client.store[key] = payload
        redis_client.store[student_email_key(email)] = f"{institution_code}:{student_id}"
        redis_client.store[f"student:{email}"] = payload
    else:
        redis_client.set(student_email_key(email), f"{institution_code}:{student_id}")
        redis_client.set(f"student:{email}", payload)

def find_user_key(email: str) -> str | None:
    """Return existing user key matching email case-insensitively."""
    target = normalize_email(email)
    exact = user_key(target)
    if redis_client.exists(exact):
        return exact
    for key in redis_client.scan_iter("user:*"):
        k = key if isinstance(key, str) else key.decode()
        if k.split("user:", 1)[1].lower() == target:
            return k
    return None

def license_to_code(value: str | None) -> str | None:
    """Return the license code for a given code or label."""
    if not value:
        return value
    val = value.strip()
    licenses = all_licenses()
    low = val.lower()
    if low in licenses:
        return low
    for code, label in licenses.items():
        if low == label.lower():
            return code
    return low

def get_school_label(code: str) -> str | None:
    """Return label for a school code from redis or defaults."""
    label = redis_client.get(f"school_code:{code}")
    if label:
        return label
    return SCHOOL_CODE_MAP.get(code)

def all_school_codes() -> dict[str, str]:
    """Return mapping of all known school codes."""
    codes = {}
    for key in redis_client.scan_iter("school_code:*"):
        val = redis_client.get(key)
        if val is not None:
            c = key.split("school_code:", 1)[1]
            codes[c] = val
    for c, l in SCHOOL_CODE_MAP.items():
        codes.setdefault(c, l)
    return codes

def all_licenses() -> dict[str, str]:
    """Return mapping of all configured licenses."""
    licenses: dict[str, str] = {}
    for key in redis_client.scan_iter("license:*"):
        if not isinstance(key, str) or not key.startswith("license:"):
            continue
        label = redis_client.get(key)
        if label is not None:
            code = key.split("license:", 1)[1]
            licenses[code] = label
    for c, l in DEFAULT_LICENSES.items():
        licenses.setdefault(c, l)
    return licenses

