import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'users' AND table_schema = 'public' "
        "ORDER BY ordinal_position"
    )).fetchall()
    print(f"users table has {len(rows)} columns:")
    for name, dtype in rows:
        print(f"  {name:30s} {dtype}")
