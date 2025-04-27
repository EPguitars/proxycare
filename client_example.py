import requests
import base64
import json
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

# Load environment variables (optional, for development)
load_dotenv()

# This should be the same key used on the server
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "YourVerySecretKeyHere1234567890123456")
API_SECRET = os.getenv("SECRETS", "X2VN8m7I3A")

def get_cipher():
    """Initialize the Fernet cipher with the encryption key"""
    if len(ENCRYPTION_KEY) < 32:
        # If key is too short, derive a proper key using PBKDF2
        salt = b'proxy_manager_salt'  # Must match server salt
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(ENCRYPTION_KEY.encode()))
    else:
        # Ensure the key is properly formatted for Fernet
        key = base64.urlsafe_b64encode(ENCRYPTION_KEY[:32].encode())
        
    return Fernet(key)

def get_proxy(source_id):
    """Get and decrypt a proxy from the server"""
    # Make request to the API with proper authentication
    headers = {"Authorization": f"Bearer {API_SECRET}"}
    
    response = requests.get(
        f"http://localhost:8000/get_proxy?source_id={source_id}",
        headers=headers
    )
    
    if response.status_code != 200:
        raise Exception(f"API error: {response.status_code} - {response.text}")
    
    # Get the encrypted proxy data
    data = response.json()
    encrypted_proxy = data.get("encrypted_proxy")
    
    if not encrypted_proxy:
        raise Exception("No encrypted proxy found in response")
    
    # Decrypt the proxy data
    cipher = get_cipher()
    encrypted_bytes = base64.urlsafe_b64decode(encrypted_proxy)
    decrypted_data = cipher.decrypt(encrypted_bytes).decode()
    
    # Try to parse as JSON
    try:
        return json.loads(decrypted_data)
    except json.JSONDecodeError:
        return decrypted_data

# Example usage
if __name__ == "__main__":
    try:
        proxy = get_proxy(1)
        print(f"Decrypted proxy: {proxy}")
    except Exception as e:
        print(f"Error: {e}") 