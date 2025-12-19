"""
Discovery Scanner - Client-side network discovery.

Discovers ZFS agents on the local network via:
1. UDP broadcast (stdlib-only, always available)
2. mDNS/Zeroconf (optional, if zeroconf library installed)

Results from both methods are merged and deduplicated.
"""

import socket
import json
import time
from typing import List, Dict, Optional

from constants import DISCOVERY_PORT, DISCOVERY_MAGIC, MDNS_SERVICE_TYPE, DISCOVERY_TIMEOUT
from debug_logging import log_debug, log_info, log_error

# Optional mDNS support (zeroconf library)
try:
    from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False


# =============================================================================
# UDP Broadcast Scanner (stdlib-only)
# =============================================================================

def discover_via_udp_broadcast(timeout: float = DISCOVERY_TIMEOUT) -> List[Dict]:
    """
    Discover ZFS agents via UDP broadcast.
    
    Sends a broadcast discovery query and collects responses.
    Works on same subnet/broadcast domain only.
    
    Args:
        timeout: Time to wait for responses (seconds)
        
    Returns:
        List of discovered agents: [{host, port, hostname, tls}, ...]
    """
    agents = []
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)  # Short timeout for individual receives
        
        # Build query
        query = json.dumps({'discover': DISCOVERY_MAGIC}).encode('utf-8')
        
        # Send broadcast
        sock.sendto(query, ('<broadcast>', DISCOVERY_PORT))
        log_debug("DISCOVERY", f"Sent UDP broadcast discovery query to port {DISCOVERY_PORT}")
        
        # Collect responses
        start_time = time.time()
        seen_hosts = set()
        
        while time.time() - start_time < timeout:
            try:
                data, addr = sock.recvfrom(1024)
                host = addr[0]
                
                # Skip duplicates from same host
                if host in seen_hosts:
                    continue
                seen_hosts.add(host)
                
                # Parse response
                try:
                    response = json.loads(data.decode('utf-8'))
                    
                    if response.get('service') == 'zfdash-agent':
                        agent = {
                            'host': host,
                            'port': response.get('port', 5555),
                            'hostname': response.get('hostname', host),
                            'tls': response.get('tls', False),
                            'source': 'udp'
                        }
                        agents.append(agent)
                        log_debug("DISCOVERY", f"Found agent via UDP: {agent['hostname']} at {host}:{agent['port']}")
                        
                except json.JSONDecodeError:
                    pass
                    
            except socket.timeout:
                continue  # Keep waiting until overall timeout
                
    except Exception as e:
        log_error("DISCOVERY", f"UDP broadcast discovery error: {e}")
    finally:
        try:
            sock.close()
        except:
            pass
    
    return agents


# =============================================================================
# mDNS Scanner (optional zeroconf dependency)
# =============================================================================

def discover_via_mdns(timeout: float = DISCOVERY_TIMEOUT) -> List[Dict]:
    """
    Discover ZFS agents via mDNS/Zeroconf.
    
    Uses multicast DNS for discovery. Can work across subnets
    if the network supports multicast routing.
    
    Args:
        timeout: Time to wait for responses (seconds)
        
    Returns:
        List of discovered agents: [{host, port, hostname, tls}, ...]
    """
    if not ZEROCONF_AVAILABLE:
        log_debug("DISCOVERY", "mDNS not available (zeroconf not installed)")
        return []
    
    agents = []
    
    class ZfdashListener(ServiceListener):
        """Listener for ZfDash mDNS services."""
        
        def add_service(self, zc: Zeroconf, type_: str, name: str):
            info = zc.get_service_info(type_, name)
            if info:
                # Extract IP addresses
                addresses = []
                for addr in info.addresses:
                    try:
                        addresses.append(socket.inet_ntoa(addr))
                    except:
                        pass
                
                if addresses:
                    props = info.properties or {}
                    agent = {
                        'host': addresses[0],  # Use first IP
                        'port': info.port,
                        'hostname': props.get(b'hostname', b'').decode('utf-8') or name.split('.')[0],
                        'tls': props.get(b'tls', b'false').decode('utf-8') == 'true',
                        'source': 'mdns'
                    }
                    agents.append(agent)
                    log_debug("DISCOVERY", f"Found agent via mDNS: {agent['hostname']} at {agent['host']}:{agent['port']}")
        
        def remove_service(self, zc: Zeroconf, type_: str, name: str):
            pass  # Not needed for discovery scan
        
        def update_service(self, zc: Zeroconf, type_: str, name: str):
            pass  # Not needed for discovery scan
    
    try:
        zeroconf = Zeroconf()
        listener = ZfdashListener()
        browser = ServiceBrowser(zeroconf, MDNS_SERVICE_TYPE, listener)
        
        log_debug("DISCOVERY", f"Started mDNS browser for {MDNS_SERVICE_TYPE}")
        
        # Wait for responses
        time.sleep(timeout)
        
        browser.cancel()
        zeroconf.close()
        
    except Exception as e:
        log_error("DISCOVERY", f"mDNS discovery error: {e}")
    
    return agents


# =============================================================================
# Combined Discovery
# =============================================================================

def discover_agents(timeout: float = DISCOVERY_TIMEOUT) -> List[Dict]:
    """
    Discover ZFS agents on the network using all available methods.
    
    Uses mDNS if zeroconf is available, and always uses UDP broadcast.
    Results are merged and deduplicated by host:port.
    
    Args:
        timeout: Time to wait for responses (seconds)
        
    Returns:
        List of discovered agents: [{host, port, hostname, tls, source}, ...]
    """
    all_agents = []
    
    # mDNS discovery (if available)
    if ZEROCONF_AVAILABLE:
        log_debug("DISCOVERY", "Starting mDNS discovery...")
        mdns_agents = discover_via_mdns(timeout)
        all_agents.extend(mdns_agents)
        log_info("DISCOVERY", f"mDNS found {len(mdns_agents)} agent(s)")
    
    # UDP broadcast discovery (always)
    log_debug("DISCOVERY", "Starting UDP broadcast discovery...")
    udp_agents = discover_via_udp_broadcast(timeout)
    all_agents.extend(udp_agents)
    log_info("DISCOVERY", f"UDP broadcast found {len(udp_agents)} agent(s)")
    
    # Deduplicate by host:port (prefer mDNS info as it has more metadata)
    seen = {}
    for agent in all_agents:
        key = f"{agent['host']}:{agent['port']}"
        if key not in seen:
            seen[key] = agent
        elif agent['source'] == 'mdns' and seen[key]['source'] == 'udp':
            # Prefer mDNS info
            seen[key] = agent
    
    result = list(seen.values())
    log_info("DISCOVERY", f"Total unique agents discovered: {len(result)}")
    
    return result


def is_mdns_available() -> bool:
    """Check if mDNS/Zeroconf is available."""
    return ZEROCONF_AVAILABLE
