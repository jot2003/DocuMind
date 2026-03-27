import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.models.database import init_db
from backend.routers.verify import router as verify_router
from backend.utils.config import settings, UPLOAD_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DocuMind eKYC API...")
    init_db()
    logger.info("Database initialized")

    from backend.routers.verify import get_ocr, get_vlm, get_face
    logger.info("Preloading AI models (this may take a minute on first run)...")
    get_ocr()
    get_vlm()
    get_face()
    logger.info("All AI models loaded and ready")

    yield
    logger.info("Shutting down DocuMind eKYC API...")


app = FastAPI(
    title="DocuMind eKYC API",
    description="Intelligent Vietnamese ID Card Verification using OCR + VLM + Face Matching",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_PATH)), name="uploads")
app.include_router(verify_router)
