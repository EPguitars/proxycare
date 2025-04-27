from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
import os
from dotenv import load_dotenv

load_dotenv()

# Get the secret from environment variables
API_SECRET = os.getenv("SECRETS")
if not API_SECRET:
    raise ValueError("API secret not found in environment variables")

# Define the header for API key authentication with Swagger UI support
API_KEY_NAME = "Authorization"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True, description="Enter: Bearer your-token-here")

async def verify_access(api_key: str = Depends(api_key_header)):
    """
    Verify the API key provided in the Authorization header.
    
    The key should be in the format: "Bearer YOUR_SECRET_KEY"
    """
    # Check if the API key has the correct format and value
    expected_key = f"Bearer {API_SECRET}"
    
    # Remove any extra whitespace and ensure case-sensitive comparison
    if api_key.strip() != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid API key. Expected format: 'Bearer TOKEN'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return API_SECRET




