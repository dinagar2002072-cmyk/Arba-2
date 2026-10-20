"""Pydantic request payload models."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginPayload(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=256)


class SignupPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=100)
    email: str = Field(
        min_length=5,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    password: str = Field(min_length=12, max_length=256)


class BaselineCell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product: str
    week: str
    qty_cs: float = Field(ge=0, le=1_000_000_000)


class BaselineSave(BaseModel):
    market: str
    customer_id: int
    cells: list[BaselineCell] = Field(max_length=20_000)


class PromoPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    version: int | None = None
    market: str
    customer_id: int
    description: str = Field(default="", max_length=50)
    start_date: date
    end_date: date
    cons_start: date
    cons_end: date
    tactic: str
    incentive_value: float = Field(ge=0, le=1_000_000_000)
    comments: str = Field(default="", max_length=100)
    items: dict[str, float] = Field(min_length=1, max_length=100)


class TacticPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_code: str
    name: str = Field(min_length=1, max_length=60)
    incentive_type: Literal["FIXED_LUMPSUM", "VARIABLE"]


class PromotionPhasingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_code: str
    customer_id: int
    duration_weeks: Literal[2, 3, 4]
    percentages: list[float] = Field(min_length=2, max_length=4)


class PromotionCopyPayload(BaseModel):
    market: str
    customer_id: int
    promotion_ids: list[int] = Field(min_length=1, max_length=100)


class ListingPayload(BaseModel):
    market: str
    customer_id: int
    products: list[str] = Field(max_length=500)


class UserAccessAssignment(BaseModel):
    market_code: str
    customer_id: int


class AdminUserUpdate(BaseModel):
    role: Literal["PLANNER", "APPROVER", "ADMIN", "VIEWER"]
    active: bool
    assignments: list[UserAccessAssignment] = Field(max_length=500)
    sales_org_access: list[str] = Field(max_length=100, default_factory=list)
    admin_sales_org_access: list[str] = Field(max_length=100, default_factory=list)


class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=5, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=2, max_length=100)
    role: Literal["PLANNER", "APPROVER", "VIEWER"]
    active: bool = True
    sales_org_access: list[str] = Field(max_length=100, default_factory=list)
    assignments: list[UserAccessAssignment] = Field(max_length=500)
    admin_sales_org_access: list[str] = Field(max_length=100, default_factory=list)


class MasterFileUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=15_000_000)


class BaselineFileUpload(MasterFileUpload):
    market: str
    customer_id: int
