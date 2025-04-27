from typing import Dict, Any

def format_response(data: Any, message: str = "Success") -> Dict[str, Any]:
    return {
        "message": message,
        "data": data
    } 