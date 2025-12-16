"""
IPC Security Layer - Modular TLS and Authentication Wrappers

This module provides composable security wrappers for any DaemonTransport:
- SecureTransport: TLS encryption wrapper
- AuthenticatedTransport: Challenge-response authentication wrapper
- TLS negotiation protocol (plaintext hello handshake before upgrade)

Usage:
    # Client-side with TLS + Auth
    transport = SocketTransport(sock)
    tls_active, transport = negotiate_tls_client(transport, tls_supported=True)
    transport = AuthenticatedTransport.client_authenticate(transport, password)
    
    # Server-side with TLS + Auth  
    transport = SocketTransport(client_socket)
    tls_active, transport = negotiate_tls_server(transport, tls_enabled=True, ssl_context)
    transport = AuthenticatedTransport.server_authenticate(transport, password_info)
"""

import ssl
import json
import socket
from typing import Optional, Tuple
from abc import ABC

# Import base transport class
from ipc_client import DaemonTransport

# Import auth protocol functions
from ipc_tcp_auth import (
    _generate_auth_challenge,
    _compute_auth_response,
    _verify_auth_response,
    AuthError
)

# Import constants
from constants import (
    TCP_PROTOCOL_VERSION,
    HELLO_TIMEOUT_SECONDS,
    TLS_ERROR_REQUIRED,
    TLS_ERROR_UNAVAILABLE,
    TLS_ERROR_PROTOCOL_MISMATCH,
    AUTH_TIMEOUT_SECONDS
)

# Debug logging
from debug_logging import log_debug, log_info, log_error


# =============================================================================
# Exceptions
# =============================================================================

class TlsNegotiationError(Exception):
    """Raised when TLS negotiation fails with a structured error code."""
    
    def __init__(self, message: str, code: str):
        """
        Args:
            message: Human-readable error message
            code: Structured error code (TLS_REQUIRED, TLS_UNAVAILABLE, etc.)
        """
        super().__init__(message)
        self.code = code


# =============================================================================
# Hello Protocol Messages
# =============================================================================

def create_client_hello(tls_supported: bool) -> dict:
    """Create client hello message for TLS negotiation."""
    return {
        "type": "hello",
        "protocol_version": TCP_PROTOCOL_VERSION,
        "client_tls_supported": tls_supported
    }


def create_server_hello_ack(tls_enabled: bool, upgrade_tls: bool) -> dict:
    """Create server hello acknowledgment."""
    return {
        "type": "hello_ack",
        "protocol_version": TCP_PROTOCOL_VERSION,
        "server_tls_enabled": tls_enabled,
        "upgrade_tls": upgrade_tls
    }


def create_hello_error(code: str, message: str) -> dict:
    """Create hello error response."""
    return {
        "type": "hello_error",
        "code": code,
        "message": message
    }


