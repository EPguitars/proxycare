from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    tokens = relationship("Token", back_populates="user")

class Token(Base):
    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="tokens")

class Source(Base):
    __tablename__ = "sources"
    
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), unique=True, nullable=False)
    proxies = relationship("Proxy", back_populates="source")

class Provider(Base):
    __tablename__ = "providers"
    
    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(50), unique=True, nullable=False)
    proxies = relationship("Proxy", back_populates="provider_relation")

class Status(Base):
    __tablename__ = "statuses"
    
    statusCode = Column(Integer, primary_key=True)
    shortDescription = Column(String(300), unique=True, nullable=False)
    statistics = relationship("Statistic", back_populates="status")

class Proxy(Base):
    __tablename__ = "proxies"
    
    id = Column(Integer, primary_key=True, index=True)
    proxy = Column(String(100), nullable=False)
    sourceid = Column(Integer, ForeignKey("sources.id"))
    priority = Column(Integer)
    blocked = Column(Boolean)
    provider = Column(Integer, ForeignKey("providers.id"))
    usage_interval = Column(Integer, default=30)
    updatedat = Column(DateTime, default=func.now())
    source = relationship("Source", back_populates="proxies")
    provider_relation = relationship("Provider", back_populates="proxies")


class Statistic(Base):
    __tablename__ = "statistics"
    
    id = Column(Integer, primary_key=True, index=True)
    proxyid = Column(Integer, ForeignKey("proxies.id"))
    statusid = Column(Integer, ForeignKey("statuses.statusCode"))
    status = relationship("Status", back_populates="statistics")
