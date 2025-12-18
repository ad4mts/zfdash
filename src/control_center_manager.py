"""
Control Center Manager - Manages remote ZFS agent connections.

This module provides the ControlCenterManager class that handles:
- Multiple remote agent connections via TCP
- Connection lifecycle (add, remove, connect, disconnect)
- Persistent storage of connection metadata
- Session-based authentication caching
"""

import json
import os
import sys
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

# Import TCP client transport
from ipc_tcp_client import connect_to_agent, TlsNegotiationError
from ipc_tcp_auth import AuthError
from zfs_manager import ZfsManagerClient

# TLS certificate trust management
from tls_manager import remove_trusted_certificate
from paths import USER_CONFIG_DIR
from pathlib import Path

# Debug logging for verbose messages
from debug_logging import log_debug, log_info, log_error, log_warning, log_critical


class AgentConnection:
    """Represents a remote ZFS agent connection."""
    
    def __init__(self, alias: str, host: str, port: int, use_tls: bool = True):
        """
        Initialize an agent connection.
        
        Args:
            alias: Human-readable name for this connection
            host: Remote host IP or hostname
            port: Remote TCP port
            use_tls: Whether to use TLS encryption (default: True)
        """
        self.alias = alias
        self.host = host
        self.port = port
        self.use_tls = use_tls  # User preference for TLS
        self.client: Optional[ZfsManagerClient] = None
        self.connected = False
        self.tls_active = False  # True only if TLS handshake succeeded
        self.last_error: Optional[str] = None
        self.last_connected: Optional[str] = None
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert connection to dictionary for storage."""
        return {
            'alias': self.alias,
            'host': self.host,
            'port': self.port,
            'use_tls': self.use_tls,
            'last_connected': self.last_connected
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentConnection':
        """Create connection from stored dictionary."""
        conn = cls(
            alias=data['alias'],
            host=data['host'],
            port=data['port'],
            use_tls=data.get('use_tls', True)  # Default True for backward compatibility
        )
        conn.last_connected = data.get('last_connected')
        return conn


class ControlCenterManager:
    """Manages multiple remote ZFS agent connections."""
    
    def __init__(self, storage_path: str):
        """
        Initialize the control center manager.
        
        Args:
            storage_path: Path to JSON file for storing connection metadata
        """
        self.connections: Dict[str, AgentConnection] = {}
        self.storage_path = storage_path
        self.active_alias: Optional[str] = None  # Currently active remote alias
        
    def add_connection(self, alias: str, host: str, port: int, use_tls: bool = True) -> Tuple[bool, str]:
        """
        Add a new agent connection.
        
        Args:
            alias: Unique alias for this connection
            host: Remote host
            port: Remote port
            use_tls: Whether to use TLS encryption (default: True)
            
        Returns:
            Tuple of (success, message)
        """
        if alias in self.connections:
            return False, f"Connection with alias '{alias}' already exists"
        
        if not alias or not alias.strip():
            return False, "Alias cannot be empty"
        
        if not host or not host.strip():
            return False, "Host cannot be empty"
        
        if not isinstance(port, int) or port < 1 or port > 65535:
            return False, f"Invalid port number: {port}"
        
        try:
            self.connections[alias] = AgentConnection(alias, host, port, use_tls)
            self.save_connections()
            return True, f"Agent '{alias}' added successfully"
        except Exception as e:
            return False, f"Failed to add connection: {e}"
    
    def remove_connection(self, alias: str) -> Tuple[bool, str]:
        """
        Remove an agent connection.
        
        Args:
            alias: Alias of connection to remove
            
        Returns:
            Tuple of (success, message)
        """
        if alias not in self.connections:
            return False, f"Connection '{alias}' not found"
        
        conn = self.connections[alias]
        
        # Disconnect if currently connected
        if conn.connected and conn.client:
            try:
                conn.client.close()
            except Exception as e:
                print(f"CC_MANAGER: Error closing connection during removal: {e}", file=sys.stderr)
        
        # Clear trusted certificate for this host:port (allows re-adding after cert change)
        try:
            if remove_trusted_certificate(Path(USER_CONFIG_DIR), conn.host, conn.port):
                log_debug("CC_MANAGER", f"Cleared trusted certificate for {conn.host}:{conn.port}")
        except Exception as e:
            log_debug("CC_MANAGER", f"Could not clear trusted certificate: {e}")
        
        # Clear active connection if this was it
        if self.active_alias == alias:
            self.active_alias = None
        
        del self.connections[alias]
        self.save_connections()
        return True, f"Agent '{alias}' removed successfully"
    
    def connect_to_agent(self, alias: str, password: str, session: Dict) -> Tuple[bool, str, str]:
        """
        Connect to a remote agent using saved TLS setting.
        
        Args:
            alias: Alias of agent to connect to
            password: Admin password for authentication
            session: Flask session dict for caching auth
            
        Returns:
            Tuple of (success, message, tls_error_code)
            - tls_error_code is None on success, or structured code on TLS failure
        """
        if alias not in self.connections:
            return False, f"Connection '{alias}' not found", None
        
        conn = self.connections[alias]
        
        # Disconnect existing connection if any
        if conn.connected and conn.client:
            try:
                conn.client.close()
            except Exception:
                pass
            conn.client = None
            conn.connected = False
        
        # Use saved TLS preference
        use_tls = conn.use_tls
        
        try:
            # Connect using TCP client transport
            log_debug("CC_MANAGER", f"Connecting to {conn.host}:{conn.port} (TLS: {use_tls})...")
            transport, tls_active = connect_to_agent(conn.host, conn.port, password, timeout=30.0, use_tls=use_tls)
            
            # Create ZfsManagerClient with the transport
            # owns_daemon=False because this is an external agent
            conn.client = ZfsManagerClient(
                daemon_process=None,
                transport=transport,
                owns_daemon=False
            )
            
            conn.connected = True
            conn.tls_active = tls_active
            conn.last_error = None
            conn.last_connected = datetime.now().isoformat()
            
            # Cache connection info in session (but not password)
            session[f'cc_connected_{alias}'] = True
            
            self.save_connections()
            
            # Return success with appropriate message
            if tls_active:
                return True, f"Connected to '{alias}' (TLS encrypted)", None
            else:
                return True, f"⚠️ Connected to '{alias}' WITHOUT encryption", None
            
        except TlsNegotiationError as e:
            # Structured TLS error - include error code for frontend
            conn.last_error = str(e)
            conn.connected = False
            conn.tls_active = False
            log_error("CC_MANAGER", f"TLS negotiation failed: {e} (code: {e.code})")
            return False, str(e), e.code
            
        except AuthError as e:
            conn.last_error = str(e)
            conn.connected = False
            conn.tls_active = False
            log_error("CC_MANAGER", f"Authentication failed: {e}")
            return False, str(e), None
            
        except Exception as e:
            error_msg = str(e)
            conn.last_error = error_msg
            conn.connected = False
            conn.tls_active = False
            log_error("CC_MANAGER", f"Connection failed: {error_msg}")
            return False, error_msg, None
    
    def disconnect_from_agent(self, alias: str) -> Tuple[bool, str]:
        """
        Disconnect from a remote agent.
        
        Args:
            alias: Alias of agent to disconnect from
            
        Returns:
            Tuple of (success, message)
        """
        if alias not in self.connections:
            return False, f"Connection '{alias}' not found"
        
        conn = self.connections[alias]
        
        if not conn.connected:
            return False, f"Agent '{alias}' is not connected"
        
        try:
            if conn.client:
                conn.client.close()
            conn.client = None
            conn.connected = False
            
            # Clear active if this was it
            if self.active_alias == alias:
                self.active_alias = None
            
            return True, f"Disconnected from '{alias}'"
        except Exception as e:
            return False, f"Error disconnecting: {e}"
    
    def switch_active(self, alias: str, session: Dict) -> Tuple[bool, str]:
        """
        Switch the active agent connection.
        
        Args:
            alias: Alias of agent to make active (or 'local' for local daemon)
            session: Flask session dict
            
        Returns:
            Tuple of (success, message)
        """
        if alias == 'local':
            self.active_alias = None
            session['cc_mode'] = 'local'
            return True, "Switched to local daemon"
        
        if alias not in self.connections:
            return False, f"Connection '{alias}' not found"
        
        conn = self.connections[alias]
        
        if not conn.connected:
            return False, f"Agent '{alias}' is not connected. Please connect first."
        
        self.active_alias = alias
        session['cc_mode'] = 'remote'
        session['cc_active_alias'] = alias
        
        return True, f"Switched to remote agent '{alias}'"
    
    def is_healthy_or_clear(self) -> Tuple[bool, Optional[str]]:
        """
        Get active agent status, clearing stale state if connection died.
        
        This is the SINGLE SOURCE OF TRUTH for connection state.
        If the active agent's TCP connection is dead, clears the state.
        
        Returns:
            Tuple of (is_healthy, active_alias or None)
        """
        if not self.active_alias:
            return False, None
        
        if self.active_alias not in self.connections:
            # Orphaned active_alias reference
            self.active_alias = None
            return False, None
        
        conn = self.connections[self.active_alias]
        
        if not conn.connected or not conn.client:
            # Not connected
            self.active_alias = None
            return False, None
        
        # Check actual TCP connection health
        try:
            if conn.client.is_connection_healthy():
                return True, self.active_alias
        except Exception as e:
            log_debug("CC_MANAGER", f"Health check exception for '{self.active_alias}': {e}")
        
        # Connection is unhealthy - clear state
        log_info("CC_MANAGER", f"Clearing stale connection for '{self.active_alias}' (TCP unhealthy)")
        alias = self.active_alias
        conn.connected = False
        conn.client = None
        conn.last_error = "Connection lost"
        self.active_alias = None
        
        return False, None
    
    def get_active_client(self) -> Optional[ZfsManagerClient]:
        """
        Get the currently active ZfsManagerClient.
        
        Returns:
            ZfsManagerClient instance or None if no remote agent is active
        """
        if self.active_alias and self.active_alias in self.connections:
            conn = self.connections[self.active_alias]
            if conn.connected and conn.client:
                return conn.client
        return None
    
    def list_connections(self) -> List[Dict[str, Any]]:
        """
        Get list of all connections with their status.
        
        Validates TCP health of each connected agent (not just active one).
        
        Returns:
            List of connection info dictionaries
        """
        result = []
        for alias, conn in self.connections.items():
            # Validate actual TCP health for connected agents
            is_healthy = False
            if conn.connected and conn.client:
                try:
                    is_healthy = conn.client.is_connection_healthy()
                except Exception:
                    is_healthy = False
                
                # Update connection state if dead
                if not is_healthy:
                    log_info("CC_MANAGER", f"Connection '{alias}' found dead during list")
                    conn.connected = False
                    conn.last_error = "Connection lost"
                    # Clear active if this was the active agent
                    if alias == self.active_alias:
                        self.active_alias = None
            
            result.append({
                'alias': alias,
                'host': conn.host,
                'port': conn.port,
                'use_tls': conn.use_tls,
                'connected': conn.connected and is_healthy,  # Use live health check
                'tls_active': conn.tls_active,
                'active': alias == self.active_alias,
                'last_connected': conn.last_connected,
                'last_error': conn.last_error
            })
        return result
    
    def update_tls(self, alias: str, use_tls: bool) -> Tuple[bool, str]:
        """
        Update TLS preference for an agent.
        
        Args:
            alias: Alias of connection to update
            use_tls: New TLS preference
            
        Returns:
            Tuple of (success, message)
        """
        if alias not in self.connections:
            return False, f"Connection '{alias}' not found"
        
        conn = self.connections[alias]
        conn.use_tls = use_tls
        self.save_connections()
        
        tls_status = "enabled" if use_tls else "disabled"
        return True, f"TLS {tls_status} for '{alias}'"
    
    def check_health(self, alias: str) -> Tuple[bool, str]:
        """
        Check if an agent connection is healthy.
        
        Args:
            alias: Alias of connection to check
            
        Returns:
            Tuple of (healthy, message)
        """
        if alias not in self.connections:
            return False, f"Connection '{alias}' not found"
        
        conn = self.connections[alias]
        
        if not conn.connected or not conn.client:
            return False, "Not connected"
        
        try:
            # Use the ZfsManagerClient's health check
            if conn.client.is_connection_healthy():
                return True, "Connection healthy"
            else:
                error = conn.client.get_connection_error()
                return False, error or "Connection unhealthy"
        except Exception as e:
            return False, f"Health check error: {e}"
    
    def save_connections(self) -> None:
        """Save connection metadata to storage file."""
        try:
            # Ensure directory exists
            storage_dir = os.path.dirname(self.storage_path)
            if storage_dir:
                os.makedirs(storage_dir, exist_ok=True)
            
            data = {
                'connections': [conn.to_dict() for conn in self.connections.values()]
            }
            
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            log_debug("CC_MANAGER", f"Saved {len(self.connections)} connections to {self.storage_path}")
        except Exception as e:
            print(f"CC_MANAGER: Error saving connections: {e}", file=sys.stderr)
    
    def load_connections(self) -> None:
        """Load connection metadata from storage file."""
        if not os.path.exists(self.storage_path):
            log_debug("CC_MANAGER", f"No saved connections found at {self.storage_path}")
            return
        
        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
            
            connections_data = data.get('connections', [])
            for conn_dict in connections_data:
                conn = AgentConnection.from_dict(conn_dict)
                self.connections[conn.alias] = conn
            
            log_debug("CC_MANAGER", f"Loaded {len(self.connections)} connections from {self.storage_path}")
        except Exception as e:
            print(f"CC_MANAGER: Error loading connections: {e}", file=sys.stderr)
