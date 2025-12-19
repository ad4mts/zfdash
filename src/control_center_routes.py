"""
Control Center Routes - Flask Blueprint for Control Center API

This module provides REST API endpoints for managing remote ZFS agent connections:
- Adding/removing agent connections
- Connecting/disconnecting from agents
- Switching active agents
- Checking connection health
"""

from flask import Blueprint, request, jsonify, session
from typing import Tuple

# Create Blueprint
control_center_bp = Blueprint('control_center', __name__)

# Will be set by web_ui.py when registering blueprint
_cc_manager = None


def init_control_center_routes(cc_manager):
    """
    Initialize the control center routes with a manager instance.
    
    Args:
        cc_manager: ControlCenterManager instance
    """
    global _cc_manager
    _cc_manager = cc_manager


@control_center_bp.route('/add', methods=['POST'])
def add_agent():
    """Add a new remote agent connection."""
    if not _cc_manager:
        return jsonify({'success': False, 'error': 'Control center not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    alias = data.get('alias', '').strip()
    host = data.get('host', '').strip()
    port = data.get('port')
    use_tls = data.get('use_tls', True)  # Default to True if not specified
    
    if not alias:
        return jsonify({'success': False, 'error': 'Alias is required'}), 400
    if not host:
        return jsonify({'success': False, 'error': 'Host is required'}), 400
    
    try:
        port = int(port)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Port must be a number'}), 400
    
    # Convert use_tls to bool if it's a string
    if isinstance(use_tls, str):
        use_tls = use_tls.lower() in ('true', '1', 'yes')
    
    success, message = _cc_manager.add_connection(alias, host, port, use_tls)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@control_center_bp.route('/remove', methods=['POST'])
def remove_agent():
    """Remove a remote agent connection."""
    if not _cc_manager:
        return jsonify({'success': False, 'error': 'Control center not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    alias = data.get('alias', '').strip()
    if not alias:
        return jsonify({'success': False, 'error': 'Alias is required'}), 400
    
    success, message = _cc_manager.remove_connection(alias)
    
    if success:
        # Clear session data for this connection
        session.pop(f'cc_connected_{alias}', None)
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@control_center_bp.route('/connect', methods=['POST'])
def connect_agent():
    """Connect to a remote agent (requires password)."""
    if not _cc_manager:
        return jsonify({'success': False, 'error': 'Control center not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    alias = data.get('alias', '').strip()
    password = data.get('password', '')
    
    if not alias:
        return jsonify({'success': False, 'error': 'Alias is required'}), 400
    if not password:
        return jsonify({'success': False, 'error': 'Password is required'}), 400
    
    # Get agent's configured TLS setting for error response
    agent_use_tls = True  # Default
    if alias in _cc_manager.connections:
        agent_use_tls = _cc_manager.connections[alias].use_tls
    
    success, message, tls_error_code = _cc_manager.connect_to_agent(
        alias, password, session
    )
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        # Include TLS error code for structured error handling in frontend
        return jsonify({
            'success': False, 
            'error': message,
            'tls_error_code': tls_error_code,  # None if not a TLS error
            'agent_tls': agent_use_tls  # Agent's saved TLS preference
        }), 400


@control_center_bp.route('/disconnect', methods=['POST'])
def disconnect_agent():
    """Disconnect from a remote agent."""
    if not _cc_manager:
        return jsonify({'success': False, 'error': 'Control center not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    alias = data.get('alias', '').strip()
    if not alias:
        return jsonify({'success': False, 'error': 'Alias is required'}), 400
    
    success, message = _cc_manager.disconnect_from_agent(alias)
    
    if success:
        # Clear session data
        session.pop(f'cc_connected_{alias}', None)
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@control_center_bp.route('/switch/<alias>', methods=['POST'])
def switch_agent(alias):
    """Switch to a different active agent (or 'local' for local daemon)."""
    if not _cc_manager:
        return jsonify({'success': False, 'error': 'Control center not initialized'}), 500
    
    alias = alias.strip()
    if not alias:
        return jsonify({'success': False, 'error': 'Alias is required'}), 400
    
    success, message = _cc_manager.switch_active(alias, session)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@control_center_bp.route('/list', methods=['GET'])
def list_agents():
    """List all configured remote agents with their status."""
    if not _cc_manager:
        return jsonify({'success': False, 'error': 'Control center not initialized'}), 500
    
    try:
        # Validate active connection (single source of truth - auto-clears dead connections)
        is_healthy, active_alias = _cc_manager.is_healthy_or_clear()
        
        # Clear session if remote died
        if session.get('cc_mode') == 'remote' and not active_alias:
            session.pop('cc_mode', None)
            session.pop('cc_active_alias', None)
        
        connections = _cc_manager.list_connections()
        current_mode = 'remote' if active_alias else 'local'
        
        return jsonify({
            'success': True,
            'connections': connections,
            'current_mode': current_mode,
            'active_alias': active_alias
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@control_center_bp.route('/health/<alias>', methods=['GET'])
def check_agent_health(alias):
    """Check if a specific agent connection is healthy."""
    if not _cc_manager:
        return jsonify({'success': False, 'error': 'Control center not initialized'}), 500
    
    alias = alias.strip()
    if not alias:
        return jsonify({'success': False, 'error': 'Alias is required'}), 400
    
    healthy, message = _cc_manager.check_health(alias)
    
    return jsonify({
        'success': True,
        'healthy': healthy,
        'message': message
    })


@control_center_bp.route('/update_tls', methods=['POST'])
def update_tls():
    """Update TLS preference for an agent."""
    if not _cc_manager:
        return jsonify({'success': False, 'error': 'Control center not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    alias = data.get('alias', '').strip()
    use_tls = data.get('use_tls')
    
    if not alias:
        return jsonify({'success': False, 'error': 'Alias is required'}), 400
    if use_tls is None:
        return jsonify({'success': False, 'error': 'use_tls is required'}), 400
    
    # Convert to bool if string
    if isinstance(use_tls, str):
        use_tls = use_tls.lower() in ('true', '1', 'yes')
    
    success, message = _cc_manager.update_tls(alias, use_tls)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@control_center_bp.route('/update', methods=['POST'])
def update_agent():
    """Update an existing agent connection."""
    if not _cc_manager:
        return jsonify({'success': False, 'error': 'Control center not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    old_alias = data.get('old_alias', '').strip()
    new_alias = data.get('alias', '').strip()
    host = data.get('host', '').strip()
    port = data.get('port')
    use_tls = data.get('use_tls', True)
    
    if not old_alias:
        return jsonify({'success': False, 'error': 'Original alias is required'}), 400
    if not new_alias:
        return jsonify({'success': False, 'error': 'Alias is required'}), 400
    if not host:
        return jsonify({'success': False, 'error': 'Host is required'}), 400
    
    try:
        port = int(port)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Port must be a number'}), 400
    
    # Convert use_tls to bool if string
    if isinstance(use_tls, str):
        use_tls = use_tls.lower() in ('true', '1', 'yes')
    
    success, message = _cc_manager.update_connection(old_alias, new_alias, host, port, use_tls)
    
    if success:
        # Clear session data for old alias if it changed
        if old_alias != new_alias:
            session.pop(f'cc_connected_{old_alias}', None)
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@control_center_bp.route('/discover', methods=['POST'])
def discover_agents():
    """
    Scan network for available ZFS agents.
    
    Uses mDNS if zeroconf is available, and always tries UDP broadcast.
    Returns list of discovered agents.
    """
    if not _cc_manager:
        return jsonify({'success': False, 'error': 'Control center not initialized'}), 500
    
    try:
        from discovery_scanner import discover_agents as scan_agents, is_mdns_available
        from constants import DISCOVERY_TIMEOUT
        
        data = request.get_json() or {}
        timeout = data.get('timeout', DISCOVERY_TIMEOUT)
        
        # Ensure timeout is reasonable
        timeout = max(1.0, min(10.0, float(timeout)))
        
        agents = scan_agents(timeout)
        
        return jsonify({
            'success': True,
            'agents': agents,
            'mdns_available': is_mdns_available(),
            'count': len(agents)
        })
    except ImportError:
        return jsonify({
            'success': False,
            'error': 'Discovery module not available'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Discovery failed: {str(e)}'
        }), 500
