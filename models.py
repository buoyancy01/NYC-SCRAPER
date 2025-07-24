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
class ScrapingResult(BaseModel):
    data: Optional[List[Dict[str, Any]]] = None
    error_message: Optional[str] = None
    captcha_solved: bool = False
    processing_time_seconds: float = 0.0

class ScrapingStatus(BaseModel):
    status: str  # "pending", "in_progress", "completed", "failed"
    progress: float = 0.0  # 0.0 to 1.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[ScrapingResult] = None
    request_context: Optional[Dict[str, Any]] = None  # Store original request for PDF generation

class ScrapingResultDB(BaseModel):
    """Database version with additional metadata"""
    license_plate: str
    state: str
    result: ScrapingResult
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    client_name: Optional[str] = None