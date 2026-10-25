import os

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from .models import Base, Vehicle


SAMPLE_VEHICLES = [
    ("Toyota", "Corolla Altis", 2022, 1850000, 6),
    ("Toyota", "Urban Cruiser Hyryder", 2024, 1740000, 8),
    ("Toyota", "Innova Hycross", 2023, 2650000, 4),
    ("Toyota", "Fortuner", 2022, 3890000, 3),
    ("Hyundai", "Creta", 2024, 1650000, 7),
    ("Hyundai", "Venue", 2023, 1120000, 9),
    ("Hyundai", "Verna", 2024, 1480000, 5),
    ("Honda", "City", 2023, 1420000, 6),
    ("Honda", "Elevate", 2024, 1590000, 5),
    ("Honda", "Amaze", 2022, 825000, 8),
    ("Tata", "Nexon", 2024, 1290000, 10),
    ("Tata", "Punch", 2023, 875000, 12),
    ("Tata", "Harrier", 2022, 2180000, 4),
    ("Mahindra", "Scorpio-N", 2024, 1920000, 5),
    ("Mahindra", "XUV700", 2023, 2350000, 4),
    ("Kia", "Seltos", 2024, 1720000, 6),
    ("Kia", "Sonet", 2023, 1120000, 7),
    ("BMW", "3 Series", 2022, 5650000, 2),
    ("Mercedes-Benz", "C-Class", 2023, 6950000, 2),
]


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./vehicles.db")
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    inserted = 0
    skipped = 0
    try:
        with session_factory() as session:
            for make, model, year, price, quantity in SAMPLE_VEHICLES:
                existing_id = session.scalar(
                    select(Vehicle.id).where(
                        Vehicle.make == make,
                        Vehicle.model == model,
                        Vehicle.year == year,
                    )
                )
                if existing_id is not None:
                    skipped += 1
                    continue

                session.add(
                    Vehicle(
                        make=make,
                        model=model,
                        year=year,
                        price=price,
                        quantity=quantity,
                    )
                )
                inserted += 1

            session.commit()
    finally:
        engine.dispose()

    print(f"Seed complete: inserted {inserted} vehicle(s), skipped {skipped} existing record(s).")


if __name__ == "__main__":
    main()
