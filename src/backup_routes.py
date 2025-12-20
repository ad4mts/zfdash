"""
Backup Routes - Flask Blueprint for ZFS Backup API

Provides REST API endpoints for ZFS send/receive backup operations:
- Send snapshot/dataset to remote agent (returns job_id for tracking)
- Get backup job status
- List all backup jobs
- Cancel a running backup
"""

from flask import Blueprint, request, jsonify, session
from flask_login import login_required

# Create Blueprint
backup_bp = Blueprint('backup', __name__)

# Will be set by web_ui.py when registering blueprint
_zfs_client_getter = None


def init_backup_routes(get_zfs_client):
    """
    Initialize backup routes with a ZFS client getter function.
    
    Args:
        get_zfs_client: Function that returns current ZfsManagerClient
    """
    global _zfs_client_getter
    _zfs_client_getter = get_zfs_client


@backup_bp.route('/send-to-agent', methods=['POST'])
@login_required
def send_to_agent():
    """
    Send a ZFS snapshot/dataset to a remote agent.
    
    Request JSON:
        source_dataset: Source snapshot or dataset name
        dest_host: Destination agent hostname/IP
        dest_port: Destination agent port (default: 5555)
        dest_password: Password for destination agent
        dest_dataset: Target dataset name on destination
        incremental_base: Optional base snapshot for incremental send
        use_tls: Whether to use TLS (default: True)
    
    Returns:
        JSON with job_id and bytes_transferred on success
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    # Required fields
    source_dataset = data.get('source_dataset', '').strip()
    dest_host = data.get('dest_host', '').strip()
    dest_password = data.get('dest_password', '')
    dest_dataset = data.get('dest_dataset', '').strip()
    
    # Optional fields with defaults
    dest_port = data.get('dest_port', 5555)
    incremental_base = (data.get('incremental_base') or '').strip() or None
    use_tls = data.get('use_tls', True)
    
    # Validation
    if not source_dataset:
        return jsonify({'success': False, 'error': 'Source dataset is required'}), 400
    if not dest_host:
        return jsonify({'success': False, 'error': 'Destination host is required'}), 400
    if not dest_password:
        return jsonify({'success': False, 'error': 'Destination password is required'}), 400
    if not dest_dataset:
        return jsonify({'success': False, 'error': 'Destination dataset is required'}), 400
    
    try:
        dest_port = int(dest_port)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Port must be a number'}), 400
    
    # Convert use_tls to bool if string
    if isinstance(use_tls, str):
        use_tls = use_tls.lower() in ('true', '1', 'yes')
    
    try:
        client = _zfs_client_getter()
        
        # Call daemon to perform backup
        result = client._send_request(
            'send_backup',
            source_dataset=source_dataset,
            dest_host=dest_host,
            dest_port=dest_port,
            dest_password=dest_password,
            dest_dataset=dest_dataset,
            incremental_base=incremental_base,
            use_tls=use_tls
        )
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {}),
                'message': 'Backup completed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Backup failed: {str(e)}'
        }), 500


@backup_bp.route('/status/<job_id>', methods=['GET'])
@login_required
def backup_status(job_id):
    """
    Get status of a backup job.
    
    Returns:
        JSON with job status, progress percentage, bytes transferred, etc.
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    try:
        client = _zfs_client_getter()
        result = client._send_request('get_backup_status', job_id=job_id)
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {})
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get job status: {str(e)}'
        }), 500


@backup_bp.route('/list', methods=['GET'])
@login_required
def list_backup_jobs():
    """
    List all backup jobs.
    
    Query params:
        include_completed: Include completed/failed/cancelled jobs (default: true)
    
    Returns:
        JSON with dict of job_id -> job details
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    include_completed = request.args.get('include_completed', 'true').lower() in ('true', '1', 'yes')
    
    try:
        client = _zfs_client_getter()
        result = client._send_request('list_backup_jobs', include_completed=include_completed)
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {})
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to list jobs: {str(e)}'
        }), 500


@backup_bp.route('/cancel/<job_id>', methods=['POST'])
@login_required
def cancel_backup(job_id):
    """
    Cancel a running backup job.
    
    Returns:
        JSON with success status
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    try:
        client = _zfs_client_getter()
        result = client._send_request('cancel_backup', job_id=job_id)
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'message': f'Job {job_id} cancelled'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to cancel job: {str(e)}'
        }), 500


