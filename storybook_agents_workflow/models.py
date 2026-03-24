from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class StoryPage(BaseModel):
    page_number: int
    text: str
    visual_description: str
    image_url: Optional[str] = None


class StoryState(BaseModel):
    theme: str
    pages: List[StoryPage] = Field(default_factory=list)
    image_provider: Literal["vertex", "openai"] = "vertex"
    current_status: str = "init"


# 공유 State 초기화
shared_state = StoryState(theme="", image_provider="openai")
