from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, Boolean, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base


class SOSStatus(enum.Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    FALSE_ALARM = "false_alarm"


class SOSEvent(Base):
    __tablename__ = "sos_events"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Location data
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    location_accuracy = Column(Float)  # in meters
    address = Column(String(500))
    
    # Maps link
    maps_link = Column(String(500))
    
    # Status and type
    status = Column(
        SQLEnum(SOSStatus, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=SOSStatus.ACTIVE,
    )
    incident_type = Column(String(100))  # e.g., "medical", "assault", "harassment"
    description = Column(Text)
    
    # Notification tracking
    sms_sent = Column(Boolean, default=False)
    whatsapp_sent = Column(Boolean, default=False)
    push_sent = Column(Boolean, default=False)
    contacts_notified = Column(Text)  # JSON array of contact IDs
    
    # Response tracking
    first_response_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    resolved_by = Column(String(255))  # user_id or system
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationship
    user = relationship("User", back_populates="sos_events")
    
    def __repr__(self):
        return f"<SOSEvent(id={self.id}, status={self.status}, created_at={self.created_at})>"
