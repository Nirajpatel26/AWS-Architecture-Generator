from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field

WorkloadType = Literal["web_api", "data_pipeline", "ml_training", "static_site"]
Scale = Literal["small", "medium", "large"]
BudgetTier = Literal["minimal", "balanced", "performance"]
DataStore = Literal["sql", "nosql", "object", "none"]
Compliance = Literal["HIPAA", "PCI", "SOC2"]


class ArchSpec(BaseModel):
    workload_type: WorkloadType = "web_api"
    scale: Scale = "small"
    compliance: List[Compliance] = Field(default_factory=list)
    region: str = "us-east-1"
    ha_required: bool = False
    multi_region: bool = False
    budget_tier: BudgetTier = "balanced"
    data_store: DataStore = "none"
    async_jobs: bool = False
    auth_required: bool = True
    project_name: str = "cloudarch"
    raw_prompt: str = ""
    assumptions: List[str] = Field(default_factory=list, alias="_assumptions")

    model_config = {"populate_by_name": True}

    def to_dict(self) -> dict:
        d = self.model_dump(by_alias=True)
        return d


GEMINI_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "workload_type": {
            "type": "string",
            "enum": ["web_api", "data_pipeline", "ml_training", "static_site"],
        },
        "scale": {"type": "string", "enum": ["small", "medium", "large"]},
        "compliance": {
            "type": "array",
            "items": {"type": "string", "enum": ["HIPAA", "PCI", "SOC2"]},
        },
        "region": {"type": "string"},
        "ha_required": {"type": "boolean"},
        "multi_region": {"type": "boolean"},
        "budget_tier": {
            "type": "string",
            "enum": ["minimal", "balanced", "performance"],
        },
        "data_store": {
            "type": "string",
            "enum": ["sql", "nosql", "object", "none"],
        },
        "async_jobs": {"type": "boolean"},
        "auth_required": {"type": "boolean"},
        "project_name": {"type": "string"},
    },
    "required": ["workload_type"],
}
