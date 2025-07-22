import os
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, APIRouter, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from contextlib import asynccontextmanager
from models import (
    ScrapingStatus, 
    ScrapingResult, 
    ViolationSearchRequest, 
    StatusCheck, 
    StatusCheckCreate,
    ScrapingResultDB
)
# In server.py:
from scraper import NYCViolationsScraperV2

@app.post("/search-violations")
async def search_violations(request: ViolationRequest):
    api_key = os.getenv('TWOCAPTCHA_API_KEY')
    scraper = NYCViolationsScraperV2(captcha_api_key=api_key)
    result = await scraper.scrape_violations(request.license_plate, request.state)
    return result

from captcha_client import CaptchaClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'nyc_violations')]

# Get CAPTCHA API key
captcha_api_key = os.environ.get('CAPTCHA_API_KEY')
if not captcha_api_key:
    logger.warning("CAPTCHA_API_KEY not found in environment variables")

# Initialize scraper and CAPTCHA client
scraper = NYCViolationScraper(captcha_api_key)
captcha_client = CaptchaClient(captcha_api_key)

# In-memory storage for scraping status (in production, use Redis or database)
scraping_jobs: Dict[str, ScrapingStatus] = {}

# Create the main app
app = FastAPI(
    title="NYC Parking Violations Scraper",
    description="API for scraping NYC parking violations by license plate",
    version="1.0.0"
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

@api_router.get("/health")
async def health_check():
    try:
        # Check database connection
        await db.admin.command('ping')
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "database": "connected",
            "total_jobs": len(scraping_jobs)
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }

@api_router.post("/search-violations")
async def search_violations(
    request: ViolationSearchRequest,
    background_tasks: BackgroundTasks
):
    """
    Start a new violation search job
    """
    job_id = str(uuid.uuid4())
    
    # Initialize job status
    scraping_jobs[job_id] = ScrapingStatus(
        status="pending",
        started_at=datetime.utcnow()
    )
    
    # Start background scraping task
    background_tasks.add_task(perform_scraping, job_id, request)
    
    # For demo purposes, we'll wait a bit and return results immediately
    # In production, you might want to return the job_id and have the client poll for status
    await asyncio.sleep(1)  # Brief delay to simulate processing
    
    # Perform the scraping
    try:
        scraping_jobs[job_id].status = "in_progress"
        scraping_jobs[job_id].progress = 0.5
        
        result = await scraper.scrape_violations(request)
        
        scraping_jobs[job_id].status = "completed"
        scraping_jobs[job_id].progress = 1.0
        scraping_jobs[job_id].completed_at = datetime.utcnow()
        scraping_jobs[job_id].result = result
        
        # Store result in database
        await store_scraping_result(request, result)
        
        return {
            "job_id": job_id,
            "status": scraping_jobs[job_id].status,
            "result": result
        }
        
    except Exception as e:
        logger.error(f"Error in scraping job {job_id}: {e}")
        scraping_jobs[job_id].status = "failed"
        scraping_jobs[job_id].result = ScrapingResult(
            error_message=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/job-status/{job_id}")
async def get_job_status(job_id: str):
    """
    Get the status of a scraping job
    """
    if job_id not in scraping_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return scraping_jobs[job_id]

@api_router.post("/status-check")
async def create_status_check(status_check: StatusCheckCreate):
    """
    Log a status check from a client
    """
    try:
        check = StatusCheck(
            client_name=status_check.client_name,
            timestamp=datetime.utcnow()
        )
        
        # Store in database
        await db.status_checks.insert_one(check.dict())
        
        return {
            "message": "Status check logged",
            "check_id": check.id,
            "timestamp": check.timestamp
        }
    except Exception as e:
        logger.error(f"Error logging status check: {e}")
        raise HTTPException(status_code=500, detail="Failed to log status check")

async def perform_scraping(job_id: str, request: ViolationSearchRequest):
    """
    Background task to perform the actual scraping
    """
    try:
        logger.info(f"Starting scraping job {job_id} for {request.license_plate}")
        
        # Update status
        scraping_jobs[job_id].status = "in_progress"
        scraping_jobs[job_id].progress = 0.1
        
        # Perform scraping
        result = await scraper.scrape_violations(request)
        
        # Update final status
        scraping_jobs[job_id].status = "completed"
        scraping_jobs[job_id].progress = 1.0
        scraping_jobs[job_id].completed_at = datetime.utcnow()
        scraping_jobs[job_id].result = result
        
        # Store result in database
        await store_scraping_result(request, result)
        
        logger.info(f"Completed scraping job {job_id}")
        
    except Exception as e:
        logger.error(f"Error in background scraping job {job_id}: {e}")
        scraping_jobs[job_id].status = "failed"
        scraping_jobs[job_id].result = ScrapingResult(
            error_message=str(e)
        )

async def store_scraping_result(request: ViolationSearchRequest, result: ScrapingResult):
    """
    Store scraping result in database
    """
    try:
        result_doc = ScrapingResultDB(
            license_plate=request.license_plate,
            state=request.state,
            result=result
        )
        
        await db.scraping_results.insert_one(result_doc.dict())
        logger.info(f"Stored result for {request.license_plate} in database")
        
    except Exception as e:
        logger.error(f"Error storing result in database: {e}")

# Include the API router in the main app
app.include_router(api_router)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint to serve the frontend (FLAT STRUCTURE VERSION)
@app.get("/")
async def read_root():
    """Serve the main dashboard HTML file - Single folder version"""
    try:
        import os
        # Look for dashboard.html in the same directory as this script
        possible_paths = [
            os.path.join(os.path.dirname(__file__), 'dashboard.html'),  # Same directory
            './dashboard.html',  # Current working directory
            'dashboard.html',  # Relative path
        ]
        
        for html_path in possible_paths:
            if os.path.exists(html_path):
                logger.info(f"Serving frontend from: {html_path}")
                return FileResponse(html_path)
        
        # If no frontend file found, return API info
        logger.warning("dashboard.html not found in current directory")
        return {
            "message": "NYC Violations Scraper API",
            "status": "running",
            "note": "dashboard.html not found in current directory",
            "endpoints": {
                "health": "/api/health",
                "search": "/api/search-violations",
                "docs": "/docs"
            },
            "instructions": "Place dashboard.html in the same directory as server.py"
        }
    except Exception as e:
        logger.error(f"Error serving frontend: {e}")
        return {
            "message": "NYC Violations Scraper API",
            "error": str(e),
            "docs": "/docs"
        }

@app.on_event("startup")
async def startup_event():
    logger.info("Starting NYC Violations Scraper API")
    logger.info(f"MongoDB URL: {mongo_url}")
    logger.info(f"Database: {db.name}")
    
    # Test database connection
    try:
        await db.admin.command('ping')
        logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down NYC Violations Scraper API")
    client.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 8001)),
        reload=os.environ.get("DEBUG", "False").lower() == "true"
    )