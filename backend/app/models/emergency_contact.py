from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.core.database import Base


class ContactRelation(enum.Enum):
    FAMILY = "family"
    FRIEND = "friend"
    PARTNER = "partner"
    COLLEAGUE = "colleague"
    NEIGHBOR = "neighbor"
    OTHER = "other"


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Contact info
    name = Column(String(255), nullable=False)
    phone_number = Column(String(20), nullable=False)
    email = Column(String(255))
    relation = Column(
        SQLEnum(ContactRelation, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=ContactRelation.OTHER,
    )
    
    # Priority
    is_primary = Column(Boolean, default=False)
    priority_order = Column(Integer, default=0)
    
    # Verification
    is_verified = Column(Boolean, default=False)
    verification_code = Column(String(10))
    verified_at = Column(DateTime(timezone=True))
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationship
    user = relationship("User", back_populates="emergency_contacts")
    
    def __repr__(self):
        return f"<EmergencyContact(id={self.id}, name={self.name}, is_primary={self.is_primary})>"
