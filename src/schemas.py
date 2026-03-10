from typing import Optional
from pydantic import BaseModel, field_validator

class InputModel(BaseModel):
    action: Optional[str] = None
    origin_id: Optional[str] = None
    dest_id: Optional[str] = None
    upload_path: Optional[str] = None
    add_suffix: Optional[str] = None
    remove_suffix: Optional[str] = None
    confirm: bool = None

    @field_validator("action")
    def action_lower(cls, valor):
        return valor.lower()