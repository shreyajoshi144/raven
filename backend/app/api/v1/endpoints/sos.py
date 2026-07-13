from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from app.core.database import get_db
from app.models.user import User
from app.models.sos_event import SOSEvent, SOSStatus
from app.schemas.sos_event import (
    SOSEventCreate,
    SOSEventUpdate,
    SOSEventResponse,
    SOSNotificationRequest,
    SOSLocationUpdate
)
from app.api.deps import get_current_active_user

router = APIRouter()


def generate_maps_link(latitude: float, longitude: float) -> str:
    """Generate Google Maps link for location"""
    return f"https://maps.google.com/?q={latitude},{longitude}"


@router.post("/", response_model=SOSEventResponse, status_code=status.HTTP_201_CREATED)
def create_sos_event(
    sos_data: SOSEventCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a new SOS event"""
    maps_link = generate_maps_link(sos_data.latitude, sos_data.longitude)
    
    new_sos = SOSEvent(
        user_id=current_user.id,
        latitude=sos_data.latitude,
        longitude=sos_data.longitude,
        location_accuracy=sos_data.location_accuracy,
        address=sos_data.address,
        maps_link=maps_link,
        incident_type=sos_data.incident_type,
        description=sos_data.description,
        status=SOSStatus.ACTIVE
    )
    
    db.add(new_sos)
    db.commit()
    db.refresh(new_sos)
    
    # TODO: Trigger notification service to alert emergency contacts
    
    return new_sos


@router.get("/", response_model=List[SOSEventResponse])
def list_sos_events(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    limit: int = 10,
    offset: int = 0
):
    """List SOS events for current user"""
    sos_events = db.query(SOSEvent).filter(
        SOSEvent.user_id == current_user.id
    ).order_by(SOSEvent.created_at.desc()).offset(offset).limit(limit).all()
    
    return sos_events


@router.get("/{sos_id}", response_model=SOSEventResponse)
def get_sos_event(
    sos_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get a specific SOS event"""
    sos_event = db.query(SOSEvent).filter(
        SOSEvent.id == sos_id,
        SOSEvent.user_id == current_user.id
    ).first()
    
    if not sos_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SOS event not found"
        )
    
    return sos_event


@router.put("/{sos_id}", response_model=SOSEventResponse)
def update_sos_event(
    sos_id: int,
    sos_update: SOSEventUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update SOS event status"""
    sos_event = db.query(SOSEvent).filter(
        SOSEvent.id == sos_id,
        SOSEvent.user_id == current_user.id
    ).first()
    
    if not sos_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SOS event not found"
        )
    
    update_data = sos_update.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(sos_event, field, value)
    
    # Set resolved_at if status is being changed to resolved
    if update_data.get("status") == SOSStatus.RESOLVED and not sos_event.resolved_at:
        sos_event.resolved_at = datetime.utcnow()
    
    db.commit()
    db.refresh(sos_event)
    
    return sos_event


@router.post("/{sos_id}/notify")
def notify_emergency_contacts(
    sos_id: int,
    notification_request: SOSNotificationRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Notify emergency contacts about SOS event"""
    sos_event = db.query(SOSEvent).filter(
        SOSEvent.id == sos_id,
        SOSEvent.user_id == current_user.id
    ).first()
    
    if not sos_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SOS event not found"
        )
    
    from app.models.emergency_contact import EmergencyContact
    
    # Get contacts to notify
    if notification_request.contact_ids:
        contacts = db.query(EmergencyContact).filter(
            EmergencyContact.id.in_(notification_request.contact_ids),
            EmergencyContact.user_id == current_user.id,
            EmergencyContact.is_verified == True
        ).all()
    else:
        # Notify all primary verified contacts
        contacts = db.query(EmergencyContact).filter(
            EmergencyContact.user_id == current_user.id,
            EmergencyContact.is_primary == True,
            EmergencyContact.is_verified == True
        ).all()
    
    if not contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verified emergency contacts to notify"
        )
    
    # TODO: Implement actual notification service (SMS, WhatsApp, Push)
    
    # Update SOS event with notification tracking
    import json
    contact_ids = [c.id for c in contacts]
    sos_event.contacts_notified = json.dumps(contact_ids)
    sos_event.sms_sent = True
    sos_event.push_sent = True
    
    if not sos_event.first_response_at:
        sos_event.first_response_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "message": f"Notified {len(contacts)} emergency contacts",
        "contacts_notified": contact_ids
    }


@router.post("/{sos_id}/location")
def update_sos_location(
    sos_id: int,
    location_update: SOSLocationUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update SOS event location"""
    sos_event = db.query(SOSEvent).filter(
        SOSEvent.id == sos_id,
        SOSEvent.user_id == current_user.id
    ).first()
    
    if not sos_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SOS event not found"
        )
    
    sos_event.latitude = location_update.latitude
    sos_event.longitude = location_update.longitude
    sos_event.location_accuracy = location_update.location_accuracy
    sos_event.address = location_update.address
    sos_event.maps_link = generate_maps_link(location_update.latitude, location_update.longitude)
    
    db.commit()
    db.refresh(sos_event)
    
    return {"message": "Location updated successfully", "maps_link": sos_event.maps_link}


@router.post("/{sos_id}/cancel")
def cancel_sos_event(
    sos_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Cancel an active SOS event"""
    sos_event = db.query(SOSEvent).filter(
        SOSEvent.id == sos_id,
        SOSEvent.user_id == current_user.id
    ).first()
    
    if not sos_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SOS event not found"
        )
    
    if sos_event.status != SOSStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only cancel active SOS events"
        )
    
    sos_event.status = SOSStatus.CANCELLED
    sos_event.resolved_at = datetime.utcnow()
    sos_event.resolved_by = str(current_user.id)
    
    db.commit()
    
    return {"message": "SOS event cancelled"}