# ============== New endpoints for Jobs Tab ==============

@backup_bp.route('/jobs', methods=['GET'])
@login_required
def get_jobs():
    """
    List all backup jobs (alias for /list).
    
    Returns:
        JSON with dict of job_id -> job details
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    include_completed = request.args.get('include_completed', 'true').lower() in ('true', '1', 'yes')
    
    try:
        client = _zfs_client_getter()
        result = client._send_request('list_backup_jobs', include_completed=include_completed)
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {})
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to list jobs: {str(e)}'
        }), 500


@backup_bp.route('/cancel', methods=['POST'])
@login_required
def cancel_backup_post():
    """
    Cancel a running backup job (POST with JSON body).
    
    Request JSON:
        job_id: Job ID to cancel
    
    Returns:
        JSON with success status
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    job_id = data.get('job_id', '').strip()
    if not job_id:
        return jsonify({'success': False, 'error': 'Job ID is required'}), 400
    
    try:
        client = _zfs_client_getter()
        result = client._send_request('cancel_backup', job_id=job_id)
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'message': f'Job {job_id} cancelled'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to cancel job: {str(e)}'
        }), 500


@backup_bp.route('/delete', methods=['POST'])
@login_required
def delete_job():
    """
    Delete a completed/failed/cancelled backup job from history.
    
    Request JSON:
        job_id: Job ID to delete
    
    Returns:
        JSON with success status
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    job_id = data.get('job_id', '').strip()
    if not job_id:
        return jsonify({'success': False, 'error': 'Job ID is required'}), 400
    
    try:
        client = _zfs_client_getter()
        result = client._send_request('delete_backup_job', job_id=job_id)
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'message': f'Job {job_id} deleted'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to delete job: {str(e)}'
        }), 500


@backup_bp.route('/clear-completed', methods=['POST'])
@login_required
def clear_completed_jobs():
    """
    Clear all completed backup jobs from history.
    
    Returns:
        JSON with success status and count of cleared jobs
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    try:
        client = _zfs_client_getter()
        result = client._send_request('clear_completed_jobs')
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {}),
                'message': 'Completed jobs cleared'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to clear jobs: {str(e)}'
        }), 500


@backup_bp.route('/resume', methods=['POST'])
@login_required
def resume_backup():
    """
    Resume a failed backup job using its stored resume token.
    
    Request JSON:
        job_id: Job ID to resume
        dest_password: Password for destination agent (required)
        dest_host: Optional, override stored host
        dest_port: Optional, override stored port
        use_tls: Whether to use TLS (default: True)
    
    Returns:
        JSON with job result on success
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    job_id = data.get('job_id', '').strip()
    dest_password = data.get('dest_password', '')
    
    if not job_id:
        return jsonify({'success': False, 'error': 'Job ID is required'}), 400
    if not dest_password:
        return jsonify({'success': False, 'error': 'Destination password is required'}), 400
    
    try:
        client = _zfs_client_getter()
        result = client._send_request(
            'resume_backup',
            job_id=job_id,
            dest_password=dest_password,
            dest_host=data.get('dest_host'),
            dest_port=data.get('dest_port'),
            use_tls=data.get('use_tls', True)
        )
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {}),
                'message': 'Backup resumed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to resume backup: {str(e)}'
        }), 500


@backup_bp.route('/fetch-token', methods=['POST'])
@login_required
def fetch_resume_token():
    """
    Manually fetch resume token from destination agent.
    
    Used when automatic token fetch failed (network was down during failure).
    This allows the UI to offer a "Fetch Token" button.
    
    Request JSON:
        job_id: Job ID that needs token fetch
        dest_host: Destination agent hostname/IP
        dest_port: Destination agent port
        dest_password: Password for destination agent
    
    Returns:
        JSON with token on success
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    job_id = data.get('job_id', '').strip()
    dest_host = data.get('dest_host', '').strip()
    dest_port = data.get('dest_port')
    dest_password = data.get('dest_password', '')
    
    if not job_id:
        return jsonify({'success': False, 'error': 'Job ID is required'}), 400
    if not dest_host:
        return jsonify({'success': False, 'error': 'Destination host is required'}), 400
    if not dest_port:
        return jsonify({'success': False, 'error': 'Destination port is required'}), 400
    if not dest_password:
        return jsonify({'success': False, 'error': 'Destination password is required'}), 400
    
    try:
        dest_port = int(dest_port)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Port must be a number'}), 400
    
    try:
        client = _zfs_client_getter()
        result = client._send_request(
            'fetch_resume_token',
            job_id=job_id,
            dest_host=dest_host,
            dest_port=dest_port,
            dest_password=dest_password
        )
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {}),
                'message': 'Resume token fetched successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to fetch token: {str(e)}'
        }), 500


