import os
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

from auth_routes import router as auth_router
from auth_middleware import AuthMiddleware
from auth_utils import get_current_user

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="Counterfeit Risk Checker API",
    description="API for Counterfeit Risk Checker authentication and usage tracking",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",  # Streamlit local dev
        "https://counterfeit-risk-checker.onrender.com",  # Render deployment
        os.getenv("FRONTEND_URL", "*")  # Configurable frontend URL
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add session middleware
app.add_middleware(
    SessionMiddleware, 
    secret_key=os.getenv("SESSION_SECRET_KEY", "your-secret-key")
)

# Add auth middleware
app.add_middleware(AuthMiddleware)

# Include routers
app.include_router(auth_router)

# Root endpoint
@app.get("/")
async def root():
    return {"message": "Counterfeit Risk Checker API"}

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# User info endpoint (protected)
@app.get("/user")
async def get_user_info(current_user: dict = Depends(get_current_user)):
    if not current_user:
        return {"authenticated": False}
    
    return {
        "authenticated": True,
        "user": {
            "email": current_user.get("email"),
            "name": current_user.get("name")
        }
    }

# Run the server with uvicorn
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("api_server:app", host="0.0.0.0", port=port, reload=True)
