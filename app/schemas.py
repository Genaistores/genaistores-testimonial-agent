from pydantic import BaseModel, Field


class PromptBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=16_000)


class RunResponse(BaseModel):
    output: str
    run_id: int
