from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator, HttpUrl

class JobRequest(BaseModel):
    job_title: str
    job_description: str
    desired_skills: list[str]
    job_code: Optional[str] = None
    source: str | None = None
    external_apply_url: HttpUrl | None = None
    required_license: str | None = None
    min_pay: float
    max_pay: float
    city: str
    state: str
    lat: float
    lng: float

    @field_validator("min_pay", "max_pay")
    @classmethod
    def check_positive(cls, v):
        if v <= 0:
            raise ValueError("Pay must be positive")
        return v

    @model_validator(mode="after")
    def validate_range(self):
        if self.min_pay > self.max_pay:
            raise ValueError("Minimum pay cannot exceed maximum pay")
        return self

class JobCodeRequest(BaseModel):
    job_code: str

