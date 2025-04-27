import os
import json
import base64
from typing import Any, Dict, Union
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

load_dotenv()

class ProxyEncryption:
    """Handles encryption and decryption of proxy data"""
    
    def __init__(self):
        # Get the encryption key from environment variables
        encryption_key = os.getenv("ENCRYPTION_KEY")
        if not encryption_key:
            raise ValueError("ENCRYPTION_KEY not found in environment variables")
        
        # Ensure the key is the correct length for Fernet
        if len(encryption_key) < 32:
            # If key is too short, derive a proper key using PBKDF2
            salt = b'proxy_manager_salt'  # A fixed salt is OK for this use case
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(encryption_key.encode()))
        else:
            # Ensure the key is properly formatted for Fernet
            key = base64.urlsafe_b64encode(encryption_key[:32].encode())
            
        self.cipher = Fernet(key)
    
    def encrypt_proxy(self, proxy_data: Union[Dict, str]) -> str:
        """
        Encrypts proxy data
        
        Args:
            proxy_data: The proxy data to encrypt (dict or string)
            
        Returns:
            str: Base64-encoded encrypted data
        """
        # Convert to JSON string if it's a dictionary
        if isinstance(proxy_data, dict):
            data = json.dumps(proxy_data)
        else:
            data = str(proxy_data)
            
        # Encrypt the data
        encrypted_data = self.cipher.encrypt(data.encode())
        
        # Return as base64 string
        return base64.urlsafe_b64encode(encrypted_data).decode()
    
    def decrypt_proxy(self, encrypted_data: str) -> Any:
        """
        Decrypts proxy data
        
        Args:
            encrypted_data: Base64-encoded encrypted data
            
        Returns:
            The decrypted proxy data (dict or string)
        """
        # Decode from base64
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_data)
        
        # Decrypt the data
        decrypted_data = self.cipher.decrypt(encrypted_bytes).decode()
        
        # Try to parse as JSON, return as string if not valid JSON
        try:
            return json.loads(decrypted_data)
        except json.JSONDecodeError:
            return decrypted_data 