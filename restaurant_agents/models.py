from pydantic import BaseModel


class UserContext(BaseModel):
    customer_id: int
    name: str
    mobile: str
    tier: str = "bronze"


class HandoffData(BaseModel):
    to_agent_name: str
    issue_type: str
    issue_description: str
    reason: str


class InputGuardRailOutput(BaseModel):
    is_off_topic: bool
    reason: str


class OutputGuardRailOutput(BaseModel):
    contains_off_topic: bool
    contains_private_data: bool
    reason: str
