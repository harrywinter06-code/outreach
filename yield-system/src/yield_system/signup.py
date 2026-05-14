"""Self-serve signup endpoint per experiment. Creates a free-tier API key.

Buyers upgrade to paid by completing Stripe Checkout; the webhook upgrades them.
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from yield_system.auth import create_customer

router = APIRouter(prefix="/signup", tags=["signup"])

_VALID_EXPERIMENTS = {"postcode", "sanctions", "webhookq", "email"}


class SignupRequest(BaseModel):
    experiment: str
    email: EmailStr


class SignupResponse(BaseModel):
    customer_id: str
    api_key: str
    plan: str
    experiment: str


@router.post("", response_model=SignupResponse)
def signup(payload: SignupRequest) -> SignupResponse:
    if payload.experiment not in _VALID_EXPERIMENTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"experiment must be one of {sorted(_VALID_EXPERIMENTS)}",
        )
    record = create_customer(payload.experiment, email=str(payload.email), plan="free")
    return SignupResponse(**record)