# ============== Agent-to-Agent Backup Endpoints ==============

def _create_temp_client(host, port, password, use_tls=True):
    """
    Create a temporary ZfsManagerClient connection to a remote agent.
    
    Args:
        host: Agent hostname/IP
        port: Agent port
        password: Agent password
        use_tls: Whether to use TLS
        
    Returns:
        Tuple of (client, error_message)
    """
    try:
        from ipc_tcp_client import connect_to_agent
        from zfs_manager import ZfsManagerClient
        
        transport, tls_active = connect_to_agent(host, port, password, timeout=30.0, use_tls=use_tls)
        
        client = ZfsManagerClient(
            daemon_process=None,
            transport=transport,
            owns_daemon=False
        )
        
        return client, None
        
    except Exception as e:
        return None, str(e)


@backup_bp.route('/agent-tree', methods=['POST'])
@login_required
def get_agent_tree():
    """
    Fetch ZFS tree from a specific agent.
    
    Used by agent-to-agent backup to load datasets from the sender agent.
    
    Request JSON:
        host: Agent hostname/IP
        port: Agent port
        password: Agent password
        use_tls: Whether to use TLS (default: True)
        
    Returns:
        JSON with ZFS tree data
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    host = data.get('host', '').strip()
    port = data.get('port', 5555)
    password = data.get('password', '')
    use_tls = data.get('use_tls', True)
    
    if not host:
        return jsonify({'success': False, 'error': 'Host is required'}), 400
    if not password:
        return jsonify({'success': False, 'error': 'Password is required'}), 400
    
    try:
        port = int(port)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Port must be a number'}), 400
    
    # Convert use_tls to bool if string
    if isinstance(use_tls, str):
        use_tls = use_tls.lower() in ('true', '1', 'yes')
    
    client, error = _create_temp_client(host, port, password, use_tls)
    if error:
        return jsonify({'success': False, 'error': f'Connection failed: {error}'}), 400
    
    try:
        # Get ZFS data from the agent
        result = client.get_all_zfs_data()
        
        # Convert to dict if needed (using same helper as web_ui)
        from dataclasses import is_dataclass, fields
        
        def _to_dict_recursive(obj):
            if isinstance(obj, list):
                return [_to_dict_recursive(item) for item in obj]
            elif is_dataclass(obj) and not isinstance(obj, type):
                result = {}
                for field_info in fields(obj):
                    if field_info.name == 'parent':
                        continue
                    value = getattr(obj, field_info.name)
                    result[field_info.name] = _to_dict_recursive(value)
                return result
            elif isinstance(obj, (str, int, float, bool, type(None), dict)):
                return obj
            else:
                return str(obj)
        
        dict_result = _to_dict_recursive(result)
        
        return jsonify({
            'success': True,
            'data': dict_result
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to fetch tree: {str(e)}'
        }), 500
        
    finally:
        try:
            client.close()
        except Exception:
            pass


@backup_bp.route('/agent-to-agent', methods=['POST'])
@login_required
def agent_to_agent():
    """
    Initiate backup from sender agent to receiver agent.
    
    WebUI acts as orchestrator - connects to sender, tells it to push to receiver.
    
    Request JSON:
        sender_host: Sender agent hostname/IP
        sender_port: Sender agent port
        sender_password: Sender agent password
        sender_tls: Whether to use TLS for sender (default: True)
        source_dataset: Source snapshot/dataset name
        dest_host: Destination agent hostname/IP  
        dest_port: Destination agent port
        dest_password: Destination agent password
        dest_dataset: Target dataset name on destination
        dest_tls: Whether to use TLS for destination (default: True)
        
    Returns:
        JSON with job result
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    # Sender details
    sender_host = data.get('sender_host', '').strip()
    sender_port = data.get('sender_port', 5555)
    sender_password = data.get('sender_password', '')
    sender_tls = data.get('sender_tls', True)
    
    # Source dataset
    source_dataset = data.get('source_dataset', '').strip()
    
    # Destination details
    dest_host = data.get('dest_host', '').strip()
    dest_port = data.get('dest_port', 5555)
    dest_password = data.get('dest_password', '')
    dest_dataset = data.get('dest_dataset', '').strip()
    dest_tls = data.get('dest_tls', True)
    
    # Optional incremental base
    incremental_base = (data.get('incremental_base') or '').strip() or None
    
    # Validation
    if not sender_host:
        return jsonify({'success': False, 'error': 'Sender host is required'}), 400
    if not sender_password:
        return jsonify({'success': False, 'error': 'Sender password is required'}), 400
    if not source_dataset:
        return jsonify({'success': False, 'error': 'Source dataset is required'}), 400
    if not dest_host:
        return jsonify({'success': False, 'error': 'Destination host is required'}), 400
    if not dest_password:
        return jsonify({'success': False, 'error': 'Destination password is required'}), 400
    if not dest_dataset:
        return jsonify({'success': False, 'error': 'Destination dataset is required'}), 400
    
    try:
        sender_port = int(sender_port)
        dest_port = int(dest_port)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Ports must be numbers'}), 400
    
    # Convert TLS to bool if string
    if isinstance(sender_tls, str):
        sender_tls = sender_tls.lower() in ('true', '1', 'yes')
    if isinstance(dest_tls, str):
        dest_tls = dest_tls.lower() in ('true', '1', 'yes')
    
    # Connect to sender agent
    client, error = _create_temp_client(sender_host, sender_port, sender_password, sender_tls)
    if error:
        return jsonify({'success': False, 'error': f'Failed to connect to sender: {error}'}), 400
    
    try:
        # Tell sender to push to receiver
        result = client._send_request(
            'send_backup',
            source_dataset=source_dataset,
            dest_host=dest_host,
            dest_port=dest_port,
            dest_password=dest_password,
            dest_dataset=dest_dataset,
            incremental_base=incremental_base,
            use_tls=dest_tls
        )
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {}),
                'message': 'Backup completed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Backup failed: {str(e)}'
        }), 500
        
    finally:
        try:
            client.close()
        except Exception:
            pass


