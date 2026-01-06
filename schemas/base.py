import re
from pydantic import BaseModel, Extra, model_validator
from typing import Any


def to_pascal(snake: str) -> str:
    """Convert a snake_case string to PascalCase.

    Args:
        snake: The string to convert.

    Returns:
        The PascalCase string.
    """
    camel = snake.title()
    return re.sub('([0-9A-Za-z])_(?=[0-9A-Z])', lambda m: m.group(1), camel)


def to_camel(snake: str) -> str:
    """Convert a snake_case string to camelCase.

    Args:
        snake: The string to convert.

    Returns:
        The converted camelCase string.
    """
    camel = to_pascal(snake)
    return re.sub('(^_*[A-Z])', lambda m: m.group(1).lower(), camel)


class LowerCamelAliasModel(BaseModel):
    class Config:
        extra = Extra.forbid

    @model_validator(mode="before")
    @classmethod
    def populate_by_alias_if_needed(cls, data: dict[str, Any]) -> dict[str, Any]:
        for k, field_info in cls.model_fields.items():
            if k not in data and to_camel(k) in data:
                data[k] = data.pop(to_camel(k))
        return data
