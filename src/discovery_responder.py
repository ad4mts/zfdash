"""
Discovery Responder - Daemon-side network discovery.

Allows ZFS agents to be discovered on the local network via:
1. UDP broadcast (stdlib-only, always available)
2. mDNS/Zeroconf (optional, if zeroconf library installed)

This module has NO external dependencies - zeroconf is optional.
"""

import socket
import json
import threading
from typing import Optional

from constants import DISCOVERY_PORT, DISCOVERY_MAGIC, MDNS_SERVICE_TYPE
from debug_logging import log_debug, log_info, log_error

# Optional mDNS support (zeroconf library)
try:
    from zeroconf import Zeroconf, ServiceInfo
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False


# =============================================================================
# UDP Broadcast Responder (stdlib-only)
# =============================================================================

class UDPDiscoveryResponder(threading.Thread):
    """
    Responds to UDP broadcast discovery queries.
    
    Listens on DISCOVERY_PORT for magic discovery packets and responds
    with agent information (hostname, port, TLS status).
    """
    
    def __init__(self, agent_port: int, tls_enabled: bool, hostname: Optional[str] = None):
        """
        Initialize the UDP discovery responder.
        
        Args:
            agent_port: TCP port the agent is listening on
            tls_enabled: Whether TLS is enabled on the agent
            hostname: Optional hostname override (defaults to socket.gethostname())
        """
        super().__init__(daemon=True, name="udp_discovery")
        self.agent_port = agent_port
        self.tls_enabled = tls_enabled
        self.hostname = hostname or socket.gethostname()
        self._stop_event = threading.Event()
        self._socket: Optional[socket.socket] = None
    
    def run(self):
        """Main responder loop - listens for discovery queries and responds."""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Allow receiving broadcast
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._socket.settimeout(1.0)  # Allow periodic stop check
            self._socket.bind(('', DISCOVERY_PORT))
            
            log_info("DISCOVERY", f"UDP discovery responder listening on port {DISCOVERY_PORT}")
            
            while not self._stop_event.is_set():
                try:
                    data, addr = self._socket.recvfrom(1024)
                    self._handle_query(data, addr)
                except socket.timeout:
                    continue  # Check stop event
                except Exception as e:
                    if not self._stop_event.is_set():
                        log_error("DISCOVERY", f"UDP receive error: {e}")
                        
        except Exception as e:
            log_error("DISCOVERY", f"Failed to start UDP responder: {e}")
        finally:
            if self._socket:
                try:
                    self._socket.close()
                except:
                    pass
    
    def _handle_query(self, data: bytes, addr: tuple):
        """Handle an incoming discovery query."""
        try:
            # Parse query
            query = json.loads(data.decode('utf-8'))
            
            # Check for magic identifier
            if query.get('discover') != DISCOVERY_MAGIC:
                return
            
            log_debug("DISCOVERY", f"Received discovery query from {addr[0]}:{addr[1]}")
            
            # Build response
            response = {
                'service': 'zfdash-agent',
                'hostname': self.hostname,
                'port': self.agent_port,
                'tls': self.tls_enabled
            }
            
            # Send response back to querier
            response_data = json.dumps(response).encode('utf-8')
            self._socket.sendto(response_data, addr)
            
            log_debug("DISCOVERY", f"Sent discovery response to {addr[0]}:{addr[1]}")
            
        except json.JSONDecodeError:
            pass  # Ignore malformed queries
        except Exception as e:
            log_error("DISCOVERY", f"Error handling discovery query: {e}")
    
    def stop(self):
        """Stop the responder thread."""
        self._stop_event.set()
        # Close socket to unblock recvfrom
        if self._socket:
            try:
                self._socket.close()
            except:
                pass


# =============================================================================
# mDNS Advertiser (optional zeroconf dependency)
# =============================================================================