# ============== Auto-Incremental Base Detection ==============

def _list_snapshots_with_guid(client, dataset: str) -> list:
    """
    List snapshots for a dataset with GUID information via daemon client.
    
    Args:
        client: ZfsManagerClient to query
        dataset: Dataset name to list snapshots for
        
    Returns:
        List of dicts with name, guid, creation for each snapshot
        
    Raises:
        Exception: If daemon connection fails or returns error
    """
    # Use list_all_datasets_snapshots which is the actual daemon command
    result = client._send_request('list_all_datasets_snapshots')
    if result.get('status') != 'success':
        error = result.get('error', 'Unknown error listing snapshots')
        raise Exception(f"Failed to list snapshots: {error}")
    
    all_items = result.get('data', [])
    
    # Filter to only snapshots for this dataset
    # Snapshot names are like "pool/dataset@snapname"
    dataset_prefix = dataset + '@'
    snapshots = []
    
    for item in all_items:
        name = item.get('name', '')
        # Check if this is a snapshot of our dataset
        if '@' in name and (name.startswith(dataset_prefix) or name.split('@')[0] == dataset):
            snapshots.append({
                'name': name,
                'guid': item.get('guid', ''),
                'creation': item.get('creation', '')
            })
    
    return snapshots


def _find_common_snapshot_by_guid(source_snapshots: list, dest_snapshots: list) -> dict:
    """
    Find the newest common snapshot between source and destination by GUID.
    """
    dest_guids = {s['guid'] for s in dest_snapshots if s.get('guid')}
    common = [s for s in source_snapshots if s.get('guid') in dest_guids]
    
    if not common:
        return None
    
    # Sort by creation time (newest first)
    try:
        common.sort(key=lambda s: int(s.get('creation', 0)), reverse=True)
    except (ValueError, TypeError):
        common.sort(key=lambda s: s.get('creation', ''), reverse=True)
    
    return {
        'incremental_base': common[0]['name'],
        'guid': common[0]['guid']
    }


