"""
TLS Certificate Manager for ZfDash TCP Transport

Handles automatic generation and management of self-signed TLS certificates
for encrypting TCP agent connections.

Certificate generation uses a fallback chain:
1. Try 'cryptography' library (best API, if installed)
2. Fall back to 'openssl' CLI (available on most systems)
3. If neither available, TLS is disabled with a warning
"""

import os
import sys
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional

# Debug logging (verbose messages only appear with --debug)
# daemon_log with IMPORTANT level shows to users by default
from debug_logging import log_debug, daemon_log

# Cross-platform executable finder
from paths import find_executable

# =============================================================================
# Cryptography availability detection (lazy import)
# =============================================================================

CRYPTOGRAPHY_AVAILABLE = None  # Set on first use
OPENSSL_CLI_PATH = None  # Cached path to openssl binary


def _check_cryptography() -> bool:
    """Check if cryptography library is available."""
    global CRYPTOGRAPHY_AVAILABLE
    if CRYPTOGRAPHY_AVAILABLE is None:
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            CRYPTOGRAPHY_AVAILABLE = True
        except ImportError:
            CRYPTOGRAPHY_AVAILABLE = False
    return CRYPTOGRAPHY_AVAILABLE


def _find_openssl() -> Optional[str]:
    """Find openssl CLI binary using cross-platform search."""
    global OPENSSL_CLI_PATH
    if OPENSSL_CLI_PATH is None:
        OPENSSL_CLI_PATH = find_executable('openssl')
    return OPENSSL_CLI_PATH


# =============================================================================
# Certificate Generation - Multi-Fallback
# =============================================================================

def ensure_server_certificate(cert_dir: Path) -> Tuple[Path, Path]:
    """
    Ensure server certificate exists, generate if missing.
    
    Args:
        cert_dir: Directory to store certificates
        
    Returns:
        Tuple of (cert_path, key_path)
        
    Raises:
        RuntimeError: If certificate cannot be generated (no crypto available)
    """
    cert_dir.mkdir(parents=True, exist_ok=True)
    
    cert_file = cert_dir / 'server-cert.pem'
    key_file = cert_dir / 'server-key.pem'
    
    if cert_file.exists() and key_file.exists():
        log_debug("TLS", f"Using existing certificate: {cert_file}")
        return cert_file, key_file
    #ensure daemon logs this
    daemon_log("Generating new self-signed TLS certificate...", "INFO")
    
    # Try cryptography library first
    if _check_cryptography():
        daemon_log("Using 'cryptography' library for TLS cert generation", "IMPORTANT")
        _generate_cert_cryptography(cert_file, key_file)
        daemon_log(f"TLS certificate generated: {cert_file}", "IMPORTANT")
        return cert_file, key_file
    
    # Fall back to openssl CLI
    openssl_path = _find_openssl()
    if openssl_path:
        daemon_log(f"'cryptography' not available, using openssl CLI: {openssl_path}", "IMPORTANT")
        if _generate_cert_openssl(cert_file, key_file, openssl_path):
            daemon_log(f"TLS certificate generated: {cert_file}", "IMPORTANT")
            return cert_file, key_file
        else:
            daemon_log("openssl CLI failed to generate certificate", "ERROR")
            raise RuntimeError("Failed to generate certificate with openssl CLI")
    
    # No method available
    raise RuntimeError(
        "Cannot generate TLS certificate: neither 'cryptography' library nor 'openssl' CLI found.\n"
        "Options:\n"
        "  1. Install cryptography: pip install cryptography\n"
        "  2. Install OpenSSL: apt install openssl / brew install openssl\n"
        "  3. Manually create certs and place at:\n"
        f"     {cert_file}\n"
        f"     {key_file}\n"
        "  4. Run agent without TLS: --no-tls (not recommended)"
    )


