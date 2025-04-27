import subprocess
import json
from fastapi import (FastAPI, status, 
                     Depends, Request)
from starlette.concurrency import iterate_in_threadpool
import uvicorn
from pydantic import BaseModel
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from api.auth import verify_access
from api.encryption import ProxyEncryption
from scheduler.scheduler import Scheduler
from scheduler.celery_worker import unblock_proxy
from scheduler.unblock_all_proxies import unblocking_proxy_subprocess

app = FastAPI(
    title="Proxy Manager API",
    description="API for managing proxies with secure authentication",
    version="1.0.0",
    openapi_tags=[
        {"name": "proxies", "description": "Operations with proxies"},
        {"name": "reports", "description": "Operations with reports"},
    ]
)
encryption = ProxyEncryption()


class Report(BaseModel):
    proxy_id: int
    status: str
    error: str


@app.get("/get_proxy", status_code=status.HTTP_200_OK)
async def get_proxy(source_id: int, api_key: str = Depends(verify_access)):
    # request scheduler to get proxy for source
    scheduler = Scheduler()
    
    proxy_data = scheduler.get_proxy(source_id)[0][0]
    
    # Encrypt the proxy data before sending
    encrypted_proxy = encryption.encrypt_proxy(proxy_data)
    
    # Return encrypted data with instructions
    return {
        "encrypted_proxy": encrypted_proxy,
        "message": "This proxy data is encrypted. Use the provided client library to decrypt."
    }


@app.post("/send_report", status_code=status.HTTP_200_OK)
async def send_report(report: Report, api_key: str = Depends(verify_access)):
    # send report to scheduler
    scheduler = Scheduler()
    
    return {"message": "Report was received successfully."}


@app.middleware("http")
async def add_custom_header(request: Request, call_next):
    response = await call_next(request)

    if "/get_proxy" == request.url.path and response.status_code == 200:
        # Extract the response body
        response_body = [chunk async for chunk in response.body_iterator][0].decode()
        
        # Parse the response to get the encrypted proxy
        response_data = json.loads(response_body)
        
        # If the response contains encrypted_proxy, decrypt it for the unblock task
        if "encrypted_proxy" in response_data:
            # Decrypt the proxy data
            decrypted_proxy = encryption.decrypt_proxy(response_data["encrypted_proxy"])
            
            # Schedule the unblock task with the decrypted proxy
            unblock_proxy.apply_async(args=[decrypted_proxy])
        
    
    if "/send_report" == request.url.path and response.status_code == 200:
        # unblock proxy
        unblock_proxy.apply_async(args=[response_data])
        
        # Restore the response body
        response.body_iterator = iterate_in_threadpool(iter([response_body.encode()]))

    
    return response


# Add security scheme to OpenAPI
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Make sure components object exists
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    
    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    
    # Add schemas if they don't exist
    if "schemas" not in openapi_schema["components"]:
        openapi_schema["components"]["schemas"] = {}
    
    # Define the HTTPValidationError schema
    openapi_schema["components"]["schemas"]["HTTPValidationError"] = {
        "title": "HTTPValidationError",
        "type": "object",
        "properties": {
            "detail": {
                "title": "Detail",
                "type": "array",
                "items": {
                    "$ref": "#/components/schemas/ValidationError"
                }
            }
        }
    }
    
    # Define the ValidationError schema
    openapi_schema["components"]["schemas"]["ValidationError"] = {
        "title": "ValidationError",
        "type": "object",
        "properties": {
            "loc": {
                "title": "Location",
                "type": "array",
                "items": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "integer"}
                    ]
                }
            },
            "msg": {
                "title": "Message",
                "type": "string"
            },
            "type": {
                "title": "Error Type",
                "type": "string"
            }
        },
        "required": ["loc", "msg", "type"]
    }
    
    # Add security requirement to all operations
    for path in openapi_schema["paths"].values():
        for operation in path.values():
            operation["security"] = [{"BearerAuth": []}]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi


if __name__ == "__main__":
    # start redis sudo service redis-server start
    unblocking_proxy_subprocess.start()
    uvicorn.run(app, host="127.0.0.1", port=8000)
