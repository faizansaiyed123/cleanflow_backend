from pydantic import BaseModel, EmailStr

from app.common.enums import UserRole


class StaffUserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole
    employee_id: str | None = None  # required when role == EMPLOYEE


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    employee_id: str | None
    customer_id: str | None

    class Config:
        from_attributes = True


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
