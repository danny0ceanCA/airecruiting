from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.services.core_utils import normalize_email

class StudentRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    license: str = Field(alias="education_level")
    skills: list[str]
    experience_summary: str
    interests: str
    city: str
    state: str
    lat: float
    lng: float
    max_travel: float

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("max_travel")
    @classmethod
    def check_travel(cls, v):
        if v <= 0:
            raise ValueError("max_travel must be positive")
        return v

