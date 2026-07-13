from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, emergency_contacts, sos

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(emergency_contacts.router, prefix="/emergency-contacts", tags=["Emergency Contacts"])
api_router.include_router(sos.router, prefix="/sos", tags=["SOS"])
