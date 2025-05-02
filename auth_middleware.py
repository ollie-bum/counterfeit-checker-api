from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from auth_utils import (
    validate_session, check_anonymous_usage_limit, track_anonymous_usage, 
    log_ai_usage, AI_PROVIDER
)

class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware to check authentication and usage limits"""
    
    async def dispatch(self, request: Request, call_next):
        # Skip auth checks for auth routes
        if request.url.path.startswith("/auth/"):
            return await call_next(request)
            
        # Skip auth checks for static files
        if request.url.path.startswith("/static/"):
            return await call_next(request)
        
        # Get session token from cookie
        token = request.cookies.get("session_token")
        
        # Skip checks if it's not an API call that requires authentication
        if not (request.url.path.startswith("/api/") or 
                request.url.path == "/" or 
                request.url.path == ""):
            return await call_next(request)
        
        # Validate user session if token exists
        user = None
        if token:
            user = await validate_session(token)
            
        # If user is authenticated, allow the request
        if user:
            # Set user in request state
            request.state.user = user
            return await call_next(request)
        
        # For anonymous users, check usage limit
        client_ip = request.client.host
        
        # Skip limit check for home page or certain routes
        if request.url.path == "/" or request.url.path == "" or request.url.path == "/health" or request.url.path == "/provider":
            return await call_next(request)
            
        # Check if anonymous usage limit has been reached
        limit_reached = await check_anonymous_usage_limit(client_ip)
        
        if limit_reached:
            # Return 402 Payment Required (or 403 Forbidden) for anonymous users who reached their limit
            return JSONResponse(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                content={
                    "detail": "Anonymous usage limit reached. Please register or log in to continue.",
                    "code": "usage_limit_reached",
                    "ai_provider": AI_PROVIDER
                }
            )
        
        # Allow the request for anonymous users within their usage limit
        return await call_next(request)