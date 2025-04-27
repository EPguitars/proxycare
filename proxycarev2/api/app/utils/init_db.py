from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.models import User, Token
from app.core.security import get_password_hash
from app.core.config import settings

def init_db():
    """
    Initialize user data. Tables are created by init.sql,
    but users are created here for better security and flexibility.
    """
    db = SessionLocal()
    try:
        # Check if root user exists
        if not db.query(User).filter(User.username == settings.ROOT_USER).first():
            print(f"Creating root user: {settings.ROOT_USER}")
            # Create root user
            hashed_password = get_password_hash(settings.ROOT_PASSWORD)
            db_user = User(username=settings.ROOT_USER, hashed_password=hashed_password)
            db.add(db_user)
            db.commit()
            db.refresh(db_user)
            
            # Add the SECRET as a token for the root user
            db_token = Token(token=settings.SECRET, user_id=db_user.id)
            db.add(db_token)
            db.commit()
            print(f"Root user created successfully with ID: {db_user.id}")
        else:
            print(f"Root user {settings.ROOT_USER} already exists")
    except Exception as e:
        print(f"Error creating root user: {str(e)}")
    finally:
        db.close() 