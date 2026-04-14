from __future__ import annotations

from pydantic import BaseModel, Field
from crewai import Agent, LLM

from app.config import get_settings


class TestimonialRequestInput(BaseModel):
    customer_name: str = Field(..., min_length=1)
    client_name: str = Field(..., min_length=1)
    client_email: str = Field(..., min_length=1)
    project_description: str = Field(..., min_length=1)
    brand_voice: str = Field(..., min_length=1)


class TestimonialWorkflowOutput(BaseModel):
    subject: str
    body: str
    extracted_testimonial: str


def build_grok_llm() -> LLM:
    settings = get_settings()
    if not settings.grok_api_key:
        raise ValueError("GROK_API_KEY is not set")

    return LLM(
        model=settings.grok_model,
        base_url=settings.xai_base_url,
        api_key=settings.grok_api_key,
        temperature=0.7,
        max_tokens=300,
    )


def create_drafter_agent(llm: LLM) -> Agent:
    return Agent(
        role="DrafterAgent",
        goal="Write a warm and specific testimonial request email draft.",
        backstory=(
            "You write concise, empathetic emails that reflect context and make it easy for "
            "clients to reply with a testimonial."
        ),
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )


def create_sender_agent(llm: LLM) -> Agent:
    return Agent(
        role="SenderAgent",
        goal="Format the draft into a polished, client-ready email with a clear subject line.",
        backstory=(
            "You are an expert email formatter who improves readability and preserves a clear "
            "call to action."
        ),
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )


def create_extractor_agent(llm: LLM) -> Agent:
    return Agent(
        role="ExtractorAgent",
        goal="Extract only the testimonial content from a client reply.",
        backstory=(
            "You identify authentic testimonial language and remove signatures, greetings, "
            "and unrelated text."
        ),
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )
