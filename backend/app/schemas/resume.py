from pydantic import BaseModel

class ResumeRequest(BaseModel):
    student_email: str
    job_code: str
    preview: bool | None = False
