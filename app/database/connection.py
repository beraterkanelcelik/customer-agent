from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine
from contextlib import asynccontextmanager

from app.config import get_settings
from .models import Base

settings = get_settings()

# Async engine
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_db() -> AsyncSession:
    """FastAPI dependency for database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context():
    """Context manager for database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def init_db():
    """Initialize database with tables and seed data."""
    # Use sync engine for initialization
    sync_url = settings.database_url.replace("+aiosqlite", "")
    sync_engine = create_engine(sync_url, echo=settings.debug)

    # Create tables
    Base.metadata.create_all(bind=sync_engine)

    # Seed data
    from sqlalchemy.orm import Session
    with Session(sync_engine) as session:
        from .models import FAQ, AppointmentTypeModel, ServiceType, Inventory

        # Check if already seeded
        if session.query(FAQ).count() > 0:
            return

        # Appointment types
        session.add_all([
            AppointmentTypeModel(name="service", display_name="Service Appointment",
                                duration_minutes=60, description="Maintenance and repairs"),
            AppointmentTypeModel(name="test_drive", display_name="Test Drive",
                                duration_minutes=30, description="Test drive a vehicle"),
        ])

        # Service types
        session.add_all([
            ServiceType(name="Oil Change", estimated_duration_minutes=30,
                       estimated_price_min=49.99, estimated_price_max=89.99),
            ServiceType(name="Tire Rotation", estimated_duration_minutes=30,
                       estimated_price_min=29.99, estimated_price_max=49.99),
            ServiceType(name="Brake Inspection", estimated_duration_minutes=45,
                       estimated_price_min=0, estimated_price_max=0),
            ServiceType(name="Brake Pad Replacement", estimated_duration_minutes=90,
                       estimated_price_min=150.00, estimated_price_max=300.00),
            ServiceType(name="Battery Replacement", estimated_duration_minutes=30,
                       estimated_price_min=100.00, estimated_price_max=200.00),
            ServiceType(name="General Inspection", estimated_duration_minutes=60,
                       estimated_price_min=49.99, estimated_price_max=99.99),
        ])

        # Inventory
        session.add_all([
            Inventory(make="Toyota", model="Camry", year=2025, color="Silver",
                     price=28999.00, is_new=True, stock_number="TC2025-001"),
            Inventory(make="Toyota", model="RAV4", year=2025, color="Blue",
                     price=34999.00, is_new=True, stock_number="TR2025-002"),
            Inventory(make="Honda", model="Civic", year=2024, color="Black",
                     price=24999.00, is_new=True, stock_number="HC2024-003"),
            Inventory(make="Honda", model="CR-V", year=2025, color="White",
                     price=32999.00, is_new=True, stock_number="HCR2025-004"),
            Inventory(make="Ford", model="Mustang", year=2024, color="Red",
                     price=42999.00, is_new=True, stock_number="FM2024-005"),
        ])

        # FAQ
        session.add_all([
            FAQ(category="hours", question="What are your opening hours?",
                answer="We are open Monday through Friday from 8 AM to 7 PM, Saturday from 9 AM to 5 PM, and closed on Sunday. Our service department opens at 7:30 AM on weekdays.",
                keywords="hours,open,close,time,when,schedule"),
            FAQ(category="hours", question="Is the service department open on weekends?",
                answer="Yes, our service department is open on Saturday from 9 AM to 4 PM. We are closed on Sunday.",
                keywords="service,weekend,saturday,sunday"),
            FAQ(category="location", question="Where are you located?",
                answer="We are located at 1234 Auto Drive, Springfield. We are right off Highway 101, next to the Springfield Mall. Free parking is available.",
                keywords="location,address,where,directions,find"),
            FAQ(category="financing", question="Do you offer financing?",
                answer="Yes, we offer competitive financing options through multiple lenders. We can work with all credit situations. Our finance team can help you find the best rate for your budget.",
                keywords="financing,loan,credit,payment,monthly,finance"),
            FAQ(category="services", question="What services do you offer?",
                answer="We offer a full range of services including oil changes, tire rotation, brake service, battery replacement, AC service, and general inspections. We service all makes and models.",
                keywords="services,offer,repair,maintenance,fix"),
            FAQ(category="services", question="How long does an oil change take?",
                answer="A standard oil change typically takes about 30 to 45 minutes. If you schedule an appointment, we can often complete it even faster.",
                keywords="oil,change,time,long,duration"),
            FAQ(category="general", question="Do you offer loaner vehicles?",
                answer="Yes, we offer complimentary loaner vehicles for service appointments expected to take more than 2 hours. Please request this when scheduling your appointment.",
                keywords="loaner,rental,car,borrow,vehicle"),
            FAQ(category="inventory", question="What cars do you sell?",
                answer="We sell new and certified pre-owned vehicles from Toyota, Honda, and Ford. Our current inventory includes the Toyota Camry and RAV4, Honda Civic and CR-V, and Ford Mustang. Would you like to schedule a test drive?",
                keywords="sell,buy,cars,vehicles,inventory,stock,have,available,purchase,new,used"),
            FAQ(category="inventory", question="Do you have any trucks or SUVs?",
                answer="Yes! We have several SUVs in stock including the Toyota RAV4 and Honda CR-V. For trucks, please ask about our current inventory as it changes frequently.",
                keywords="truck,suv,crossover,rav4,crv"),
        ])

        session.commit()
        print("Database seeded successfully!")
