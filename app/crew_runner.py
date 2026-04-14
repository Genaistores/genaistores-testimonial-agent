from crewai import Agent, Crew, LLM, Process, Task

from app.config import get_settings


def run_crew(prompt: str) -> str:
    settings = get_settings()
    if not settings.xai_api_key:
        raise ValueError("XAI_API_KEY is not set")

    llm = LLM(
        model=settings.xai_model,
        base_url=settings.xai_base_url,
        api_key=settings.xai_api_key,
    )

    analyst = Agent(
        role="Brief analyst",
        goal="Produce a concise, accurate answer to the user's request.",
        backstory="You are careful, direct, and avoid fluff.",
        llm=llm,
        verbose=False,
    )

    task = Task(
        description=prompt,
        expected_output="A short plain-text answer (under 800 words).",
        agent=analyst,
    )

    crew = Crew(agents=[analyst], tasks=[task], process=Process.sequential, verbose=False)
    result = crew.kickoff()
    raw = getattr(result, "raw", None)
    if raw is not None:
        return str(raw)
    return str(result)
