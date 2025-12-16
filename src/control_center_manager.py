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
from ipc_tcp_client import connect_to_agent
from zfs_manager import ZfsManagerClient


class AgentConnection:
    """Represents a remote ZFS agent connection."""
    
    def __init__(self, alias: str, host: str, port: int):
        """
        Initialize an agent connection.
        
        Args:
            alias: Human-readable name for this connection
            host: Remote host IP or hostname
            port: Remote TCP port
        """
        self.alias = alias
        self.host = host
        self.port = port
        self.client: Optional[ZfsManagerClient] = None
        self.connected = False
        self.last_error: Optional[str] = None
        self.last_connected: Optional[str] = None
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert connection to dictionary for storage."""
        return {
            'alias': self.alias,
            'host': self.host,
            'port': self.port,
            'last_connected': self.last_connected
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentConnection':
        """Create connection from stored dictionary."""
        conn = cls(
            alias=data['alias'],
            host=data['host'],
            port=data['port']
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
        self.active_connection: Optional[str] = None  # Active agent alias
        
    def add_connection(self, alias: str, host: str, port: int) -> Tuple[bool, str]:
        """
        Add a new agent connection.
        
        Args:
            alias: Unique alias for this connection
            host: Remote host
            port: Remote port
            
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
            self.connections[alias] = AgentConnection(alias, host, port)
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
        
        # Clear active connection if this was it
        if self.active_connection == alias:
            self.active_connection = None
        
        del self.connections[alias]
        self.save_connections()
        return True, f"Agent '{alias}' removed successfully"
    
    def connect_to_agent(self, alias: str, password: str, session: Dict) -> Tuple[bool, str]:
        """
        Connect to a remote agent.
        
        Args:
            alias: Alias of agent to connect to
            password: Admin password for authentication
            session: Flask session dict for caching auth
            
        Returns:
            Tuple of (success, message)
        """
        if alias not in self.connections:
            return False, f"Connection '{alias}' not found"
        
        conn = self.connections[alias]
        
        # Disconnect existing connection if any
        if conn.connected and conn.client:
            try:
                conn.client.close()
            except Exception:
                pass
            conn.client = None
            conn.connected = False
        
        try:
            # Connect using TCP client transport
            print(f"CC_MANAGER: Connecting to {conn.host}:{conn.port}...", file=sys.stderr)
            transport = connect_to_agent(conn.host, conn.port, password, timeout=30.0)
            
            # Create ZfsManagerClient with the transport
            # owns_daemon=False because this is an external agent
            conn.client = ZfsManagerClient(
                daemon_process=None,
                transport=transport,
                owns_daemon=False
            )
            
            conn.connected = True
            conn.last_error = None
            conn.last_connected = datetime.now().isoformat()
            
            # Cache connection info in session (but not password)
            session[f'cc_connected_{alias}'] = True
            
            self.save_connections()
            
            return True, f"Successfully connected to '{alias}'"
            
        except Exception as e:
            error_msg = str(e)
            conn.last_error = error_msg
            conn.connected = False
            print(f"CC_MANAGER: Connection failed: {error_msg}", file=sys.stderr)
            return False, f"Failed to connect to '{alias}': {error_msg}"
    
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
            if self.active_connection == alias:
                self.active_connection = None
            
            return True, f"Disconnected from '{alias}'"
        except Exception as e:
            return False, f"Error disconnecting: {e}"
    
    def switch_active_agent(self, alias: str, session: Dict) -> Tuple[bool, str]:
        """
        Switch the active agent connection.
        
        Args:
            alias: Alias of agent to make active (or 'local' for local daemon)
            session: Flask session dict
            
        Returns:
            Tuple of (success, message)
        """
        if alias == 'local':
            self.active_connection = None
            session['cc_mode'] = 'local'
            return True, "Switched to local daemon"
        
        if alias not in self.connections:
            return False, f"Connection '{alias}' not found"
        
        conn = self.connections[alias]
        
        if not conn.connected:
            return False, f"Agent '{alias}' is not connected. Please connect first."
        
        self.active_connection = alias
        session['cc_mode'] = 'remote'
        session['cc_active_alias'] = alias
        
        return True, f"Switched to remote agent '{alias}'"
    
    def get_active_client(self) -> Optional[ZfsManagerClient]:
        """
        Get the currently active ZfsManagerClient.
        
        Returns:
            ZfsManagerClient instance or None if no remote agent is active
        """
        if self.active_connection and self.active_connection in self.connections:
            conn = self.connections[self.active_connection]
            if conn.connected and conn.client:
                return conn.client
        return None
    
    def list_connections(self) -> List[Dict[str, Any]]:
        """
        Get list of all connections with their status.
        
        Returns:
            List of connection info dictionaries
        """
        result = []
        for alias, conn in self.connections.items():
            result.append({
                'alias': alias,
                'host': conn.host,
                'port': conn.port,
                'connected': conn.connected,
                'active': alias == self.active_connection,
                'last_connected': conn.last_connected,
                'last_error': conn.last_error
            })
        return result
    
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
            
            print(f"CC_MANAGER: Saved {len(self.connections)} connections to {self.storage_path}", file=sys.stderr)
        except Exception as e:
            print(f"CC_MANAGER: Error saving connections: {e}", file=sys.stderr)
    
    def load_connections(self) -> None:
        """Load connection metadata from storage file."""
        if not os.path.exists(self.storage_path):
            print(f"CC_MANAGER: No saved connections found at {self.storage_path}", file=sys.stderr)
            return
        
        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
            
            connections_data = data.get('connections', [])
            for conn_dict in connections_data:
                conn = AgentConnection.from_dict(conn_dict)
                self.connections[conn.alias] = conn
            
            print(f"CC_MANAGER: Loaded {len(self.connections)} connections from {self.storage_path}", file=sys.stderr)
        except Exception as e:
            print(f"CC_MANAGER: Error loading connections: {e}", file=sys.stderr)