def _generate_cert_cryptography(cert_path: Path, key_path: Path):
    """
    Generate self-signed certificate using cryptography library.
    Valid for 10 years.
    """
    # Import here to avoid top-level import failure
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from datetime import timedelta
    import ipaddress
    
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
    
    log_debug("TLS", f"Certificate generated with cryptography: {cert_path}")


def _generate_cert_openssl(cert_path: Path, key_path: Path, openssl_path: str) -> bool:
    """
    Generate self-signed certificate using openssl CLI.
    Valid for 10 years (3650 days).
    
    Returns:
        True if successful, False on error
    """
    # OpenSSL command for self-signed cert with SAN extension
    # Using -addext for subject alternative names (requires openssl 1.1.1+)
    cmd = [
        openssl_path, 'req',
        '-x509',                         # Self-signed certificate
        '-newkey', 'rsa:2048',           # Generate new RSA 2048-bit key
        '-keyout', str(key_path),        # Output private key
        '-out', str(cert_path),          # Output certificate
        '-days', '3650',                 # Valid for 10 years
        '-nodes',                        # No passphrase on key
        '-subj', '/CN=ZfDash Agent/O=ZfDash',  # Subject name
    ]
    
    # Try to add SAN extension (may fail on older openssl)
    cmd_with_san = cmd + [
        '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1'
    ]
    
    try:
        # First try with SAN extension
        result = subprocess.run(
            cmd_with_san,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            # SAN might not be supported, try without
            log_debug("TLS", "openssl -addext failed, trying without SAN extension")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
        
        if result.returncode != 0:
            print(f"TLS: openssl command failed: {result.stderr}", file=sys.stderr)
            return False
        
        # Set permissions
        os.chmod(key_path, 0o600)
        os.chmod(cert_path, 0o644)
        
        log_debug("TLS", f"Certificate generated with openssl CLI: {cert_path}")
        return True
        
    except subprocess.TimeoutExpired:
        print("TLS: openssl command timed out", file=sys.stderr)
        return False
    except Exception as e:
        print(f"TLS: Error running openssl: {e}", file=sys.stderr)
        return False


# =============================================================================
# Certificate Fingerprinting (stdlib only - no cryptography needed)
# =============================================================================

def get_certificate_fingerprint(cert_path: Path) -> str:
    """
    Get SHA256 fingerprint of certificate for verification.
    Uses openssl CLI if cryptography not available.
    
    Args:
        cert_path: Path to certificate file
        
    Returns:
        Hex-encoded SHA256 fingerprint
    """
    if _check_cryptography():
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        
        with open(cert_path, 'rb') as f:
            cert = x509.load_pem_x509_certificate(f.read())
        return cert.fingerprint(hashes.SHA256()).hex()
    
    # Fallback: use openssl CLI
    openssl_path = _find_openssl()
    if openssl_path:
        try:
            result = subprocess.run(
                [openssl_path, 'x509', '-in', str(cert_path), '-noout', '-fingerprint', '-sha256'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                # Output format: "SHA256 Fingerprint=XX:XX:XX..."
                fp_line = result.stdout.strip()
                if '=' in fp_line:
                    fp = fp_line.split('=', 1)[1].replace(':', '').lower()
                    return fp
        except Exception as e:
            log_debug("TLS", f"openssl fingerprint failed: {e}")
    
    # Last resort: hash the DER portion (less accurate but works)
    with open(cert_path, 'rb') as f:
        cert_data = f.read()
    return hashlib.sha256(cert_data).hexdigest()


def get_certificate_fingerprint_from_der(cert_der: bytes) -> str:
    """
    Get SHA256 fingerprint from DER-encoded certificate.
    This is stdlib-only, no external dependencies needed.
    
    Args:
        cert_der: DER-encoded certificate bytes
        
    Returns:
        Hex-encoded SHA256 fingerprint
    """
    fingerprint = hashlib.sha256(cert_der).digest()
    return fingerprint.hex()


# =============================================================================
# Trust-on-First-Use (TOFU) Certificate Store
# =============================================================================

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
