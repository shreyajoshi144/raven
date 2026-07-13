from pydantic import BaseModel, EmailStr, Field, validator
from datetime import datetime
from typing import Optional
from enum import Enum


class ContactRelation(str, Enum):
    FAMILY = "family"
    FRIEND = "friend"
    PARTNER = "partner"
    COLLEAGUE = "colleague"
    NEIGHBOR = "neighbor"
    OTHER = "other"


class EmergencyContactBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    phone_number: str = Field(..., min_length=10, max_length=20)
    email: Optional[EmailStr] = None
    relation: ContactRelation = ContactRelation.OTHER


class EmergencyContactCreate(EmergencyContactBase):
    is_primary: bool = False
    priority_order: int = 0


class EmergencyContactUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone_number: Optional[str] = Field(None, min_length=10, max_length=20)
    email: Optional[EmailStr] = None
    relation: Optional[ContactRelation] = None
    is_primary: Optional[bool] = None
    priority_order: Optional[int] = None


class EmergencyContactInDB(EmergencyContactBase):
    id: int
    user_id: int
    is_primary: bool
    priority_order: int
    is_verified: bool
    verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class EmergencyContactResponse(EmergencyContactInDB):
    pass


class VerificationRequest(BaseModel):
    contact_id: int
    verification_code: str
