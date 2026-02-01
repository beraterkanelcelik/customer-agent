from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import date, time, datetime

from .enums import AppointmentType, AppointmentStatus


class TimeSlot(BaseModel):
    """Available time slot."""
    date: date
    start_time: time
    end_time: time
    is_available: bool = True

    def format_time(self) -> str:
        return self.start_time.strftime("%I:%M %p").lstrip("0")


class ServiceTypeResponse(BaseModel):
    """Service type info."""
    id: int
    name: str
    estimated_duration_minutes: int
    estimated_price_min: Optional[float] = None
    estimated_price_max: Optional[float] = None

    class Config:
        from_attributes = True

    def price_display(self) -> str:
        if self.estimated_price_min is None or self.estimated_price_min == 0:
            return "Free"
        if self.estimated_price_min == self.estimated_price_max:
            return f"${self.estimated_price_min:.2f}"
        return f"${self.estimated_price_min:.2f} - ${self.estimated_price_max:.2f}"


class InventoryVehicleResponse(BaseModel):
    """Inventory vehicle for test drives."""
    id: int
    make: str
    model: str
    year: int
    color: Optional[str] = None
    price: Optional[float] = None
    is_new: bool = True
    stock_number: Optional[str] = None

    class Config:
        from_attributes = True

    def display_name(self) -> str:
        return f"{self.year} {self.make} {self.model}"


class AppointmentBase(BaseModel):
    """Base appointment schema."""
    appointment_type: AppointmentType
    scheduled_date: date
    scheduled_time: time
    duration_minutes: int = Field(default=60, ge=15, le=480)
    notes: Optional[str] = Field(default=None, max_length=500)


class AppointmentCreate(AppointmentBase):
    """Create appointment request."""
    customer_id: int
    vehicle_id: Optional[int] = None
    inventory_id: Optional[int] = None
    service_type_id: Optional[int] = None


class AppointmentUpdate(BaseModel):
    """Update appointment request."""
    scheduled_date: Optional[date] = None
    scheduled_time: Optional[time] = None
    status: Optional[AppointmentStatus] = None
    notes: Optional[str] = None


class AppointmentResponse(AppointmentBase):
    """Appointment response."""
    id: int
    customer_id: int
    vehicle_id: Optional[int] = None
    inventory_id: Optional[int] = None
    service_type_id: Optional[int] = None
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
    created_at: datetime
    updated_at: datetime

    service_type: Optional[ServiceTypeResponse] = None
    inventory_vehicle: Optional[InventoryVehicleResponse] = None

    class Config:
        from_attributes = True

    def display_datetime(self) -> str:
        date_str = self.scheduled_date.strftime("%A, %B %d")
        time_str = self.scheduled_time.strftime("%I:%M %p").lstrip("0")
        return f"{date_str} at {time_str}"


class AvailabilityRequest(BaseModel):
    """Check availability request."""
    appointment_type: AppointmentType
    preferred_date: date
    preferred_time: Optional[time] = None


class AvailabilityResponse(BaseModel):
    """Availability check response."""
    available: bool
    slots: List[TimeSlot] = []
    next_available: Optional[date] = None
    message: str


class BookingConfirmation(BaseModel):
    """Booking confirmation."""
    success: bool
    appointment_id: Optional[int] = None
    confirmation_message: str
    appointment: Optional[AppointmentResponse] = None
