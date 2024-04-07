import os
import sys
import json

from fastapi import Query, HTTPException, status
from dotenv import load_dotenv

load_dotenv()
SECRETS = os.getenv("SECRETS") and json.loads(os.getenv("SECRETS")).values()
# added paths to the system path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def verify_access(password: str = Query(..., description="The password for access")):
    """Simple authentication"""

    if password not in SECRETS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
            headers={"WWW-Authenticate": "Bearer"},
        )




