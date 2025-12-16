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
    
    if not alias:
        return jsonify({'success': False, 'error': 'Alias is required'}), 400
    if not host:
        return jsonify({'success': False, 'error': 'Host is required'}), 400
    
    try:
        port = int(port)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Port must be a number'}), 400
    
    success, message = _cc_manager.add_connection(alias, host, port)
    
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
    
    success, message = _cc_manager.connect_to_agent(alias, password, session)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


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
    
    success, message = _cc_manager.switch_active_agent(alias, session)
    
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
        connections = _cc_manager.list_connections()
        
        # Add current mode info
        current_mode = session.get('cc_mode', 'local')
        active_alias = session.get('cc_active_alias')
        
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