class MDNSAdvertiser:
    """
    Advertises the ZFS agent via mDNS/Zeroconf.
    
    Only functional if the zeroconf library is installed.
    This provides cross-subnet discovery on networks with multicast routing.
    """
    
    def __init__(self):
        self._zeroconf: Optional['Zeroconf'] = None
        self._service_info: Optional['ServiceInfo'] = None
        self._running = False
    
    def start(self, agent_port: int, tls_enabled: bool, hostname: Optional[str] = None):
        """
        Start advertising the agent via mDNS.
        
        Args:
            agent_port: TCP port the agent is listening on
            tls_enabled: Whether TLS is enabled
            hostname: Optional hostname override
        
        Returns:
            True if started successfully, False otherwise
        """
        if not ZEROCONF_AVAILABLE:
            log_debug("DISCOVERY", "mDNS not available (zeroconf not installed)")
            return False
        
        if self._running:
            return True
        
        try:
            hostname = hostname or socket.gethostname()
            
            # Get local IP addresses for registration
            local_ips = self._get_local_ips()
            if not local_ips:
                log_error("DISCOVERY", "Could not determine local IP addresses for mDNS")
                return False
            
            # Create service info
            # Service name format: hostname._zfdash._tcp.local.
            service_name = f"{hostname}.{MDNS_SERVICE_TYPE}"
            
            self._service_info = ServiceInfo(
                type_=MDNS_SERVICE_TYPE,
                name=service_name,
                port=agent_port,
                properties={
                    'tls': 'true' if tls_enabled else 'false',
                    'hostname': hostname
                },
                addresses=[socket.inet_aton(ip) for ip in local_ips]
            )
            
            self._zeroconf = Zeroconf()
            self._zeroconf.register_service(self._service_info)
            self._running = True
            
            log_info("DISCOVERY", f"mDNS advertising started: {service_name}")
            return True
            
        except Exception as e:
            log_error("DISCOVERY", f"Failed to start mDNS advertiser: {e}")
            self.stop()
            return False
    
    def stop(self):
        """Stop mDNS advertising."""
        if self._zeroconf and self._service_info:
            try:
                self._zeroconf.unregister_service(self._service_info)
            except:
                pass
        
        if self._zeroconf:
            try:
                self._zeroconf.close()
            except:
                pass
        
        self._zeroconf = None
        self._service_info = None
        self._running = False
    
    def _get_local_ips(self) -> list:
        """Get list of local IP addresses (excluding loopback)."""
        ips = []
        try:
            # Get all network interfaces
            hostname = socket.gethostname()
            # Try to get all IPs associated with hostname
            try:
                for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                    ip = info[4][0]
                    if not ip.startswith('127.'):
                        ips.append(ip)
            except:
                pass
            
            # Fallback: connect to external address to get default route IP
            if not ips:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect(('8.8.8.8', 80))
                    ips.append(s.getsockname()[0])
        except:
            pass
        
        return list(set(ips))  # Deduplicate


# =============================================================================
# Combined Discovery Manager
# =============================================================================

class DiscoveryResponder:
    """
    Combined discovery responder that manages both UDP and mDNS.
    
    Usage:
        responder = DiscoveryResponder(agent_port=5555, tls_enabled=True)
        responder.start()
        # ... agent runs ...
        responder.stop()
    """
    
    def __init__(self, agent_port: int, tls_enabled: bool, hostname: Optional[str] = None):
        self.agent_port = agent_port
        self.tls_enabled = tls_enabled
        self.hostname = hostname or socket.gethostname()
        
        self._udp_responder: Optional[UDPDiscoveryResponder] = None
        self._mdns_advertiser: Optional[MDNSAdvertiser] = None
    
    def start(self):
        """Start all discovery services."""
        # Always start UDP responder (stdlib-only)
        self._udp_responder = UDPDiscoveryResponder(
            agent_port=self.agent_port,
            tls_enabled=self.tls_enabled,
            hostname=self.hostname
        )
        self._udp_responder.start()
        
        # Try to start mDNS advertiser (optional)
        if ZEROCONF_AVAILABLE:
            self._mdns_advertiser = MDNSAdvertiser()
            if self._mdns_advertiser.start(self.agent_port, self.tls_enabled, self.hostname):
                log_info("DISCOVERY", "mDNS advertising enabled (cross-subnet discovery available)")
            else:
                self._mdns_advertiser = None
        else:
            log_debug("DISCOVERY", "mDNS not available - install 'zeroconf' for cross-subnet discovery")
    
    def stop(self):
        """Stop all discovery services."""
        if self._udp_responder:
            self._udp_responder.stop()
            self._udp_responder = None
        
        if self._mdns_advertiser:
            self._mdns_advertiser.stop()
            self._mdns_advertiser = None


def start_discovery_responder(agent_port: int, tls_enabled: bool, 
                              hostname: Optional[str] = None) -> DiscoveryResponder:
    """
    Convenience function to start the discovery responder.
    
    Args:
        agent_port: TCP port the agent is listening on
        tls_enabled: Whether TLS is enabled on the agent
        hostname: Optional hostname override
        
    Returns:
        DiscoveryResponder instance (call .stop() to shut down)
    """
    responder = DiscoveryResponder(agent_port, tls_enabled, hostname)
    responder.start()
    return responder
