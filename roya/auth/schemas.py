from typing import Literal
from pydantic import BaseModel, EmailStr, Field


class RegisterInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    account_type: Literal["guest", "hotel"] = "guest"


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
