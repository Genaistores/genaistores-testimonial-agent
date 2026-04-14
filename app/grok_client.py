from langchain_openai import ChatOpenAI

from app.config import get_settings


def get_chat_model() -> ChatOpenAI:
    settings = get_settings()
    if not settings.xai_api_key:
        raise ValueError("XAI_API_KEY is not set")
    return ChatOpenAI(
        model=settings.xai_model,
        api_key=settings.xai_api_key,
        base_url=settings.xai_base_url,
        temperature=0.2,
    )
