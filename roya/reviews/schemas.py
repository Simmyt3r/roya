from uuid import UUID

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    reservation_id: UUID
    rating: int = Field(ge=1,le=5)
    comment: str = Field(default="",max_length=2000)
