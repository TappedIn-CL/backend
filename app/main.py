from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# DB setup
from db.session import engine, Base

# Import models (IMPORTANT for table creation)
from app.models import user

# Import routes
from app.routers.user import router as user_router


app = FastAPI()

# -------------------------
# CORS (frontend connection)
# -------------------------
origins = [
    "http://localhost:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Create database tables
# -------------------------
Base.metadata.create_all(bind=engine)

# -------------------------
# Include API routes
# -------------------------
app.include_router(user_router, prefix="/users", tags=["users"])

# -------------------------
# Root endpoint
# -------------------------
@app.get("/")
def read_root():
    return {"message": "TappedIn API running 🚀"}