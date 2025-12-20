"""
Credential Routes - Flask Blueprint for Credential Vault API

Provides REST API endpoints for managing the credential vault:
- Vault status (exists/unlocked)
- Create vault with master password
- Unlock/lock vault
- Get/set/delete agent passwords
"""

from flask import Blueprint, request, jsonify, session
from flask_login import login_required

from credential_vault import get_vault

# Create Blueprint
credential_bp = Blueprint('credentials', __name__)

# Session key for vault unlock state
VAULT_UNLOCKED_KEY = 'vault_unlocked'


@credential_bp.route('/status', methods=['GET'])
@login_required
def vault_status():
    """
    Get vault status.
    
    Returns:
        JSON with vault status:
        - available: bool - crypto libraries installed
        - initialized: bool - vault file exists
        - unlocked: bool - vault is unlocked for this session
    """
    vault = get_vault()
    
    return jsonify({
        'success': True,
        'data': {
            'available': vault.is_available(),
            'initialized': vault.is_initialized(),
            'unlocked': vault.is_unlocked() and session.get(VAULT_UNLOCKED_KEY, False)
        }
    })


@credential_bp.route('/create', methods=['POST'])
@login_required
def create_vault():
    """
    Create a new vault with master password.
    
    Request JSON:
        master_password: Master password for vault
        
    Returns:
        JSON with success status
    """
    vault = get_vault()
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    master_password = data.get('master_password', '')
    
    success, message = vault.create(master_password)
    
    if success:
        session[VAULT_UNLOCKED_KEY] = True
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@credential_bp.route('/unlock', methods=['POST'])
@login_required
def unlock_vault():
    """
    Unlock vault with master password.
    
    Request JSON:
        master_password: Master password
        
    Returns:
        JSON with success status
    """
    vault = get_vault()
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    master_password = data.get('master_password', '')
    
    success, message = vault.unlock(master_password)
    
    if success:
        session[VAULT_UNLOCKED_KEY] = True
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@credential_bp.route('/lock', methods=['POST'])
@login_required
def lock_vault():
    """
    Lock the vault.
    
    Returns:
        JSON with success status
    """
    vault = get_vault()
    vault.lock()
    session.pop(VAULT_UNLOCKED_KEY, None)
    
    return jsonify({'success': True, 'message': 'Vault locked'})


@credential_bp.route('/password/<agent_alias>', methods=['GET'])
@login_required
def get_password(agent_alias):
    """
    Get stored password for an agent.
    
    Returns:
        JSON with password (if found and vault unlocked)
    """
    vault = get_vault()
    
    if not vault.is_unlocked():
        return jsonify({
            'success': False, 
            'error': 'Vault is locked',
            'needs_unlock': True
        }), 401
    
    password = vault.get_password(agent_alias)
    
    if password is not None:
        return jsonify({
            'success': True,
            'data': {'password': password, 'has_password': True}
        })
    else:
        return jsonify({
            'success': True,
            'data': {'password': None, 'has_password': False}
        })


@credential_bp.route('/password', methods=['POST'])
@login_required
def save_password():
    """
    Save password for an agent.
    
    Request JSON:
        agent_alias: Agent identifier
        password: Password to store
        
    Returns:
        JSON with success status
    """
    vault = get_vault()
    
    if not vault.is_unlocked():
        return jsonify({
            'success': False, 
            'error': 'Vault is locked',
            'needs_unlock': True
        }), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    agent_alias = data.get('agent_alias', '').strip()
    password = data.get('password', '')
    
    if not agent_alias:
        return jsonify({'success': False, 'error': 'Agent alias is required'}), 400
    
    success, message = vault.set_password(agent_alias, password)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@credential_bp.route('/password/<agent_alias>', methods=['DELETE'])
@login_required
def delete_password(agent_alias):
    """
    Delete stored password for an agent.
    
    Returns:
        JSON with success status
    """
    vault = get_vault()
    
    if not vault.is_unlocked():
        return jsonify({
            'success': False, 
            'error': 'Vault is locked',
            'needs_unlock': True
        }), 401
    
    success, message = vault.delete_password(agent_alias)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@credential_bp.route('/list', methods=['GET'])
@login_required
def list_stored_passwords():
    """
    List all agents with stored passwords.
    
    Returns:
        JSON with list of agent aliases
    """
    vault = get_vault()
    
    if not vault.is_unlocked():
        return jsonify({
            'success': False, 
            'error': 'Vault is locked',
            'needs_unlock': True
        }), 401
    
    agents = vault.list_agents()
    
    return jsonify({
        'success': True,
        'data': {'agents': agents}
    })


@credential_bp.route('/change-password', methods=['POST'])
@login_required
def change_master_password():
    """
    Change the vault master password.
    
    Request JSON:
        old_password: Current master password
        new_password: New master password
        
    Returns:
        JSON with success status
    """
    vault = get_vault()
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    
    success, message = vault.change_master_password(old_password, new_password)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400


@credential_bp.route('/delete-vault', methods=['POST'])
@login_required
def delete_vault():
    """
    Delete the entire vault.
    
    Request JSON:
        confirm: Must be true to confirm deletion
        
    Returns:
        JSON with success status
    """
    vault = get_vault()
    
    data = request.get_json()
    if not data or not data.get('confirm'):
        return jsonify({'success': False, 'error': 'Deletion not confirmed'}), 400
    
    success, message = vault.delete_vault()
    session.pop(VAULT_UNLOCKED_KEY, None)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400
