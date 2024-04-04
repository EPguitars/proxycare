import os
import json

from fastapi import Query, HTTPException, status
from dotenv import load_dotenv

load_dotenv()
SECRETS = os.getenv("SECRETS") and json.loads(os.getenv("SECRETS")).values()


def verify_access(password: str = Query(..., description="The password for access")):
    """Simple authentication"""

    if password not in SECRETS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
            headers={"WWW-Authenticate": "Bearer"},
        )




