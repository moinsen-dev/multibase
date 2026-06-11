"""multibase configuration model — Pydantic-based."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class ProjectConfig(BaseModel):
    """A single Supabase project within a multibase cluster."""

    name: str
    port_base: int = Field(ge=1000, le=65000)

    @field_validator("name")
    @classmethod
    def valid_project_name(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"Invalid project name: {v!r} — use letters, digits, hyphens, underscores")
        return v


class SharedConfig(BaseModel):
    """Shared service configuration."""

    db_image: str = "public.ecr.aws/supabase/postgres:17.6.1.132"
    studio_port: int = 3000
    kong_port: int = 8000
    analytics: bool = True
    storage: bool = True


class MultibaseConfig(BaseModel):
    """Top-level multibase configuration."""

    name: str = "my-multibase"
    shared: SharedConfig = Field(default_factory=SharedConfig)
    projects: list[ProjectConfig] = []

    @classmethod
    def from_file(cls, path: Path) -> MultibaseConfig:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    @classmethod
    def default(cls, name: str, port_base: int) -> MultibaseConfig:
        return cls(
            name=name,
            projects=[ProjectConfig(name=name, port_base=port_base)],
        )

    def to_yaml(self) -> str:
        data = self.model_dump(mode="python")
        return yaml.safe_dump(data, default_flow_style=False, sort_keys=False)

    def save(self, path: Path) -> None:
        path.write_text(self.to_yaml())
