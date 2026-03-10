from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

class InputModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    action: str = None
    origin_id: Optional[str] = None
    dest_id: Optional[str] = None
    upload_path: Optional[str] = None
    add_suffix: Optional[str] = None
    remove_suffix: Optional[str] = None
    confirm: bool = None

    @field_validator("action")
    def action_lower(cls, valor):
        return valor.lower()

    @field_validator("origin_id", "dest_id", mode="before")
    def transform_id(cls, valor: str) -> str:
        if len(valor) == 10 and not str(valor).startswith("-100"):
            return f"-100{valor}"
        return valor