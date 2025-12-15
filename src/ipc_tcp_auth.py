import hmac
import hashlib
import binascii
import secrets
from typing import Tuple

from config_manager import PBKDF2_ALGORITHM, PBKDF2_ITERATIONS
from constants import NONCE_BYTES

class AuthError(Exception):
    """Raised when authentication fails."""
    pass


def _generate_auth_challenge(password_info: dict) -> Tuple[dict, bytes]:
    """
    Generate an auth challenge message and the expected HMAC.
    
    Args:
        password_info: Dict with 'salt', 'hash', 'iterations' from credentials
        
    Returns:
        Tuple of (challenge_dict, expected_hmac_bytes)
    """
    nonce = secrets.token_hex(NONCE_BYTES)
    
    # Get stored hash (this is what client should derive from password)
    stored_hash_hex = password_info.get("hash", "")
    stored_hash = binascii.unhexlify(stored_hash_hex)
    
    # Compute expected HMAC using stored hash as key
    expected_hmac = hmac.new(stored_hash, nonce.encode('utf-8'), hashlib.sha256).digest()
    
    challenge = {
        "type": "auth_challenge",
        "salt": password_info.get("salt", ""),
        "iterations": password_info.get("iterations", PBKDF2_ITERATIONS),
        "nonce": nonce
    }
    
    return challenge, expected_hmac


def _compute_auth_response(password: str, salt_hex: str, iterations: int, nonce: str) -> str:
    """
    Compute the auth response HMAC from password and challenge.
    
    Args:
        password: User's plaintext password
        salt_hex: Salt from challenge (hex string)
        iterations: PBKDF2 iterations from challenge
        nonce: Random nonce from challenge
        
    Returns:
        HMAC as hex string
    """
    # Derive key using PBKDF2 (same as server-side password hashing)
    salt = binascii.unhexlify(salt_hex)
    key = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode('utf-8'),
        salt,
        iterations
    )
    
    # Compute HMAC of nonce using derived key
    response_hmac = hmac.new(key, nonce.encode('utf-8'), hashlib.sha256).digest()
    return binascii.hexlify(response_hmac).decode('ascii')


def _verify_auth_response(response_hmac_hex: str, expected_hmac: bytes) -> bool:
    """
    Verify client's HMAC response (constant-time comparison).
    
    Args:
        response_hmac_hex: Client's HMAC as hex string
        expected_hmac: Expected HMAC bytes
        
    Returns:
        True if valid, False otherwise
    """
    try:
        response_hmac = binascii.unhexlify(response_hmac_hex)
        return hmac.compare_digest(response_hmac, expected_hmac)
    except (binascii.Error, ValueError):
        return False
