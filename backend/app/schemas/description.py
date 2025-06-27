from pydantic import BaseModel

class DescriptionRequest(BaseModel):
    student_email: str
    job_code: str
