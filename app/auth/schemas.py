from pydantic import BaseModel, EmailStr

from app.common.enums import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    user_id: str
    full_name: str


class MeResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    employee_id: str | None = None
    customer_id: str | None = None

    class Config:
        from_attributes = True
