from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional, List
from enum import Enum


class SOSStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    FALSE_ALARM = "false_alarm"


class SOSEventBase(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    location_accuracy: Optional[float] = Field(None, ge=0)
    address: Optional[str] = Field(None, max_length=500)
    incident_type: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


class SOSEventCreate(SOSEventBase):
    pass


class SOSEventUpdate(BaseModel):
    status: Optional[SOSStatus] = None
    incident_type: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    resolved_by: Optional[str] = None


class SOSEventInDB(SOSEventBase):
    id: int
    user_id: int
    maps_link: Optional[str] = None
    status: SOSStatus
    sms_sent: bool = False
    whatsapp_sent: bool = False
    push_sent: bool = False
    contacts_notified: Optional[str] = None
    first_response_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class SOSEventResponse(SOSEventInDB):
    pass


class SOSNotificationRequest(BaseModel):
    sos_event_id: int
    contact_ids: Optional[List[int]] = None  # If None, notify all primary contacts


class SOSLocationUpdate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    location_accuracy: Optional[float] = Field(None, ge=0)
    address: Optional[str] = Field(None, max_length=500)
