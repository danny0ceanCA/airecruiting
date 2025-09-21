from pydantic import BaseModel

class StudentLoadTimeMetric(BaseModel):
    role: str
    duration: float

