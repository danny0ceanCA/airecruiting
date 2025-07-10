from app.main import redis_client
import json

# Set your test emails and job code
applicant_email = "123@ascs.com"
recruiter_email = "123r@ascs.com"   # use the correct recruiter email
job_code = "787dd505"               # replace with your real job code

def pretty(data):
    if data is None:
        return None
    try:
        return json.dumps(json.loads(data), indent=2)
    except Exception:
        return data

# Applicant and recruiter user info
print("=== Applicant user ===")
print(pretty(redis_client.get(f"user:{applicant_email}")))

print("\n=== Applicant student profile ===")
print(pretty(redis_client.get(f"student:{applicant_email}")))

print("\n=== Recruiter user ===")
print(pretty(redis_client.get(f"user:{recruiter_email}")))

# Print ALL job info
print("\n=== Jobs ===")
for key in redis_client.scan_iter("job:*"):
    job_raw = redis_client.get(key)
    if not job_raw:
        continue
    job = json.loads(job_raw)
    print(f"Job Key: {key}")
    print(json.dumps(job, indent=2))
    if job.get("job_code") == job_code:
        print(">>> This is the job you matched on above! <<<")

# If you want to check the last match result, add this:
print("\n=== Last match results ===")
match_key = f"match_results:{job_code}"
print(pretty(redis_client.get(match_key)))
