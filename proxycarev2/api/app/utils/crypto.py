import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def get_encryption_key(secret_key: str) -> bytes:
    """
    Derive a Fernet encryption key from the secret key.
    Uses PBKDF2 with a static salt (not ideal for high security,
    but consistent across app restarts).
    """
    # Use a static salt - this means the same secret produces the same key
    # For higher security, use a stored salt, but this works for our use case
    salt = b'proxycare_static_salt_value'
    
    # Generate a key using PBKDF2
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return key

def encrypt_proxy(proxy_data: dict, secret: str) -> dict:
    """
    Encrypt sensitive proxy fields before sending them.
    Returns a new dict with encrypted fields.
    """
    if not secret:
        # If no secret is provided, return data unencrypted
        return proxy_data
    
    try:
        # Create a new dictionary to hold the result
        encrypted_data = proxy_data.copy()
        
        # Generate key from secret
        key = get_encryption_key(secret)
        f = Fernet(key)
        
        # Encrypt the sensitive fields
        if 'proxy' in encrypted_data and encrypted_data['proxy']:
            # Encrypt the proxy string (host:port:user:pass)
            proxy_bytes = encrypted_data['proxy'].encode()
            encrypted_data['proxy'] = f.encrypt(proxy_bytes).decode()
            encrypted_data['_encrypted'] = True  # Flag to indicate encryption
        
        return encrypted_data
    except Exception as e:
        # On encryption error, log but return original
        # This prevents breaking existing functionality
        print(f"Encryption error: {e}")
        return proxy_data

def decrypt_proxy(proxy_data: dict, secret: str) -> dict:
    """
    Decrypt encrypted proxy fields.
    Returns a new dict with decrypted fields.
    """
    if not proxy_data.get('_encrypted', False):
        # If not encrypted, return as is
        return proxy_data
    
    try:
        # Create a new dictionary to hold the result
        decrypted_data = proxy_data.copy()
        
        # Generate key from secret
        key = get_encryption_key(secret)
        f = Fernet(key)
        
        # Decrypt the proxy field
        if 'proxy' in decrypted_data and decrypted_data['proxy']:
            proxy_bytes = decrypted_data['proxy'].encode()
            decrypted_data['proxy'] = f.decrypt(proxy_bytes).decode()
        
        # Remove the encryption flag
        if '_encrypted' in decrypted_data:
            del decrypted_data['_encrypted']
            
        return decrypted_data
    except Exception as e:
        # On decryption error, return original but remove encryption flag
        print(f"Decryption error: {e}")
        if '_encrypted' in proxy_data:
            proxy_data = proxy_data.copy()
            del proxy_data['_encrypted']
        return proxy_data 