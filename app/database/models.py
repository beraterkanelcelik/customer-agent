from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean,
    DateTime, Date, Time, ForeignKey, Index
)
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(100))
    email = Column(String(100))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    vehicles = relationship("Vehicle", back_populates="customer", lazy="selectin")
    appointments = relationship("Appointment", back_populates="customer", lazy="selectin")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    make = Column(String(50), nullable=False)
    model = Column(String(50), nullable=False)
    year = Column(Integer)
    license_plate = Column(String(20))
    vin = Column(String(17))
    created_at = Column(DateTime, server_default=func.now())

    customer = relationship("Customer", back_populates="vehicles")


class AppointmentTypeModel(Base):
    __tablename__ = "appointment_types"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    description = Column(Text)


class ServiceType(Base):
    __tablename__ = "service_types"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    estimated_duration_minutes = Column(Integer, nullable=False)
    estimated_price_min = Column(Float)
    estimated_price_max = Column(Float)


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True)
    make = Column(String(50), nullable=False)
    model = Column(String(50), nullable=False)
    year = Column(Integer, nullable=False)
    color = Column(String(30))
    price = Column(Float)
    is_new = Column(Boolean, default=True)
    is_available = Column(Boolean, default=True)
    stock_number = Column(String(20), unique=True)


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    appointment_type_id = Column(Integer, ForeignKey("appointment_types.id"), nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"))
    inventory_id = Column(Integer, ForeignKey("inventory.id"))
    service_type_id = Column(Integer, ForeignKey("service_types.id"))

    scheduled_date = Column(Date, nullable=False)
    scheduled_time = Column(Time, nullable=False)
    duration_minutes = Column(Integer, nullable=False)

    status = Column(String(20), default="scheduled", index=True)
    notes = Column(Text)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    customer = relationship("Customer", back_populates="appointments")
    service_type = relationship("ServiceType", lazy="joined")
    inventory_vehicle = relationship("Inventory", lazy="joined")

    __table_args__ = (
        Index("idx_appointments_date", "scheduled_date"),
        Index("idx_appointments_customer", "customer_id"),
    )


class FAQ(Base):
    __tablename__ = "faq"

    id = Column(Integer, primary_key=True)
    category = Column(String(50), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    keywords = Column(Text)


class ConversationLog(Base):
    __tablename__ = "conversation_logs"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(50), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    agent_type = Column(String(50))
    tool_calls = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class EscalationRequest(Base):
    __tablename__ = "escalation_requests"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(50), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    reason = Column(Text)
    status = Column(String(20), default="pending")
    human_agent_id = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())


class AvailabilitySlot(Base):
    """
    Pre-generated availability slots for appointment scheduling.

    These slots are populated on app startup for the next 30 days,
    following business hours and excluding Sundays and lunch breaks.

    For test drives, each vehicle has its own availability slots.
    """
    __tablename__ = "availability_slots"

    id = Column(Integer, primary_key=True)
    slot_date = Column(Date, nullable=False, index=True)
    slot_time = Column(Time, nullable=False)
    appointment_type = Column(String(20), nullable=False)  # "service" or "test_drive"
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=True)  # For test drives - which car
    is_available = Column(Boolean, default=True, index=True)
    booked_appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    appointment = relationship("Appointment", lazy="joined")
    vehicle = relationship("Inventory", lazy="joined")

    __table_args__ = (
        Index("idx_availability_date_type", "slot_date", "appointment_type"),
        Index("idx_availability_available", "slot_date", "is_available"),
        Index("idx_availability_vehicle", "inventory_id", "slot_date"),
    )
