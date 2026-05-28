from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# DB setup
from db.session import engine, Base

# Import models (IMPORTANT for table creation)
from app.models import user
from app.models import event
from app.models import favorite
from app.models import going_to
from app.models import google_credentials
from app.models import friendship

# Import routes
from app.routers.event import router as event_router
from app.routers.user import router as user_router
from app.routers.agent import router as agent_router
from app.routers.integrations_google import router as integrations_google_router

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
# Include API routes
# -------------------------
app.include_router(user_router, prefix="/users", tags=["users"])
app.include_router(event_router, prefix="/events", tags=["events"])
app.include_router(agent_router, prefix="/agent", tags=["agent"])
app.include_router(
    integrations_google_router,
    prefix="/integrations/google",
    tags=["integrations-google"],
)

# -------------------------
# Root endpoint
# -------------------------
@app.get("/")
def read_root():
    return {"message": "TappedIn API running 🚀"}
