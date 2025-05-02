import os
import boto3
import jwt
from datetime import datetime, timedelta
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from typing import Optional, Dict, Any
import uuid
import hashlib
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme for token extraction
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

# DynamoDB configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
dynamodb = boto3.resource(
    'dynamodb',
    region_name=AWS_REGION,
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

# DynamoDB tables
users_table = dynamodb.Table('counterfeit_checker_users')
sessions_table = dynamodb.Table('counterfeit_checker_sessions')
usage_table = dynamodb.Table('counterfeit_checker_usage')

# Anonymous usage limit
ANONYMOUS_USAGE_LIMIT = 5

# Initialize AI providers
# OpenAI initialization
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Gemini initialization
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Determine AI provider to use
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower()

# Password hashing and verification functions
def verify_password(plain_password, hashed_password):
    """Verify a password against a hash"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    """Generate a hash for a password"""
    return pwd_context.hash(password)

# JWT token functions
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> Dict[str, Any]:
    """Decode a JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return {}

# User functions
async def get_user(email: str):
    """Get a user from the database"""
    response = users_table.get_item(Key={"email": email.lower()})
    user = response.get("Item")
    if user:
        return user
    return None

async def create_user(email: str, password: str, name: str):
    """Create a new user in the database"""
    hashed_password = get_password_hash(password)
    user = {
        "email": email.lower(),
        "hashed_password": hashed_password,
        "name": name,
        "disabled": False,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Check if user already exists
    existing_user = await get_user(email)
    if existing_user:
        return None
        
    # Create new user
    users_table.put_item(Item=user)
    # Remove hashed_password from returned user object
    user.pop("hashed_password")
    return user

async def authenticate_user(email: str, password: str):
    """Authenticate a user"""
    user = await get_user(email)
    if not user:
        return False
    if not verify_password(password, user.get("hashed_password")):
        return False
    return user

# Session management
async def create_session(user_email: str):
    """Create a new session for a user"""
    token = str(uuid.uuid4())
    expires_at = (datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)).isoformat()
    
    session = {
        "token": token,
        "user_email": user_email,
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": expires_at
    }
    
    sessions_table.put_item(Item=session)
    return token, expires_at

async def validate_session(token: str):
    """Validate a session token"""
    if not token:
        return None
        
    response = sessions_table.get_item(Key={"token": token})
    session = response.get("Item")
    
    if not session:
        return None
        
    # Check if session is expired
    expires_at = datetime.fromisoformat(session.get("expires_at"))
    if expires_at < datetime.utcnow():
        return None
        
    # Return the user associated with this session
    user = await get_user(session.get("user_email"))
    if user and not user.get("disabled", False):
        return user
        
    return None

async def end_session(token: str):
    """End a session by deleting it"""
    sessions_table.delete_item(Key={"token": token})
    return True

# Anonymous usage tracking
def get_client_id(ip_address: str):
    """Generate a consistent client ID from an IP address"""
    return hashlib.md5(ip_address.encode()).hexdigest()

async def track_anonymous_usage(ip_address: str):
    """Track anonymous usage by IP address"""
    client_id = get_client_id(ip_address)
    now = datetime.utcnow().isoformat()
    
    # Try to get existing usage record
    response = usage_table.get_item(Key={"client_id": client_id})
    usage = response.get("Item")
    
    if not usage:
        # Create new usage record
        usage = {
            "client_id": client_id,
            "count": 1,
            "first_used": now,
            "last_used": now
        }
        usage_table.put_item(Item=usage)
    else:
        # Update existing usage record
        usage_table.update_item(
            Key={"client_id": client_id},
            UpdateExpression="SET #count = #count + :inc, #last = :now",
            ExpressionAttributeNames={
                "#count": "count",
                "#last": "last_used"
            },
            ExpressionAttributeValues={
                ":inc": 1,
                ":now": now
            }
        )
        usage["count"] += 1
    
    return usage

async def get_anonymous_usage(ip_address: str):
    """Get anonymous usage count by IP address"""
    client_id = get_client_id(ip_address)
    
    response = usage_table.get_item(Key={"client_id": client_id})
    usage = response.get("Item")
    
    if not usage:
        return 0
    
    return usage.get("count", 0)

async def check_anonymous_usage_limit(ip_address: str):
    """Check if anonymous usage limit has been reached"""
    count = await get_anonymous_usage(ip_address)
    return count >= ANONYMOUS_USAGE_LIMIT

# Dependency to get the current user from token
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Get the current user from the session token"""
    if not token:
        return None
    
    user = await validate_session(token)
    return user

# AI provider functions for rate limiting
def log_ai_usage(provider, function_type, success, error_message=None):
    """
    Log AI usage for monitoring.
    
    Args:
        provider (str): The AI provider used (gemini/openai)
        function_type (str): The type of function call (text/vision)
        success (bool): Whether the call was successful
        error_message (str, optional): Error message if the call failed
    """
    try:
        # Log to file or database
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "provider": provider,
            "function_type": function_type,
            "success": success,
            "error": error_message
        }
        
        logger.info(f"AI Usage: {json.dumps(log_entry)}")
        
    except Exception as e:
        logger.error(f"Error logging AI usage: {str(e)}")