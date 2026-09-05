import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import Show
from app.seed import run as run_seed

def seed_if_empty():
    engine = create_engine(os.environ["DATABASE_URL"])
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        count = session.query(Show).count()
        if count == 0:
            print("Database empty — running seed script...")
            run_seed()
        else:
            print(f"Database already has {count} shows — skipping seed.")
    finally:
        session.close()

if __name__ == "__main__":
    seed_if_empty()