/**
 * Control Center API Module
 * 
 * Provides abstraction layer for all Control Center API calls.
 */

/**
 * List all configured remote agents
 * @returns {Promise<Object>} Response with connections array
 */
export async function listAgents() {
    const response = await fetch('/api/cc/list');
    return await response.json();
}

/**
 * Add a new remote agent
 * @param {string} alias - Agent alias
 * @param {string} host - Remote host
 * @param {number} port - Remote port
 * @returns {Promise<Object>} Response with success status
 */
export async function addAgent(alias, host, port) {
    const response = await fetch('/api/cc/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alias, host, port })
    });
    return await response.json();
}

/**
 * Remove a remote agent
 * @param {string} alias - Agent alias to remove
 * @returns {Promise<Object>} Response with success status
 */
export async function removeAgent(alias) {
    const response = await fetch('/api/cc/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alias })
    });
    return await response.json();
}

/**
 * Connect to a remote agent (with password)
 * @param {string} alias - Agent alias
 * @param {string} password - Admin password
 * @returns {Promise<Object>} Response with success status
 */
export async function connectAgent(alias, password) {
    const response = await fetch('/api/cc/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alias, password })
    });
    return await response.json();
}

/**
 * Disconnect from a remote agent
 * @param {string} alias - Agent alias
 * @returns {Promise<Object>} Response with success status
 */
export async function disconnectAgent(alias) {
    const response = await fetch('/api/cc/disconnect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alias })
    });
    return await response.json();
}

/**
 * Switch active agent
 * @param {string} alias - Agent alias to switch to ('local' for local daemon)
 * @returns {Promise<Object>} Response with success status
 */
export async function switchAgent(alias) {
    const response = await fetch(`/api/cc/switch/${alias}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    });
    return await response.json();
}

/**
 * Check agent connection health
 * @param {string} alias - Agent alias
 * @returns {Promise<Object>} Response with healthy status
 */
export async function checkAgentHealth(alias) {
    const response = await fetch(`/api/cc/health/${alias}`);
    return await response.json();
}
