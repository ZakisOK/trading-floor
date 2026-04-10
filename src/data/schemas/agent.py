"""Agent-related Pydantic schemas stub."""
from pydantic import BaseModel, ConfigDict


class AgentTask(BaseModel):
    model_config = ConfigDict(strict=True)

    agent: str
    task_type: str
    payload: dict[str, object]


class AgentResult(BaseModel):
    model_config = ConfigDict(strict=True)

    agent: str
    task_id: str
    confidence: float
    result: dict[str, object]
