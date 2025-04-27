from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

class TokenSchema(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class DataResponse(BaseModel):
    message: str
    data: Dict[str, Any] 