@backup_bp.route('/find-incremental-base', methods=['POST'])
@login_required
def find_incremental_base():
    """
    Find the best incremental base snapshot by matching GUIDs.
    
    Queries source and destination to find the newest common snapshot
    that exists on both systems (matched by GUID, not name).
    
    Request JSON:
        source_dataset: Source dataset name (e.g., tank/data)
        source_agent: Optional dict with host, port, password, use_tls
        dest_type: 'local', 'agent', or 'ssh'
        dest_dataset: Destination dataset name
        dest_agent: Required if dest_type='agent'
        dest_ssh: Required if dest_type='ssh'
        
    Returns:
        JSON with incremental_base snapshot name and all source snapshots
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    source_dataset = (data.get('source_dataset') or '').strip()
    source_agent = data.get('source_agent')
    dest_type = (data.get('dest_type') or 'local').strip()
    dest_dataset = (data.get('dest_dataset') or '').strip()
    dest_agent = data.get('dest_agent')
    dest_ssh = data.get('dest_ssh')
    
    if not source_dataset:
        return jsonify({'success': False, 'error': 'Source dataset is required'}), 400
    if not dest_dataset:
        return jsonify({'success': False, 'error': 'Destination dataset is required'}), 400
    
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Daemon not connected'}), 503
    
    # Track clients we CREATE (not the main one from _zfs_client_getter)
    temp_source_client = None
    temp_dest_client = None
    
    try:
        # Get source snapshots
        if source_agent:
            # A2A: source is explicit remote agent (different from WebUI connection)
            host = source_agent.get('host', '').strip()
            port = int(source_agent.get('port', 5555))
            password = source_agent.get('password', '')
            use_tls = source_agent.get('use_tls', True)
            
            if not host or not password:
                return jsonify({'success': False, 'error': 'Source agent host and password required'}), 400
            
            temp_source_client, error = _create_temp_client(host, port, password, use_tls)
            if error:
                return jsonify({'success': False, 'error': f'Failed to connect to source: {error}'}), 400
            source_client = temp_source_client
        else:
            # Default: use WebUI's current daemon connection (local or remote)
            source_client = _zfs_client_getter()
        
        source_snapshots = _list_snapshots_with_guid(source_client, source_dataset)
        
        if not source_snapshots:
            return jsonify({
                'success': True,
                'incremental_base': None,
                'message': 'No snapshots found on source',
                'all_source_snapshots': [],
                'method': 'guid'
            })
        
        # Get destination snapshots
        if dest_type == 'local':
            # Use current daemon connection for local destination too (don't close!)
            # If the Webui is connected to an Agent, the Agent is considered as local in the local backup tab!
            dest_client = _zfs_client_getter()
            dest_snapshots = _list_snapshots_with_guid(dest_client, dest_dataset)
            
        elif dest_type == 'agent':
            if not dest_agent:
                return jsonify({'success': False, 'error': 'Destination agent info required'}), 400
            
            host = dest_agent.get('host', '').strip()
            port = int(dest_agent.get('port', 5555))
            password = dest_agent.get('password', '')
            use_tls = dest_agent.get('use_tls', True)
            
            if not host or not password:
                return jsonify({'success': False, 'error': 'Destination agent host and password required'}), 400
            
            temp_dest_client, error = _create_temp_client(host, port, password, use_tls)
            if error:
                return jsonify({'success': False, 'error': f'Failed to connect to destination: {error}'}), 400
            
            dest_snapshots = _list_snapshots_with_guid(temp_dest_client, dest_dataset)
            
        elif dest_type == 'ssh':
            if not dest_ssh:
                return jsonify({'success': False, 'error': 'SSH destination info required'}), 400
            
            import paramiko
            
            ssh_host = dest_ssh.get('host', '').strip()
            ssh_port = int(dest_ssh.get('port', 22))
            ssh_user = dest_ssh.get('user', 'root').strip()
            ssh_password = dest_ssh.get('password', '')
            ssh_key_path = dest_ssh.get('key_path')
            
            if not ssh_host:
                return jsonify({'success': False, 'error': 'SSH host required'}), 400
            
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                connect_kwargs = {
                    'hostname': ssh_host,
                    'port': ssh_port,
                    'username': ssh_user,
                    'timeout': 30
                }
                if ssh_key_path:
                    connect_kwargs['key_filename'] = ssh_key_path
                elif ssh_password:
                    connect_kwargs['password'] = ssh_password
                else:
                    connect_kwargs['allow_agent'] = True
                    connect_kwargs['look_for_keys'] = True
                
                ssh.connect(**connect_kwargs)
                
                # Prepend common paths - non-interactive SSH sessions often lack sbin/brew paths
                cmd = f'export PATH="/usr/sbin:/sbin:/usr/local/sbin:/usr/local/bin:/opt/homebrew/bin:$PATH"; zfs list -t snapshot -H -p -o name,guid,creation -r {dest_dataset}'
                stdin_ch, stdout_ch, stderr_ch = ssh.exec_command(cmd)
                rc = stdout_ch.channel.recv_exit_status()
                stdout = stdout_ch.read().decode('utf-8', errors='replace')
                ssh.close()
                
                if rc != 0:
                    dest_snapshots = []
                else:
                    dest_snapshots = []
                    for line in stdout.strip().split('\n'):
                        if not line:
                            continue
                        parts = line.split('\t')
                        if len(parts) >= 3:
                            dest_snapshots.append({
                                'name': parts[0],
                                'guid': parts[1], 
                                'creation': parts[2]
                            })
            except Exception as ssh_err:
                return jsonify({'success': False, 'error': f'SSH error: {ssh_err}'}), 400
        else:
            return jsonify({'success': False, 'error': f'Unknown dest_type: {dest_type}'}), 400
        
        # Find common snapshot by GUID
        common = _find_common_snapshot_by_guid(source_snapshots, dest_snapshots)
        all_source_names = [s['name'] for s in source_snapshots]
        
        if common:
            return jsonify({
                'success': True,
                'incremental_base': common['incremental_base'],
                'incremental_base_guid': common['guid'],
                'all_source_snapshots': all_source_names,
                'method': 'guid'
            })
        else:
            return jsonify({
                'success': True,
                'incremental_base': None,
                'message': 'No common snapshot found - full backup required',
                'all_source_snapshots': all_source_names,
                'method': 'guid'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to find incremental base: {str(e)}'
        }), 500
        
    finally:
        # Only close TEMP clients (ones we created), not the main daemon connection
        if temp_source_client:
            try:
                temp_source_client.close()
            except Exception:
                pass
        if temp_dest_client:
            try:
                temp_dest_client.close()
            except Exception:
                pass


# ============== Local / File / SSH Backup Endpoints ==============

@backup_bp.route('/local', methods=['POST'])
@login_required
def local_backup():
    """
    Perform local pool-to-pool replication.
    
    Request JSON:
        source_snapshot: Source snapshot name (e.g., tank/data@snap1)
        dest_dataset: Destination dataset path (e.g., backup/data)
        incremental_base: Optional base snapshot for incremental send
        force_rollback: Whether to use -F flag (default: True)
    
    Returns:
        JSON with job result on success
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    source_snapshot = (data.get('source_snapshot') or '').strip()
    dest_dataset = (data.get('dest_dataset') or '').strip()
    incremental_base = (data.get('incremental_base') or '').strip() or None
    force_rollback = data.get('force_rollback', True)
    
    if not source_snapshot:
        return jsonify({'success': False, 'error': 'Source snapshot is required'}), 400
    if not dest_dataset:
        return jsonify({'success': False, 'error': 'Destination dataset is required'}), 400
    
    try:
        # If the Webui is connected to an Agent, this Agent is considered as Local!
        client = _zfs_client_getter()
        result = client._send_request(
            'local_backup',
            source_snapshot=source_snapshot,
            dest_dataset=dest_dataset,
            incremental_base=incremental_base,
            force_rollback=force_rollback
        )
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {}),
                'message': 'Local replication completed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Local replication failed: {str(e)}'
        }), 500


