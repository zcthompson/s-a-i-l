"""Build script for test database.

Usage:
  python scripts/build_test_db.py          # Build and seed test database
  python scripts/build_test_db.py --clean  # Remove old DB and rebuild

This script:
1. Removes any existing test database file
2. Creates a fresh SQLite database
3. Creates all tables
4. Seeds initial data (admin user, etc.)

The built database is stored in tests/backend/test.db (ignored by git).
"""

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import os
os.environ["SAIL_JWT_SECRET"] = "test-secret-for-unit-tests-only-00000000"
os.environ["SAIL_DATABASE_URL"] = str(PROJECT_ROOT / "tests/backend/test.db")

from backend.config import get_settings
from backend.models.use_case import Base, User
from backend.auth import hash_password

import argparse
import glob
import shutil


def clean_old_db():
    """Remove any old test database files."""
    db_path = PROJECT_ROOT / "tests/backend/test.db"
    
    # Remove all SQLite artifacts
    for pattern in [
        str(db_path),
        str(db_path) + "-wal",
        str(db_path) + "-shm",
        str(db_path) + "-journal",
    ]:
        if os.path.exists(pattern):
            print(f"Removing old file: {pattern}")
            os.remove(pattern)
    
    # Also remove any other test.db files that might exist
    for f in glob.glob(str(PROJECT_ROOT / "tests/backend" / "test.db*")):
        print(f"Removing old file: {f}")
        os.remove(f)


def build_db():
    """Create fresh database and seed it."""
    db_path = PROJECT_ROOT / "tests/backend/test.db"
    
    # Remove old DB
    clean_old_db()
    
    # Set environment for new DB
    os.environ["SAIL_DATABASE_URL"] = str(db_path)
    
    # Re-read settings (they were cached)
    # Clear any cache if it exists
    if hasattr(get_settings, 'cache_clear'):
        get_settings.cache_clear()
    
    settings = get_settings()
    print(f"Creating database at: {settings.database_url}")
    
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    
    # Create engine and tables
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("✓ Tables created")
    
    # Seed admin user
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Check if admin already exists
    admin = session.query(User).filter(User.username == "admin").first()
    if not admin:
        admin = User(
            username="admin",
            email="admin@test.local",
            hashed_password=hash_password("admin"),
            display_name="Administrator",
            department="IT",
            is_admin=1,
            approved=1,
            is_active=1,
        )
        session.add(admin)
        session.commit()
        print("✓ Admin user created")
    else:
        print("✓ Admin user already exists")
    
    session.close()
    
    print(f"\n✓ Test database built: {db_path}")
    print(f"  File size: {os.path.getsize(db_path):,} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and seed test database")
    parser.add_argument("--clean", action="store_true", help="Remove old DB files first")
    args = parser.parse_args()
    
    if args.clean:
        clean_old_db()
    
    build_db()
