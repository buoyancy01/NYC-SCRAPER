from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import asyncio
import time
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import uuid
from datetime import datetime

# Import our scraper modules
from models import (
    StatusCheck, StatusCheckCreate, ViolationSearchRequest, 
    ScrapingResult, ScrapingStatus, ScrapingResultDB
)
from scraper import NYCServScraper


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Get CAPTCHA API key
captcha_api_key = os.environ.get('CAPTCHA_API_KEY')
if not captcha_api_key:
    logger.warning("CAPTCHA_API_KEY not found in environment variables")

# In-memory storage for scraping status (in production, use Redis or database)
scraping_jobs: Dict[str, ScrapingStatus] = {}

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.dict()
    status_obj = StatusCheck(**status_dict)
    _ = await db.status_checks.insert_one(status_obj.dict())
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find().to_list(1000)
    return [StatusCheck(**status_check) for status_check in status_checks]

# ========================================
# NYC Serv Scraper Endpoints
# ========================================

async def run_scraper_job(job_id: str, license_plate: str, state: str):
    """Background task to run the scraper"""
    try:
        # Update job status to processing
        if job_id in scraping_jobs:
            scraping_jobs[job_id].status = "processing"
            scraping_jobs[job_id].progress = "Initializing browser..."
        
        # Run the scraper
        async with NYCServScraper(captcha_api_key) as scraper:
            if job_id in scraping_jobs:
                scraping_jobs[job_id].progress = "Navigating to NYC Serv website..."
            
            start_time = time.time()
            result = await scraper.search_violations(license_plate, state)
            end_time = time.time()
            
            result.processing_time_seconds = end_time - start_time
            
            # Save result to database
            result_db = ScrapingResultDB(**result.dict())
            await db.scraping_results.insert_one(result_db.dict())
            
            # Update job status
            if job_id in scraping_jobs:
                scraping_jobs[job_id].status = "completed"
                scraping_jobs[job_id].progress = f"Found {len(result.violations)} violations"
                scraping_jobs[job_id].completed_at = datetime.utcnow()
                scraping_jobs[job_id].result = result
            
            logger.info(f"Scraper job {job_id} completed successfully")
            
    except Exception as e:
        error_msg = f"Scraper job failed: {str(e)}"
        logger.error(f"Job {job_id}: {error_msg}")
        
        # Update job status to failed
        if job_id in scraping_jobs:
            scraping_jobs[job_id].status = "failed"
            scraping_jobs[job_id].progress = error_msg
            scraping_jobs[job_id].completed_at = datetime.utcnow()

@api_router.post("/scraper/violations", response_model=dict)
async def start_violation_search(request: ViolationSearchRequest, background_tasks: BackgroundTasks):
    """
    Start a parking violation search for a license plate
    """
    try:
        if not captcha_api_key:
            raise HTTPException(status_code=500, detail="CAPTCHA API key not configured")
        
        # Create job ID
        job_id = str(uuid.uuid4())
        
        # Create job status
        job_status = ScrapingStatus(
            id=job_id,
            status="pending",
            progress="Job queued for processing...",
            started_at=datetime.utcnow()
        )
        
        scraping_jobs[job_id] = job_status
        
        # Start background task
        background_tasks.add_task(
            run_scraper_job, 
            job_id, 
            request.license_plate, 
            request.state
        )
        
        return {
            "job_id": job_id,
            "message": "Scraping job started successfully",
            "status": "pending",
            "check_status_url": f"/api/scraper/status/{job_id}"
        }
        
    except Exception as e:
        logger.error(f"Error starting scraper job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/scraper/status/{job_id}", response_model=ScrapingStatus)
async def get_scraping_status(job_id: str):
    """
    Get the status of a scraping job
    """
    if job_id not in scraping_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return scraping_jobs[job_id]

@api_router.get("/scraper/results/{job_id}", response_model=ScrapingResult)
async def get_scraping_results(job_id: str):
    """
    Get the results of a completed scraping job
    """
    if job_id not in scraping_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_status = scraping_jobs[job_id]
    
    if job_status.status != "completed":
        raise HTTPException(status_code=400, detail=f"Job is not completed. Current status: {job_status.status}")
    
    if not job_status.result:
        raise HTTPException(status_code=500, detail="Job completed but no result available")
    
    return job_status.result

@api_router.get("/scraper/history")
async def get_scraping_history(limit: int = 50):
    """
    Get historical scraping results from database
    """
    try:
        results = await db.scraping_results.find().sort("created_at", -1).limit(limit).to_list(length=limit)
        return [ScrapingResultDB(**result) for result in results]
    except Exception as e:
        logger.error(f"Error getting scraping history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/scraper/pdf/{ticket_number}")
async def download_violation_pdf(ticket_number: str):
    """
    Download PDF for a specific violation ticket
    """
    try:
        pdf_path = f"/app/backend/downloads/pdfs/ticket_{ticket_number}.pdf"
        
        if not os.path.exists(pdf_path):
            raise HTTPException(status_code=404, detail="PDF not found")
        
        return FileResponse(
            path=pdf_path,
            filename=f"ticket_{ticket_number}.pdf",
            media_type="application/pdf"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/scraper/health")
async def scraper_health_check():
    """
    Check scraper service health and 2captcha balance
    """
    try:
        if not captcha_api_key:
            return {
                "status": "unhealthy",
                "captcha_service": "not_configured",
                "message": "CAPTCHA API key not configured"
            }
        
        from captcha_client import TwoCaptchaClient
        captcha_client = TwoCaptchaClient(captcha_api_key)
        
        # Check balance
        balance = captcha_client.get_balance()
        
        return {
            "status": "healthy",
            "captcha_service": "connected" if balance is not None else "error",
            "captcha_balance": balance,
            "active_jobs": len([job for job in scraping_jobs.values() if job.status == "processing"]),
            "total_jobs": len(scraping_jobs)
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
