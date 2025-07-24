"""
Updated NYC Violations Server - Using Official NYC Open Data API
This version uses the official API instead of web scraping, eliminating CAPTCHA issues
"""

import os
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, APIRouter, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from motor.motor_asyncio import AsyncIOMotorClient
from models import (
    ScrapingStatus, 
    ScrapingResult, 
    ViolationSearchRequest, 
    StatusCheck, 
    StatusCheckCreate,
    ScrapingResultDB
)
from nyc_api_client import NYCViolationsAPI
from pdf_generator import ViolationsPDFGenerator

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'nyc_violations')]

# Initialize API client (no CAPTCHA needed!)
api_client = NYCViolationsAPI()

# Initialize PDF generator
pdf_generator = ViolationsPDFGenerator()

# In-memory storage for job status (in production, use Redis or database)
scraping_jobs: Dict[str, ScrapingStatus] = {}

# Create the main app
app = FastAPI(
    title="NYC Parking Violations API",
    description="API for retrieving NYC parking violations by license plate using official NYC Open Data",
    version="2.0.0"
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
            "total_jobs": len(scraping_jobs),
            "api_version": "2.0.0 - NYC Open Data API",
            "no_captcha_required": True
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
    Search for violations using NYC Open Data API (no CAPTCHA required!)
    """
    job_id = str(uuid.uuid4())
    
    # Initialize job status
    scraping_jobs[job_id] = ScrapingStatus(
        status="pending",
        started_at=datetime.utcnow()
    )
    
    # Start background API call
    background_tasks.add_task(perform_api_search, job_id, request)
    
    # For immediate response, also perform the search synchronously
    try:
        scraping_jobs[job_id].status = "in_progress"
        scraping_jobs[job_id].progress = 0.5
        
        # Use NYC Open Data API instead of web scraping
        api_result = await api_client.search_violations(request.license_plate, request.state)
        
        # Convert API result to our expected format
        result = convert_api_result_to_scraping_result(api_result)
        
        scraping_jobs[job_id].status = "completed"
        scraping_jobs[job_id].progress = 1.0
        scraping_jobs[job_id].completed_at = datetime.utcnow()
        scraping_jobs[job_id].result = result
        
        # Store result in database
        await store_scraping_result(request, result)
        
        return {
            "job_id": job_id,
            "status": scraping_jobs[job_id].status,
            "result": result,
            "api_version": "2.0.0",
            "method": "NYC Open Data API",
            "captcha_required": False
        }
        
    except Exception as e:
        logger.error(f"Error in API search job {job_id}: {e}")
        scraping_jobs[job_id].status = "failed"
        scraping_jobs[job_id].result = ScrapingResult(
            error_message=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/job-status/{job_id}")
async def get_job_status(job_id: str):
    """
    Get the status of an API search job
    """
    if job_id not in scraping_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return scraping_jobs[job_id]

@api_router.get("/download-pdf/{job_id}")
async def download_violations_pdf(job_id: str):
    """
    Download violations report as PDF
    """
    if job_id not in scraping_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = scraping_jobs[job_id]
    if job.status != "completed" or not job.result or job.result.error_message:
        raise HTTPException(status_code=400, detail="Job not completed successfully or has errors")
    
    try:
        # Extract license plate and state from job context (we'll need to store this)
        # For now, we'll extract from the stored result data
        violations_data = {
            'success': True,
            'violations': job.result.data or [],
            'total_violations': len(job.result.data) if job.result.data else 0
        }
        
        # Get plate and state from first violation if available
        if violations_data['violations']:
            first_violation = violations_data['violations'][0]
            license_plate = first_violation.get('plate', 'UNKNOWN')
            state = first_violation.get('state', 'UNKNOWN')
        else:
            license_plate = 'UNKNOWN'
            state = 'UNKNOWN'
        
        # Generate PDF
        pdf_bytes = pdf_generator.generate_violation_report(license_plate, state, violations_data)
        
        # Create filename
        filename = f"violations_report_{license_plate}_{state}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        # Return PDF as download
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"Error generating PDF for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")

@api_router.post("/search-violations-with-pdf")
async def search_violations_with_pdf_option(
    request: ViolationSearchRequest,
    background_tasks: BackgroundTasks
):
    """
    Search for violations and provide option to download PDF
    """
    job_id = str(uuid.uuid4())
    
    # Initialize job status
    scraping_jobs[job_id] = ScrapingStatus(
        status="pending",
        started_at=datetime.utcnow()
    )
    
    # Start background API call
    background_tasks.add_task(perform_api_search_with_context, job_id, request)
    
    # For immediate response, also perform the search synchronously
    try:
        scraping_jobs[job_id].status = "in_progress"
        scraping_jobs[job_id].progress = 0.5
        
        # Use NYC Open Data API instead of web scraping
        api_result = await api_client.search_violations(request.license_plate, request.state)
        
        # Convert API result to our expected format
        result = convert_api_result_to_scraping_result(api_result)
        
        scraping_jobs[job_id].status = "completed"
        scraping_jobs[job_id].progress = 1.0
        scraping_jobs[job_id].completed_at = datetime.utcnow()
        scraping_jobs[job_id].result = result
        
        # Store the original request context for PDF generation
        scraping_jobs[job_id].request_context = {
            'license_plate': request.license_plate,
            'state': request.state
        }
        
        # Store result in database
        await store_scraping_result(request, result)
        
        response = {
            "job_id": job_id,
            "status": scraping_jobs[job_id].status,
            "result": result,
            "api_version": "2.0.0",
            "method": "NYC Open Data API",
            "captcha_required": False
        }
        
        # Add PDF download link if violations found
        if result.data and len(result.data) > 0:
            response["pdf_download_url"] = f"/api/download-pdf/{job_id}"
            response["pdf_available"] = True
        else:
            response["pdf_available"] = False
            response["message"] = "No violations found - PDF not available"
        
        return response
        
    except Exception as e:
        logger.error(f"Error in API search job {job_id}: {e}")
        scraping_jobs[job_id].status = "failed"
        scraping_jobs[job_id].result = ScrapingResult(
            error_message=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/generate-pdf")
async def generate_pdf_direct(
    request: ViolationSearchRequest
):
    """
    Generate PDF directly without storing job
    """
    try:
        # Get violation data
        api_result = await api_client.search_violations(request.license_plate, request.state)
        
        if not api_result['success']:
            raise HTTPException(status_code=400, detail=api_result.get('error', 'Failed to retrieve violations'))
        
        # Generate PDF
        pdf_bytes = pdf_generator.generate_violation_report(request.license_plate, request.state, api_result)
        
        # Create filename
        filename = f"violations_report_{request.license_plate}_{request.state}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        # Return PDF as download
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating direct PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")

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

async def perform_api_search_with_context(job_id: str, request: ViolationSearchRequest):
    """
    Background task to perform the actual API search with request context stored
    """
    try:
        logger.info(f"Starting API search job {job_id} for {request.license_plate}")
        
        # Update status
        scraping_jobs[job_id].status = "in_progress"
        scraping_jobs[job_id].progress = 0.1
        
        # Store request context for PDF generation
        scraping_jobs[job_id].request_context = {
            'license_plate': request.license_plate,
            'state': request.state
        }
        
        # Perform API search
        api_result = await api_client.search_violations(request.license_plate, request.state)
        result = convert_api_result_to_scraping_result(api_result)
        
        # Update final status
        scraping_jobs[job_id].status = "completed"
        scraping_jobs[job_id].progress = 1.0
        scraping_jobs[job_id].completed_at = datetime.utcnow()
        scraping_jobs[job_id].result = result
        
        # Store result in database
        await store_scraping_result(request, result)
        
        logger.info(f"Completed API search job {job_id}")
        
    except Exception as e:
        logger.error(f"Error in background API search job {job_id}: {e}")
        scraping_jobs[job_id].status = "failed"
        scraping_jobs[job_id].result = ScrapingResult(
            error_message=str(e)
        )

async def perform_api_search(job_id: str, request: ViolationSearchRequest):
    """
    Background task to perform the actual API search
    """
    try:
        logger.info(f"Starting API search job {job_id} for {request.license_plate}")
        
        # Update status
        scraping_jobs[job_id].status = "in_progress"
        scraping_jobs[job_id].progress = 0.1
        
        # Perform API search
        api_result = await api_client.search_violations(request.license_plate, request.state)
        result = convert_api_result_to_scraping_result(api_result)
        
        # Update final status
        scraping_jobs[job_id].status = "completed"
        scraping_jobs[job_id].progress = 1.0
        scraping_jobs[job_id].completed_at = datetime.utcnow()
        scraping_jobs[job_id].result = result
        
        # Store result in database
        await store_scraping_result(request, result)
        
        logger.info(f"Completed API search job {job_id}")
        
    except Exception as e:
        logger.error(f"Error in background API search job {job_id}: {e}")
        scraping_jobs[job_id].status = "failed"
        scraping_jobs[job_id].result = ScrapingResult(
            error_message=str(e)
        )

def convert_api_result_to_scraping_result(api_result: Dict) -> ScrapingResult:
    """
    Convert NYC API result to our ScrapingResult format
    """
    if api_result['success']:
        # Convert violations to the expected format
        violation_data = []
        for violation in api_result['violations']:
            violation_data.append({
                'summons_number': violation['summons_number'],
                'issue_date': violation['issue_date'],
                'violation': violation['violation_code'],
                'fine_amount': violation['fine_amount'],
                'amount_due': violation['amount_due'],
                'status': violation['status'],
                'agency': violation['issuing_agency'],
                'plate': violation['plate'],
                'state': violation['state']
            })
        
        return ScrapingResult(
            data=violation_data,
            captcha_solved=False,  # No CAPTCHA needed with API!
            processing_time_seconds=api_result['processing_time']
        )
    else:
        return ScrapingResult(
            error_message=api_result['error'],
            captcha_solved=False,
            processing_time_seconds=api_result['processing_time']
        )

async def store_scraping_result(request: ViolationSearchRequest, result: ScrapingResult):
    """
    Store API result in database
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

# Root endpoint to serve the frontend
@app.get("/")
async def read_root():
    """Serve the main dashboard HTML file"""
    try:
        import os
        # Look for dashboard.html in the same directory as this script
        possible_paths = [
            os.path.join(os.path.dirname(__file__), 'dashboard.html'),
            './dashboard.html',
            'dashboard.html',
        ]
        
        for html_path in possible_paths:
            if os.path.exists(html_path):
                logger.info(f"Serving frontend from: {html_path}")
                return FileResponse(html_path)
        
        # If no frontend file found, return API info
        logger.warning("dashboard.html not found in current directory")
        return {
            "message": "NYC Violations API v2.0.0",
            "status": "running",
            "method": "NYC Open Data API",
            "captcha_required": False,
            "note": "dashboard.html not found in current directory",
            "endpoints": {
                "health": "/api/health",
                "search": "/api/search-violations",
                "docs": "/docs"
            },
            "improvements": [
                "No CAPTCHA required",
                "Official NYC data source",
                "Faster response times",
                "More reliable service",
                "Real-time violation data"
            ]
        }
    except Exception as e:
        logger.error(f"Error serving frontend: {e}")
        return {
            "message": "NYC Violations API v2.0.0",
            "error": str(e),
            "docs": "/docs"
        }

@app.on_event("startup")
async def startup_event():
    logger.info("Starting NYC Violations API v2.0.0")
    logger.info("Using NYC Open Data API - No CAPTCHA required!")
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
    logger.info("Shutting down NYC Violations API v2.0.0")
    client.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server_api:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 8001)),
        reload=os.environ.get("DEBUG", "False").lower() == "true"
    )