def _negotiate_tls_decision(client_tls_supported: bool, server_tls_enabled: bool) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Determine TLS upgrade decision based on client/server capabilities.
    
    Server controls security policy: if TLS is enabled on server, it's required.
    
    Args:
        client_tls_supported: Does client support/want TLS?
        server_tls_enabled: Is TLS enabled on server?
        
    Returns:
        Tuple of (upgrade_tls, error_code, error_message)
        - If upgrade_tls is True, TLS upgrade should happen
        - If error_code is not None, negotiation failed
    """
    if server_tls_enabled and not client_tls_supported:
        # Server requires TLS but client doesn't support it
        return False, TLS_ERROR_REQUIRED, "Server requires TLS encryption. Enable TLS for this agent."
    
    if client_tls_supported and not server_tls_enabled:
        # Client wants TLS but server doesn't have it
        return False, TLS_ERROR_UNAVAILABLE, "Server does not support TLS. Disable TLS for this agent."
    
    if client_tls_supported and server_tls_enabled:
        # Both support TLS - upgrade
        return True, None, None
    
    # Neither wants TLS - plaintext OK
    return False, None, None


# =============================================================================
# SecureTransport - TLS Wrapper
# =============================================================================

class SecureTransport(DaemonTransport):
    """
    Wraps a socket-based DaemonTransport with TLS encryption.
    
    This is a wrapper that upgrades an existing plaintext connection to TLS.
    The underlying transport must have a socket (works with SocketTransport).
    """
    
    def __init__(self, ssl_socket: ssl.SSLSocket, original_type: str = "socket"):
        """
        Initialize with an already-wrapped SSL socket.
        
        Use SecureTransport.wrap_client() or wrap_server() class methods instead.
        """
        self.ssl_socket = ssl_socket
        self._original_type = original_type
    
    @classmethod
    def wrap_client(cls, sock: socket.socket, ssl_context: ssl.SSLContext, 
                    server_hostname: str) -> 'SecureTransport':
        """
        Wrap a client socket with TLS.
        
        Args:
            sock: Plain socket to wrap
            ssl_context: SSL context for TLS
            server_hostname: Server hostname for SNI
            
        Returns:
            SecureTransport wrapping the TLS connection
        """
        ssl_socket = ssl_context.wrap_socket(sock, server_hostname=server_hostname)
        log_debug("SECURITY", "TLS client wrap completed")
        return cls(ssl_socket, "tcp")
    
    @classmethod
    def wrap_server(cls, sock: socket.socket, ssl_context: ssl.SSLContext) -> 'SecureTransport':
        """
        Wrap a server socket with TLS.
        
        Args:
            sock: Client socket to wrap (from accept())
            ssl_context: SSL context with server certificate
            
        Returns:
            SecureTransport wrapping the TLS connection
        """
        ssl_socket = ssl_context.wrap_socket(sock, server_side=True)
        log_debug("SECURITY", "TLS server wrap completed")
        return cls(ssl_socket, "tcp")
    
    def send(self, data: bytes) -> None:
        """Send data through TLS socket."""
        self.ssl_socket.sendall(data)
    
    def receive(self, size: int = 4096) -> bytes:
        """Receive data from TLS socket."""
        return self.ssl_socket.recv(size)
    
    def fileno(self) -> int:
        """Return socket FD for select."""
        return self.ssl_socket.fileno()
    
    def close(self) -> None:
        """Close TLS socket."""
        try:
            self.ssl_socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.ssl_socket.close()
        except Exception:
            pass
    
    def get_type(self) -> str:
        return f"tls+{self._original_type}"
    
    def get_ssl_socket(self) -> ssl.SSLSocket:
        """Get underlying SSL socket for certificate operations."""
        return self.ssl_socket


# =============================================================================
# Socket-based Transport Helper
# =============================================================================

class RawSocketTransport(DaemonTransport):
    """
    Minimal socket transport for use during negotiation.
    
    This wraps a raw socket without any line buffering, for use
    during the hello handshake phase before security is established.
    """
    
    def __init__(self, sock: socket.socket):
        self.socket = sock
        self._buffer = b""
    
    def send(self, data: bytes) -> None:
        self.socket.sendall(data)
    
    def receive(self, size: int = 4096) -> bytes:
        return self.socket.recv(size)
    
    def fileno(self) -> int:
        return self.socket.fileno()
    
    def close(self) -> None:
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.socket.close()
        except Exception:
            pass
    
    def get_type(self) -> str:
        return "raw_socket"
    
    def get_socket(self) -> socket.socket:
        """Get underlying socket."""
        return self.socket
    
    def send_json(self, obj: dict) -> None:
        """Send JSON object with newline."""
        data = json.dumps(obj).encode('utf-8') + b'\n'
        self.send(data)
    
    def receive_json(self, timeout: float = None) -> dict:
        """Receive one JSON line."""
        if timeout is not None:
            old_timeout = self.socket.gettimeout()
            self.socket.settimeout(timeout)
        
        try:
            # Read until newline
            while b'\n' not in self._buffer:
                chunk = self.socket.recv(4096)
                if not chunk:
                    raise ConnectionError("Connection closed during JSON receive")
                self._buffer += chunk
            
            line, self._buffer = self._buffer.split(b'\n', 1)
            return json.loads(line.decode('utf-8'))
        finally:
            if timeout is not None:
                self.socket.settimeout(old_timeout)


# =============================================================================
# TLS Negotiation Functions
# =============================================================================

def negotiate_tls_client(sock: socket.socket, tls_supported: bool, 
                         host: str) -> Tuple[bool, socket.socket]:
    """
    Client-side TLS negotiation.
    
    Sends hello, receives server response, upgrades to TLS if agreed.
    
    Args:
        sock: Connected plaintext socket
        tls_supported: Whether client supports/wants TLS
        host: Server hostname (for TLS SNI)
        
    Returns:
        Tuple of (tls_active, socket)
        - tls_active: True if TLS was established
        - socket: Original socket or wrapped SSL socket
        
    Raises:
        TlsNegotiationError: If negotiation fails
    """
    raw = RawSocketTransport(sock)
    
    try:
        # Send client hello
        hello = create_client_hello(tls_supported)
        log_debug("SECURITY", f"Sending client hello: tls_supported={tls_supported}")
        raw.send_json(hello)
        
        # Receive server response
        response = raw.receive_json(timeout=HELLO_TIMEOUT_SECONDS)
        log_debug("SECURITY", f"Received server response: {response.get('type')}")
        
        if response.get("type") == "hello_error":
            code = response.get("code", "UNKNOWN")
            message = response.get("message", "TLS negotiation failed")
            raise TlsNegotiationError(message, code)
        
        if response.get("type") != "hello_ack":
            raise TlsNegotiationError(
                f"Unexpected response type: {response.get('type')}",
                TLS_ERROR_PROTOCOL_MISMATCH
            )
        
        upgrade_tls = response.get("upgrade_tls", False)
        
        if upgrade_tls:
            # Upgrade to TLS
            log_debug("SECURITY", "Upgrading to TLS...")
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE  # We do TOFU separately
            
            ssl_socket = ssl_context.wrap_socket(sock, server_hostname=host)
            log_debug("SECURITY", "TLS upgrade complete")
            return True, ssl_socket
        else:
            log_debug("SECURITY", "Proceeding without TLS")
            return False, sock
            
    except TlsNegotiationError:
        raise
    except json.JSONDecodeError as e:
        raise TlsNegotiationError(f"Invalid server response: {e}", TLS_ERROR_PROTOCOL_MISMATCH)
    except socket.timeout:
        raise TlsNegotiationError("Server did not respond to hello", TLS_ERROR_PROTOCOL_MISMATCH)
    except Exception as e:
        raise TlsNegotiationError(f"Negotiation failed: {e}", TLS_ERROR_PROTOCOL_MISMATCH)


def negotiate_tls_server(sock: socket.socket, tls_enabled: bool,
                         ssl_context: Optional[ssl.SSLContext]) -> Tuple[bool, socket.socket]:
    """
    Server-side TLS negotiation.
    
    Receives client hello, sends response, upgrades to TLS if agreed.
    
    Args:
        sock: Connected client socket (plaintext)
        tls_enabled: Whether server has TLS enabled
        ssl_context: SSL context with server certificate (required if tls_enabled)
        
    Returns:
        Tuple of (tls_active, socket)
        - tls_active: True if TLS was established  
        - socket: Original socket or wrapped SSL socket
        
    Raises:
        TlsNegotiationError: If negotiation fails (not sent to client - they get hello_error)
    """
    raw = RawSocketTransport(sock)
    
    try:
        # Receive client hello
        sock.settimeout(HELLO_TIMEOUT_SECONDS)
        hello = raw.receive_json(timeout=HELLO_TIMEOUT_SECONDS)
        log_debug("SECURITY", f"Received client hello: {hello}")
        
        if hello.get("type") != "hello":
            # Not a valid hello - could be legacy client or garbage
            error = create_hello_error(TLS_ERROR_PROTOCOL_MISMATCH, "Invalid hello message")
            raw.send_json(error)
            raise TlsNegotiationError("Invalid hello from client", TLS_ERROR_PROTOCOL_MISMATCH)
        
        client_tls_supported = hello.get("client_tls_supported", False)
        
        # Make TLS decision
        upgrade_tls, error_code, error_message = _negotiate_tls_decision(
            client_tls_supported, tls_enabled
        )
        
        if error_code:
            # Send error response
            error = create_hello_error(error_code, error_message)
            raw.send_json(error)
            raise TlsNegotiationError(error_message, error_code)
        
        # Send hello_ack
        ack = create_server_hello_ack(tls_enabled, upgrade_tls)
        raw.send_json(ack)
        log_debug("SECURITY", f"Sent hello_ack: upgrade_tls={upgrade_tls}")
        
        if upgrade_tls:
            # Upgrade to TLS
            log_debug("SECURITY", "Upgrading to TLS (server)...")
            if ssl_context is None:
                raise RuntimeError("TLS enabled but no SSL context provided")
            
            ssl_socket = ssl_context.wrap_socket(sock, server_side=True)
            log_debug("SECURITY", "TLS upgrade complete (server)")
            return True, ssl_socket
        else:
            log_debug("SECURITY", "Proceeding without TLS (server)")
            return False, sock
            
    except TlsNegotiationError:
        raise
    except json.JSONDecodeError:
        try:
            error = create_hello_error(TLS_ERROR_PROTOCOL_MISMATCH, "Invalid JSON")
            raw.send_json(error)
        except Exception:
            pass
        raise TlsNegotiationError("Invalid JSON from client", TLS_ERROR_PROTOCOL_MISMATCH)
    except socket.timeout:
        raise TlsNegotiationError("Client hello timeout", TLS_ERROR_PROTOCOL_MISMATCH)
    except Exception as e:
        raise TlsNegotiationError(f"Negotiation failed: {e}", TLS_ERROR_PROTOCOL_MISMATCH)


# =============================================================================
# Authentication Functions
# =============================================================================

def authenticate_client(sock: socket.socket, password: str) -> None:
    """
    Client-side authentication over an already-connected socket.
    
    Receives challenge from server, computes response, receives result.
    
    Args:
        sock: Connected socket (may be SSL socket)
        password: Password to authenticate with
        
    Raises:
        AuthError: If authentication fails
    """
    raw = RawSocketTransport(sock)
    
    try:
        # Receive challenge
        sock.settimeout(AUTH_TIMEOUT_SECONDS)
        challenge = raw.receive_json(timeout=AUTH_TIMEOUT_SECONDS)
        
        if challenge.get("type") != "auth_challenge":
            raise AuthError(f"Unexpected message type: {challenge.get('type')}")
        
        # Extract challenge parameters
        salt_hex = challenge.get("salt", "")
        iterations = challenge.get("iterations", 600000)
        nonce = challenge.get("nonce", "")
        
        if not salt_hex or not nonce:
            raise AuthError("Invalid challenge: missing salt or nonce")
        
        # Compute response
        response_hmac = _compute_auth_response(password, salt_hex, iterations, nonce)
        
        # Send response
        response = {"type": "auth_response", "hmac": response_hmac}
        raw.send_json(response)
        
        # Receive result
        result = raw.receive_json(timeout=AUTH_TIMEOUT_SECONDS)
        
        if result.get("type") != "auth_result":
            raise AuthError(f"Unexpected result type: {result.get('type')}")
        
        if not result.get("success"):
            error_msg = result.get("error", "Authentication failed")
            raise AuthError(error_msg)
        
        log_debug("SECURITY", "Client authentication successful")
        
    except AuthError:
        raise
    except Exception as e:
        raise AuthError(f"Authentication error: {e}")
    finally:
        sock.settimeout(None)  # Clear timeout for normal operation


def authenticate_server(sock: socket.socket, password_info: dict) -> bool:
    """
    Server-side authentication over an already-connected socket.
    
    Sends challenge to client, receives response, verifies.
    
    Args:
        sock: Connected client socket (may be SSL socket)
        password_info: Password info dict from credentials (with hash, salt, iterations)
        
    Returns:
        True if authentication succeeded
        
    Raises:
        AuthError: If authentication fails
    """
    raw = RawSocketTransport(sock)
    
    try:
        sock.settimeout(AUTH_TIMEOUT_SECONDS)
        
        # Generate and send challenge
        challenge, expected_hmac = _generate_auth_challenge(password_info)
        raw.send_json(challenge)
        
        # Receive response
        response = raw.receive_json(timeout=AUTH_TIMEOUT_SECONDS)
        
        if response.get("type") != "auth_response":
            log_info("SECURITY", f"Invalid auth response type: {response.get('type')}")
            result = {"type": "auth_result", "success": False, "error": "Invalid response"}
            raw.send_json(result)
            return False
        
        # Verify HMAC
        client_hmac_hex = response.get("hmac", "")
        if _verify_auth_response(client_hmac_hex, expected_hmac):
            result = {"type": "auth_result", "success": True}
            raw.send_json(result)
            log_debug("SECURITY", "Server authentication successful")
            return True
        else:
            result = {"type": "auth_result", "success": False, "error": "Invalid credentials"}
            raw.send_json(result)
            log_error("SECURITY", "Server authentication failed: invalid HMAC")
            return False
            
    except Exception as e:
        log_error("SECURITY", f"Server auth error: {e}")
        try:
            result = {"type": "auth_result", "success": False, "error": str(e)}
            raw.send_json(result)
        except Exception:
            pass
        return False
    finally:
        sock.settimeout(None)
