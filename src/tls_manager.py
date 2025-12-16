"""
TLS Certificate Manager for ZfDash TCP Transport

Handles automatic generation and management of self-signed TLS certificates
for encrypting TCP agent connections.
"""

import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Tuple, Optional
import ipaddress

# Import cryptography components
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# Debug logging (verbose messages only appear with --debug)
from debug_logging import log_debug


def ensure_server_certificate(cert_dir: Path) -> Tuple[Path, Path]:
    """
    Ensure server certificate exists, generate if missing.
    
    Args:
        cert_dir: Directory to store certificates
        
    Returns:
        Tuple of (cert_path, key_path)
    """
    cert_dir.mkdir(parents=True, exist_ok=True)
    
    cert_file = cert_dir / 'server-cert.pem'
    key_file = cert_dir / 'server-key.pem'
    
    if cert_file.exists() and key_file.exists():
        log_debug("TLS", f"Using existing certificate: {cert_file}")
        return cert_file, key_file
    
    print(f"TLS: Generating new self-signed certificate...", file=sys.stderr)  # Important - always show
    generate_self_signed_cert(cert_file, key_file)
    log_debug("TLS", f"Certificate generated: {cert_file}")
    
    return cert_file, key_file


def generate_self_signed_cert(cert_path: Path, key_path: Path):
    """
    Generate self-signed certificate valid for 10 years.
    
    Args:
        cert_path: Path to save certificate
        key_path: Path to save private key
    """
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    
    # Generate certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "ZfDash Agent"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ZfDash"),
    ])
    
    # Build certificate
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=3650))  # 10 years
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                x509.IPAddress(ipaddress.IPv6Address("::1")),
            ]),
            critical=False
        )
        .sign(private_key, hashes.SHA256())
    )
    
    # Save certificate
    with open(cert_path, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    # Save private key
    with open(key_path, 'wb') as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    # Set permissions
    os.chmod(key_path, 0o600)  # Private key: read/write owner only
    os.chmod(cert_path, 0o644)  # Certificate: readable by all
    
    log_debug("TLS", f"Certificate saved to {cert_path}")
    log_debug("TLS", f"Private key saved to {key_path} (permissions: 600)")


def get_certificate_fingerprint(cert_path: Path) -> str:
    """
    Get SHA256 fingerprint of certificate for verification.
    
    Args:
        cert_path: Path to certificate file
        
    Returns:
        Hex-encoded SHA256 fingerprint
    """
    with open(cert_path, 'rb') as f:
        cert_data = f.read()
        cert = x509.load_pem_x509_certificate(cert_data)
    
    fingerprint = cert.fingerprint(hashes.SHA256())
    return fingerprint.hex()


def get_certificate_fingerprint_from_der(cert_der: bytes) -> str:
    """
    Get SHA256 fingerprint from DER-encoded certificate.
    
    Args:
        cert_der: DER-encoded certificate bytes
        
    Returns:
        Hex-encoded SHA256 fingerprint
    """
    fingerprint = hashlib.sha256(cert_der).digest()
    return fingerprint.hex()


def load_trusted_certificates(config_dir: Path) -> dict:
    """
    Load trusted certificate fingerprints.
    
    Args:
        config_dir: User config directory
        
    Returns:
        Dictionary of {host:port -> cert_info}
    """
    trusted_certs_file = config_dir / 'trusted_certs.json'
    
    if not trusted_certs_file.exists():
        return {}
    
    try:
        with open(trusted_certs_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"TLS: Error loading trusted certificates: {e}", file=sys.stderr)
        return {}


def save_trusted_certificate(config_dir: Path, host: str, port: int, 
                            fingerprint: str, first_seen: bool = True):
    """
    Save trusted certificate fingerprint.
    
    Args:
        config_dir: User config directory
        host: Remote host
        port: Remote port
        fingerprint: Certificate fingerprint
        first_seen: True if this is first connection
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    trusted_certs_file = config_dir / 'trusted_certs.json'
    
    # Load existing
    trusted_certs = load_trusted_certificates(config_dir)
    
    host_key = f"{host}:{port}"
    
    if first_seen:
        trusted_certs[host_key] = {
            'fingerprint': fingerprint,
            'first_seen': datetime.now().isoformat(),
            'last_verified': datetime.now().isoformat()
        }
    else:
        # Update last verified
        if host_key in trusted_certs:
            trusted_certs[host_key]['last_verified'] = datetime.now().isoformat()
    
    # Save
    try:
        with open(trusted_certs_file, 'w') as f:
            json.dump(trusted_certs, f, indent=2)
    except IOError as e:
        print(f"TLS: Error saving trusted certificate: {e}", file=sys.stderr)


def verify_certificate_tofu(config_dir: Path, host: str, port: int, 
                           cert_der: bytes) -> Tuple[bool, Optional[str]]:
    """
    Verify certificate using Trust-on-First-Use.
    
    Args:
        config_dir: User config directory
        host: Remote host
        port: Remote port
        cert_der: DER-encoded certificate
        
    Returns:
        Tuple of (verified, error_message)
        - (True, None) if verified or first connection
        - (False, error_msg) if mismatch detected
    """
    fingerprint = get_certificate_fingerprint_from_der(cert_der)
    host_key = f"{host}:{port}"
    
    trusted_certs = load_trusted_certificates(config_dir)
    
    if host_key not in trusted_certs:
        # First connection - auto-trust
        log_debug("TLS", f"First connection to {host_key}")
        log_debug("TLS", f"Certificate fingerprint: {fingerprint[:16]}...")
        
        save_trusted_certificate(config_dir, host, port, fingerprint, first_seen=True)
        return True, None
    
    # Verify against stored fingerprint
    stored_fp = trusted_certs[host_key]['fingerprint']
    
    if fingerprint != stored_fp:
        error_msg = (
            f"Certificate mismatch for {host_key}!\n"
            f"Expected: {stored_fp[:16]}...\n"
            f"Received: {fingerprint[:16]}...\n"
            f"Possible MITM attack or certificate rotation."
        )
        print(f"TLS: {error_msg}", file=sys.stderr)
        return False, error_msg
    
    # Certificate matches - update last verified
    save_trusted_certificate(config_dir, host, port, fingerprint, first_seen=False)
    log_debug("TLS", f"Certificate verified for {host_key}")
    
    return True, None


def remove_trusted_certificate(config_dir: Path, host: str, port: int) -> bool:
    """
    Remove a trusted certificate (for re-trusting after cert change).
    
    Args:
        config_dir: User config directory
        host: Remote host
        port: Remote port
        
    Returns:
        True if removed, False if not found
    """
    trusted_certs = load_trusted_certificates(config_dir)
    host_key = f"{host}:{port}"
    
    if host_key in trusted_certs:
        del trusted_certs[host_key]
        
        trusted_certs_file = config_dir / 'trusted_certs.json'
        try:
            with open(trusted_certs_file, 'w') as f:
                json.dump(trusted_certs, f, indent=2)
            log_debug("TLS", f"Removed trusted certificate for {host_key}")
            return True
        except IOError as e:
            print(f"TLS: Error removing trusted certificate: {e}", file=sys.stderr)
            return False
    
    return False
