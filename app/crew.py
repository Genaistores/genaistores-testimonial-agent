from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from crewai import Agent, Crew, Process, Task
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.agents import (
    TestimonialRequestInput,
    TestimonialWorkflowOutput,
    build_grok_llm,
    create_drafter_agent,
    create_extractor_agent,
    create_sender_agent,
)
from app.config import get_settings


class WorkflowState(TypedDict):
    payload: TestimonialRequestInput
    draft: str
    subject: str
    body: str
    email_status: str


def _result_text(result: Any) -> str:
    raw = getattr(result, "raw", None)
    if raw is not None:
        return str(raw).strip()
    return str(result).strip()


class TestimonialAgentCrew:
    """CrewAI + LangGraph workflow for testimonial outreach and extraction."""

    def __init__(self) -> None:
        llm = build_grok_llm()
        self.drafter_agent = create_drafter_agent(llm)
        self.sender_agent = create_sender_agent(llm)
        self.extractor_agent = create_extractor_agent(llm)
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()

    def _run_single_task(
        self,
        agent: Agent,
        description: str,
        expected_output: str,
        memory: bool = True,
    ) -> str:
        task = Task(
            description=description,
            expected_output=expected_output,
            agent=agent,
        )
        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            memory=memory,
            verbose=False,
        )
        return _result_text(crew.kickoff())

    def _draft_node(self, state: WorkflowState) -> dict[str, str]:
        payload = state["payload"]
        draft = self._run_single_task(
            agent=self.drafter_agent,
            description=(
                "Write a warm testimonial request email draft.\n"
                f"Customer name: {payload.customer_name}\n"
                f"Client name: {payload.client_name}\n"
                f"Client email: {payload.client_email}\n"
                f"Project description: {payload.project_description}\n"
                f"Brand voice: {payload.brand_voice}\n"
                "Keep it personal, short, and include a direct ask for 2-3 sentences."
            ),
            expected_output="A single email draft body only, no subject line.",
            memory=True,
        )
        return {"draft": draft}

    def _sender_node(self, state: WorkflowState) -> dict[str, str]:
        payload = state["payload"]
        draft = state["draft"]
        formatted = self._run_single_task(
            agent=self.sender_agent,
            description=(
                "Format this testimonial request draft into a final email.\n"
                f"Brand voice: {payload.brand_voice}\n"
                f"Client name: {payload.client_name}\n"
                f"Client email: {payload.client_email}\n"
                "Return exactly this format:\n"
                "SUBJECT: <subject line>\n"
                "BODY:\n"
                "<email body>\n\n"
                "Draft:\n"
                f"{draft}"
            ),
            expected_output="Exactly SUBJECT and BODY blocks.",
            memory=True,
        )

        subject = ""
        body = formatted
        for line in formatted.splitlines():
            if line.strip().upper().startswith("SUBJECT:"):
                subject = line.split(":", 1)[1].strip()
                break
        if "BODY:" in formatted:
            body = formatted.split("BODY:", 1)[1].strip()
        if not subject:
            subject = f"Quick testimonial request from {payload.customer_name}"
        return {"subject": subject, "body": body}

    def _send_email_node(self, state: WorkflowState) -> dict[str, str]:
        payload = state["payload"]
        subject = state["subject"]
        body = state["body"]
        settings = get_settings()

        if not settings.smtp_host:
            return {"email_status": "skipped: SMTP_HOST is not configured"}

        from_address = settings.smtp_from_email or settings.smtp_username or "no-reply@localhost"

        message = EmailMessage()
        message["From"] = from_address
        message["To"] = payload.client_email
        message["Subject"] = subject
        message.set_content(body)

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_use_starttls:
                    smtp.starttls()
                if settings.smtp_username and settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        except Exception as exc:
            return {"email_status": f"failed: {exc}"}

        return {"email_status": "sent"}

    def _build_graph(self):
        graph = StateGraph(WorkflowState)
        graph.add_node("drafter", self._draft_node)
        graph.add_node("sender", self._sender_node)
        graph.add_node("send_email", self._send_email_node)
        graph.add_edge(START, "drafter")
        graph.add_edge("drafter", "sender")
        graph.add_edge("sender", "send_email")
        graph.add_edge("send_email", END)
        return graph.compile(checkpointer=self.checkpointer)

    def run(self, data: TestimonialRequestInput, thread_id: str = "testimonial-thread") -> dict[str, str]:
        initial: WorkflowState = {
            "payload": data,
            "draft": "",
            "subject": "",
            "body": "",
            "email_status": "",
        }
        result = self.graph.invoke(initial, config={"configurable": {"thread_id": thread_id}})
        output = TestimonialWorkflowOutput(
            subject=result["subject"],
            body=result["body"],
            extracted_testimonial="",
        )
        return output.model_dump()

    def extract_testimonial(self, reply_text: str) -> str:
        if not reply_text.strip():
            return ""
        return self._run_single_task(
            agent=self.extractor_agent,
            description=(
                "Extract testimonial text from this client reply. "
                "If there is no testimonial, return an empty string.\n\n"
                f"Client reply:\n{reply_text}"
            ),
            expected_output="Only the extracted testimonial text.",
            memory=True,
        )
