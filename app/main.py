from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import parse_qs
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import TestimonialRequestInput
from app.auth import (
    enforce_daily_limit,
    generate_api_key,
    get_current_user,
    get_remaining_quota,
    verify_gumroad_license,
)
from app.config import get_settings
from app.crew import TestimonialAgentCrew
from app.db import get_db, get_session_factory, init_db
from app.models import ApiUser, Request as RequestModel


class CreateRequestBody(TestimonialRequestInput):
    pass


class CreateRequestResponse(BaseModel):
    job_id: str
    status: str
    remaining_today: int


class StatusResponse(BaseModel):
    job_id: str
    status: str
    subject: str | None = None
    body: str | None = None
    extracted_testimonial: str | None = None
    error: str | None = None


class GumroadWebhookBody(BaseModel):
    email: EmailStr
    license_key: str = Field(..., min_length=4)
    product_permalink: str | None = None


_workflow: TestimonialAgentCrew | None = None


def get_workflow() -> TestimonialAgentCrew:
    global _workflow
    if _workflow is None:
        _workflow = TestimonialAgentCrew()
    return _workflow


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Testimonial Agent API", lifespan=lifespan)


async def _run_job(job_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(select(RequestModel).where(RequestModel.job_id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return

        job.status = "running"
        job.updated_at = datetime.now(UTC)
        await db.commit()

        try:
            payload = TestimonialRequestInput(
                customer_name=job.customer_name,
                client_name=job.client_name,
                client_email=job.client_email,
                project_description=job.project_description,
                brand_voice=job.brand_voice,
            )
            output = await asyncio.to_thread(get_workflow().run, payload, f"job-{job_id}")
            job.subject = output.get("subject")
            job.body = output.get("body")
            job.extracted_testimonial = output.get("extracted_testimonial")
            job.status = "completed"
            job.error = None
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.updated_at = datetime.now(UTC)
            await db.commit()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/create-request", response_model=CreateRequestResponse)
async def create_request(
    body: CreateRequestBody,
    background_tasks: BackgroundTasks,
    user: Annotated[ApiUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    remaining = await enforce_daily_limit(db, user)
    job_id = str(uuid4())
    row = RequestModel(
        job_id=job_id,
        user_id=user.id,
        status="pending",
        customer_name=body.customer_name,
        client_name=body.client_name,
        client_email=body.client_email,
        project_description=body.project_description,
        brand_voice=body.brand_voice,
    )
    db.add(row)
    await db.commit()
    background_tasks.add_task(_run_job, job_id)
    return CreateRequestResponse(job_id=job_id, status="pending", remaining_today=remaining)


@app.get("/status/{job_id}", response_model=StatusResponse)
async def get_status(
    job_id: str,
    user: Annotated[ApiUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(RequestModel).where(RequestModel.job_id == job_id, RequestModel.user_id == user.id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return StatusResponse(
        job_id=row.job_id,
        status=row.status,
        subject=row.subject,
        body=row.body,
        extracted_testimonial=row.extracted_testimonial,
        error=row.error,
    )


@app.post("/gumroad/webhook")
async def gumroad_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    settings = get_settings()
    raw = await request.body()

    if settings.gumroad_webhook_secret:
        provided = request.headers.get("X-Gumroad-Signature", "")
        digest = hmac.new(settings.gumroad_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, digest):
            raise HTTPException(status_code=401, detail="Invalid Gumroad signature")

    payload: dict[str, str] = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = json.loads(raw.decode("utf-8") or "{}")
    else:
        parsed = parse_qs(raw.decode("utf-8"))
        payload = {k: v[0] for k, v in parsed.items() if v}

    email = payload.get("email") or payload.get("purchase[email]")
    license_key = payload.get("license_key") or payload.get("purchase[license_key]")
    product_permalink = payload.get("product_permalink")
    if not email or not license_key:
        raise HTTPException(status_code=400, detail="Missing email or license_key")

    data = GumroadWebhookBody(email=email, license_key=license_key, product_permalink=product_permalink)
    verify = await verify_gumroad_license(data.license_key, data.product_permalink)
    if not verify.get("success"):
        raise HTTPException(status_code=403, detail="License verification failed")

    result = await db.execute(select(ApiUser).where(ApiUser.email == data.email))
    user = result.scalar_one_or_none()
    created = False
    if user is None:
        user = ApiUser(
            email=str(data.email),
            api_key=generate_api_key(),
            gumroad_license_key=data.license_key,
            license_valid=True,
            daily_limit=settings.default_daily_limit,
        )
        db.add(user)
        created = True
    else:
        user.gumroad_license_key = data.license_key
        user.license_valid = True
        if not user.api_key:
            user.api_key = generate_api_key()

    await db.commit()
    return {"ok": True, "created": created, "api_key": user.api_key}


@app.get("/dashboard")
async def dashboard(
    user: Annotated[ApiUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    usage_remaining = await get_remaining_quota(db, user)

    total_q = await db.execute(select(func.count()).select_from(RequestModel).where(RequestModel.user_id == user.id))
    completed_q = await db.execute(
        select(func.count()).select_from(RequestModel).where(RequestModel.user_id == user.id, RequestModel.status == "completed")
    )
    failed_q = await db.execute(
        select(func.count()).select_from(RequestModel).where(RequestModel.user_id == user.id, RequestModel.status == "failed")
    )
    recent_q = await db.execute(
        select(RequestModel)
        .where(RequestModel.user_id == user.id)
        .order_by(RequestModel.id.desc())
        .limit(20)
    )
    recent = recent_q.scalars().all()

    return {
        "email": user.email,
        "daily_limit": user.daily_limit,
        "remaining_today": usage_remaining,
        "stats": {
            "total": int(total_q.scalar_one()),
            "completed": int(completed_q.scalar_one()),
            "failed": int(failed_q.scalar_one()),
        },
        "recent_jobs": [
            {
                "job_id": r.job_id,
                "status": r.status,
                "client_name": r.client_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent
        ],
    }
