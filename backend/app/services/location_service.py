from typing import Optional, Tuple
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import logging

logger = logging.getLogger(__name__)


class LocationService:
    """Service for geolocation and address operations"""
    
    def __init__(self):
        self.geocoder = Nominatim(user_agent="raven_safety_platform")
    
    def reverse_geocode(
        self,
        latitude: float,
        longitude: float
    ) -> Optional[str]:
        """Convert coordinates to address"""
        try:
            location = self.geocoder.reverse(
                f"{latitude}, {longitude}",
                exactly_one=True
            )
            if location:
                return location.address
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logger.error(f"Geocoding error: {e}")
        except Exception as e:
            logger.error(f"Unexpected geocoding error: {e}")
        
        return None
    
    def geocode(self, address: str) -> Optional[Tuple[float, float]]:
        """Convert address to coordinates"""
        try:
            location = self.geocoder.geocode(address, exactly_one=True)
            if location:
                return (location.latitude, location.longitude)
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logger.error(f"Geocoding error: {e}")
        except Exception as e:
            logger.error(f"Unexpected geocoding error: {e}")
        
        return None
    
    def calculate_distance(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float
    ) -> float:
        """Calculate distance between two coordinates in kilometers using Haversine formula"""
        from math import radians, cos, sin, asin, sqrt
        
        # Convert decimal degrees to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        
        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        
        # Radius of earth in kilometers
        r = 6371
        
        return c * r
    
    def generate_maps_link(
        self,
        latitude: float,
        longitude: float,
        provider: str = "google"
    ) -> str:
        """Generate maps link for location"""
        if provider == "google":
            return f"https://maps.google.com/?q={latitude},{longitude}"
        elif provider == "apple":
            return f"https://maps.apple.com/?ll={latitude},{longitude}"
        elif provider == "osm":
            return f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map=15/{latitude}/{longitude}"
        else:
            return f"https://maps.google.com/?q={latitude},{longitude}"


# Global location service instance
location_service = LocationService()
