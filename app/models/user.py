from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator, model_validator

class RegisterRequest(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    institutional_code: str | None = Field(default=None, alias="school_code")
    password: str
    role: str = "applicant"

    model_config = ConfigDict(populate_by_name=True)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class VerifyTokenRequest(BaseModel):
    token: str

class ApproveRequest(BaseModel):
    email: EmailStr
    role: str | None = None  # optional new role

class RejectRequest(BaseModel):
    email: EmailStr

class UpdateUserRequest(BaseModel):
    role: str | None = None
    institutional_code: str | None = Field(default=None, alias="school_code")
    active: bool | None = None

