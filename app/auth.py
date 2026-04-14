from __future__ import annotations

import secrets
from datetime import UTC, date, datetime
from typing import Annotated

import httpx
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import ApiUser, DailyUsage


def generate_api_key() -> str:
    return f"gs_{secrets.token_urlsafe(32)}"


async def get_current_user(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> ApiUser:
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key")

    result = await db.execute(select(ApiUser).where(ApiUser.api_key == x_api_key, ApiUser.license_valid.is_(True)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return user


async def enforce_daily_limit(db: AsyncSession, user: ApiUser, limit_override: int | None = None) -> int:
    usage_date = datetime.now(UTC).date()
    result = await db.execute(
        select(DailyUsage).where(DailyUsage.user_id == user.id, DailyUsage.usage_date == usage_date)
    )
    usage = result.scalar_one_or_none()
    if usage is None:
        usage = DailyUsage(user_id=user.id, usage_date=usage_date, count=0)
        db.add(usage)
        await db.flush()

    daily_limit = limit_override if limit_override is not None else user.daily_limit
    if usage.count >= daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily limit reached ({daily_limit}/day).",
        )

    usage.count += 1
    await db.commit()
    remaining = max(daily_limit - usage.count, 0)
    return remaining


async def get_remaining_quota(db: AsyncSession, user: ApiUser) -> int:
    today: date = datetime.now(UTC).date()
    result = await db.execute(select(DailyUsage).where(DailyUsage.user_id == user.id, DailyUsage.usage_date == today))
    usage = result.scalar_one_or_none()
    count = usage.count if usage else 0
    return max(user.daily_limit - count, 0)


async def verify_gumroad_license(license_key: str, product_permalink: str | None = None) -> dict:
    settings = get_settings()
    permalink = product_permalink or settings.gumroad_product_permalink
    if not settings.gumroad_access_token:
        raise HTTPException(status_code=503, detail="GUMROAD_ACCESS_TOKEN is not configured")
    if not permalink:
        raise HTTPException(status_code=503, detail="GUMROAD_PRODUCT_PERMALINK is not configured")

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://api.gumroad.com/v2/licenses/verify",
            data={
                "access_token": settings.gumroad_access_token,
                "product_permalink": permalink,
                "license_key": license_key,
                "increment_uses_count": "false",
            },
        )

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Failed to verify license with Gumroad")

    data = response.json()
    success = bool(data.get("success"))
    purchase = data.get("purchase") or {}
    valid = bool(purchase.get("license_key")) and not bool(purchase.get("refunded"))
    return {"success": success and valid, "purchase": purchase}
