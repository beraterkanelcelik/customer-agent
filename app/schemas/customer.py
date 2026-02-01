from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime


class VehicleBase(BaseModel):
    """Base vehicle schema."""
    make: str = Field(..., min_length=1, max_length=50, examples=["Toyota"])
    model: str = Field(..., min_length=1, max_length=50, examples=["Camry"])
    year: Optional[int] = Field(default=None, ge=1900, le=2030, examples=[2022])
    license_plate: Optional[str] = Field(default=None, max_length=20)
    vin: Optional[str] = Field(default=None, max_length=17)


class VehicleCreate(VehicleBase):
    """Create vehicle request."""
    pass


class VehicleResponse(VehicleBase):
    """Vehicle response with ID."""
    id: int
    customer_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class CustomerBase(BaseModel):
    """Base customer schema."""
    phone: str = Field(..., min_length=10, max_length=20, examples=["555-123-4567"])
    name: Optional[str] = Field(default=None, max_length=100, examples=["John Doe"])
    email: Optional[EmailStr] = Field(default=None, examples=["john@example.com"])


class CustomerCreate(CustomerBase):
    """Create customer request."""
    vehicle: Optional[VehicleCreate] = None


class CustomerUpdate(BaseModel):
    """Update customer request."""
    name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[EmailStr] = None


class CustomerResponse(CustomerBase):
    """Customer response with relationships."""
    id: int
    vehicles: List[VehicleResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerContext(BaseModel):
    """Customer context for conversation state."""
    customer_id: Optional[int] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    vehicles: List[dict] = Field(default_factory=list)

    @property
    def is_identified(self) -> bool:
        return self.customer_id is not None

    def to_summary(self) -> str:
        """Generate summary string for prompts."""
        if not self.is_identified:
            return "Customer not yet identified"

        summary = f"Customer: {self.name or 'Unknown'} (ID: {self.customer_id})"
        if self.phone:
            summary += f", Phone: {self.phone}"
        if self.vehicles:
            v = self.vehicles[0]
            summary += f", Vehicle: {v.get('year', '')} {v.get('make', '')} {v.get('model', '')}"
        return summary
