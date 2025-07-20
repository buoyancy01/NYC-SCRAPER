from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

# Original Status Check Models
class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class StatusCheckCreate(BaseModel):
    client_name: str

# Request Models
class ViolationSearchRequest(BaseModel):
    license_plate: str = Field(..., description="License plate number")
    state: str = Field(..., description="State abbreviation (e.g., NY, NJ, CT)")

# Response Models
class ViolationDetail(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticket_number: Optional[str] = None
    violation_date: Optional[str] = None
    violation_code: Optional[str] = None
    violation_description: Optional[str] = None
    fine_amount: Optional[float] = None
    penalty_amount: Optional[float] = None
    total_amount: Optional[float] = None
    status: Optional[str] = None
    due_date: Optional[str] = None
    location: Optional[str] = None
    pdf_url: Optional[str] = None
    pdf_downloaded: bool = False
    pdf_path: Optional[str] = None

class ScrapingResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    license_plate: str
    state: str
    search_timestamp: datetime = Field(default_factory=datetime.utcnow)
    success: bool = False
    violations: List[ViolationDetail] = []
    total_violations: int = 0
    total_amount_due: float = 0.0
    error_message: Optional[str] = None
    captcha_solved: bool = False
    processing_time_seconds: Optional[float] = None
    
class ScrapingStatus(BaseModel):
    id: str
    status: str  # "pending", "processing", "completed", "failed"
    progress: str = "Initializing..."
    started_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[ScrapingResult] = None

# Database Models
class ScrapingResultDB(ScrapingResult):
    """Database version with additional metadata"""
    _id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)