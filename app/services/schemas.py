from pydantic import BaseModel, Field


class ChecklistItemIn(BaseModel):
    label: str
    is_required: bool = True
    sort_order: int = 0


class ChecklistTemplateCreate(BaseModel):
    name: str
    items: list[ChecklistItemIn] = []


class ChecklistItemOut(ChecklistItemIn):
    id: str

    class Config:
        from_attributes = True


class ChecklistTemplateOut(BaseModel):
    id: str
    name: str
    items: list[ChecklistItemOut]

    class Config:
        from_attributes = True


class ServiceCreate(BaseModel):
    name: str
    description: str | None = None
    is_addon: bool = False
    base_rate: float = Field(ge=0)
    checklist_template_id: str | None = None


class ServiceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_addon: bool | None = None
    base_rate: float | None = None
    checklist_template_id: str | None = None
    is_archived: bool | None = None


class ServiceOut(BaseModel):
    id: str
    name: str
    description: str | None
    is_addon: bool
    base_rate: float
    checklist_template_id: str | None
    is_archived: bool

    class Config:
        from_attributes = True
