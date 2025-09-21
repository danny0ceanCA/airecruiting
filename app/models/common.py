from pydantic import BaseModel, EmailStr

class PlacementRequest(BaseModel):
    student_email: EmailStr
    job_code: str

