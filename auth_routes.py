from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from auth_utils import (
    authenticate_user, create_user, get_current_user, create_session, 
    end_session, track_anonymous_usage, check_anonymous_usage_limit,
    get_anonymous_usage, ANONYMOUS_USAGE_LIMIT,
    log_ai_usage, AI_PROVIDER
)

# Auth router
router = APIRouter(prefix="/auth", tags=["authentication"])

# Models for request/response
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str

class UserResponse(BaseModel):
    email: str
    name: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str

class AuthStatusResponse(BaseModel):
    authenticated: bool
    user: Optional[UserResponse] = None
    anonymous_uses_remaining: Optional[int] = None
    anonymous_uses_limit: int = ANONYMOUS_USAGE_LIMIT
    ai_provider: str = AI_PROVIDER

# Rate limiting
request_counts = {}
rate_limit_window = 60  # 1 minute
rate_limit_max = 5  # 5 requests per minute

def check_rate_limit(ip_address: str) -> bool:
    """Simple rate limiting implementation"""
    current_time = time.time()
    if ip_address not in request_counts:
        request_counts[ip_address] = []
    
    # Remove old requests
    request_counts[ip_address] = [t for t in request_counts[ip_address] 
                                 if current_time - t < rate_limit_window]
    
    # Check limit
    if len(request_counts[ip_address]) >= rate_limit_max:
        return False
    
    # Add current request
    request_counts[ip_address].append(current_time)
    return True

# Routes
@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, request: Request, response: Response):
    """Register a new user"""
    ip = request.client.host
    
    # Apply rate limiting
    if not check_rate_limit(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later."
        )
    
    user = await create_user(user_data.email, user_data.password, user_data.name)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )
    
    # Create a session for the new user
    token, expires_at = await create_session(user["email"])
    
    # Set cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        expires=expires_at
    )
    
    return user

@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends()
):

    """Login and get access token"""
    ip = request.client.host
    
    # Apply rate limiting
    if not check_rate_limit(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later."
        )
    
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create a session
    token, expires_at = await create_session(user["email"])
    
    # Set cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        expires=expires_at
    )
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at
    }

@router.post("/logout")
async def logout(response: Response, token: str = Depends(get_current_user)):
    """Logout user by ending session"""
    if token:
        await end_session(token)
    
    # Clear cookie
    response.delete_cookie(key="session_token")
    
    return {"message": "Successfully logged out"}

@router.get("/me", response_model=UserResponse)
async def get_user_me(current_user: dict = Depends(get_current_user)):
    """Get current user information"""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return current_user

@router.get("/check", response_model=AuthStatusResponse)
async def check_auth_status(request: Request, current_user: dict = Depends(get_current_user)):
    """Check authentication status and anonymous usage"""
    ip = request.client.host
    
    if current_user:
        # User is authenticated
        return {
            "authenticated": True,
            "user": current_user,
            "anonymous_uses_remaining": None,
            "anonymous_uses_limit": ANONYMOUS_USAGE_LIMIT,
            "ai_provider": AI_PROVIDER
        }
    else:
        # Anonymous user - check usage
        uses = await get_anonymous_usage(ip)
        uses_remaining = max(0, ANONYMOUS_USAGE_LIMIT - uses)
        
        return {
            "authenticated": False,
            "user": None,
            "anonymous_uses_remaining": uses_remaining,
            "anonymous_uses_limit": ANONYMOUS_USAGE_LIMIT,
            "ai_provider": AI_PROVIDER
        }

@router.post("/track-usage")
async def track_usage(request: Request, current_user: dict = Depends(get_current_user)):
    """Track usage for anonymous users or return status for authenticated users"""
    ip = request.client.host
    
    if current_user:
        # Authenticated users have unlimited usage
        return {
            "authenticated": True,
            "usage_limited": False,
            "ai_provider": AI_PROVIDER
        }
    else:
        # Track anonymous usage
        usage = await track_anonymous_usage(ip)
        limited = usage["count"] > ANONYMOUS_USAGE_LIMIT
        
        return {
            "authenticated": False,
            "usage_limited": limited,
            "usage_count": usage["count"],
            "uses_remaining": max(0, ANONYMOUS_USAGE_LIMIT - usage["count"]),
            "ai_provider": AI_PROVIDER
        }