from pydantic import BaseModel, field_validator


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()

class ResumeRequest(BaseModel):
    student_email: str
    job_code: str
    preview: bool | None = False

    @field_validator("student_email", mode="before")
    @classmethod
    def normalize_email_field(cls, v: str) -> str:
        return normalize_email(v)
