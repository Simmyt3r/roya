from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


class ReservationCreate(BaseModel):
    property_id: UUID
    room_type_id: UUID
    rate_plan_id: UUID
    check_in: date
    check_out: date
    quantity: int = Field(default=1,ge=1,le=10)
    adults: int = Field(default=1,ge=1,le=20)
    children: int = Field(default=0,ge=0,le=20)
    guest_name: str = Field(min_length=2,max_length=150)
    guest_email: EmailStr
    guest_phone: str = Field(min_length=7,max_length=30)
    guarantee_type: str

    @model_validator(mode="after")
    def validate_stay(self):
        if self.check_out<=self.check_in:
            raise ValueError("check_out must be after check_in")
        if (self.check_out-self.check_in).days>90:
            raise ValueError("a reservation cannot exceed 90 nights")
        if self.guarantee_type not in {"pay_now","deposit","pay_at_property","hotel_approval"}:
            raise ValueError("unsupported guarantee_type")
        return self


class PartnerReservationDecision(BaseModel):
    decision: Literal["approve","reject"]
    reason: str | None = Field(default=None,max_length=1000)