@backup_bp.route('/export-file', methods=['POST'])
@login_required
def export_to_file():
    """
    Export snapshot to a file.
    
    Request JSON:
        source_snapshot: Source snapshot name
        file_path: Full path for output file
        compression: Compression type (none, gzip, lz4, zstd)
        incremental_base: Optional base snapshot for incremental stream
    
    Returns:
        JSON with bytes_written on success
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    source_snapshot = (data.get('source_snapshot') or '').strip()
    file_path = (data.get('file_path') or '').strip()
    compression = data.get('compression', 'none')
    incremental_base = (data.get('incremental_base') or '').strip() or None
    
    if not source_snapshot:
        return jsonify({'success': False, 'error': 'Source snapshot is required'}), 400
    if not file_path:
        return jsonify({'success': False, 'error': 'File path is required'}), 400
    
    # Validate compression option
    valid_compressions = ['none', 'gzip', 'lz4', 'zstd']
    if compression not in valid_compressions:
        return jsonify({'success': False, 'error': f'Invalid compression: {compression}'}), 400
    
    try:
        client = _zfs_client_getter()
        result = client._send_request(
            'export_to_file',
            source_snapshot=source_snapshot,
            file_path=file_path,
            compression=compression,
            incremental_base=incremental_base
        )
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {}),
                'message': 'Export completed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Export failed: {str(e)}'
        }), 500


@backup_bp.route('/send-ssh', methods=['POST'])
@login_required
def send_to_ssh():
    """
    Send snapshot to remote host via SSH.
    
    Request JSON:
        source_snapshot: Source snapshot name
        ssh_host: Remote SSH host
        ssh_port: SSH port (default: 22)
        ssh_user: SSH username
        ssh_password: SSH password
        dest_dataset: Destination dataset on remote host
        incremental_base: Optional base snapshot for incremental send
        force_rollback: Whether to use -F flag (default: True)
    
    Returns:
        JSON with bytes_transferred on success
    """
    if not _zfs_client_getter:
        return jsonify({'success': False, 'error': 'Backup module not initialized'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    source_snapshot = (data.get('source_snapshot') or '').strip()
    ssh_host = (data.get('ssh_host') or '').strip()
    ssh_port = data.get('ssh_port', 22)
    ssh_user = (data.get('ssh_user') or '').strip()
    dest_dataset = (data.get('dest_dataset') or '').strip()
    incremental_base = (data.get('incremental_base') or '').strip() or None
    force_rollback = data.get('force_rollback', True)
    
    # Auth parameters
    auth_method = (data.get('auth_method') or 'auto').strip()
    ssh_password = data.get('ssh_password') or ''
    ssh_key_path = (data.get('ssh_key_path') or '').strip() or None
    ssh_key_passphrase = data.get('ssh_key_passphrase') or None
    
    if not source_snapshot:
        return jsonify({'success': False, 'error': 'Source snapshot is required'}), 400
    if not ssh_host:
        return jsonify({'success': False, 'error': 'SSH host is required'}), 400
    if not ssh_user:
        return jsonify({'success': False, 'error': 'SSH username is required'}), 400
    if not dest_dataset:
        return jsonify({'success': False, 'error': 'Destination dataset is required'}), 400
    
    # Validate based on auth method
    if auth_method == 'password' and not ssh_password:
        return jsonify({'success': False, 'error': 'SSH password is required for password auth'}), 400
    
    try:
        ssh_port = int(ssh_port)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'SSH port must be a number'}), 400
    
    try:
        client = _zfs_client_getter()
        result = client._send_request(
            'send_ssh',
            source_snapshot=source_snapshot,
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            dest_dataset=dest_dataset,
            auth_method=auth_method,
            ssh_password=ssh_password,
            ssh_key_path=ssh_key_path,
            ssh_key_passphrase=ssh_key_passphrase,
            incremental_base=incremental_base,
            force_rollback=force_rollback
        )
        
        if result.get('status') == 'success':
            return jsonify({
                'success': True,
                'data': result.get('data', {}),
                'message': 'SSH backup completed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'SSH backup failed: {str(e)}'
        }), 500
