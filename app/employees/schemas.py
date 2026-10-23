from pydantic import BaseModel, EmailStr, Field


class EmployeeCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: str
    hourly_rate: float = Field(gt=0, default=18.0)
    skills: list[str] = []
    availability: dict = {}


class EmployeeUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    hourly_rate: float | None = None
    skills: list[str] | None = None
    availability: dict | None = None
    is_active: bool | None = None


class EmployeeOut(BaseModel):
    id: str
    full_name: str
    email: str
    phone: str
    hourly_rate: float
    skills: list[str]
    availability: dict
    profile_photo_url: str | None
    is_active: bool

    class Config:
        from_attributes = True
