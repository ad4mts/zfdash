/**
 * dom-elements.js - DOM Element References
 * 
 * Centralized cache of frequently used DOM element references.
 * Exports a 'dom' object that gets populated by initDomElements() after DOMContentLoaded.
 * 
 * IMPORTANT: ES6 Module Fix
 * -------------------------
 * We use a mutable object container pattern here instead of individual `export let` 
 * variables because ES6 module exports are live bindings that are READ-ONLY from 
 * the importing module's perspective. By using a single exported object, we can 
 * mutate its properties after the DOM is ready.
 * 
 * The initDomElements() function MUST be called after DOMContentLoaded to populate
 * all DOM references. This is done in app.js's DOMContentLoaded event handler.
 * 
 * Usage: 
 *   import dom from './dom-elements.js';
 *   // After initDomElements() is called in app.js:
 *   dom.zfsTree.innerHTML = '...';
 */

// --- DOM element container object (mutable) ---
const dom = {
    // Body Element
    bodyElement: null,
    
    // Authentication Elements
    loginSection: null,
    appSection: null,
    loginForm: null,
    loginError: null,
    userMenu: null,
    usernameDisplay: null,
    logoutButton: null,
    shutdownButtonItem: null,
    navbarContentLoggedIn: null,
    
    // Change Password Modal Elements
    changePasswordModalElement: null,
    changePasswordModal: null,
    changePasswordForm: null,
    changePasswordError: null,
    changePasswordSuccess: null,
    changePasswordConfirmButton: null,
    
    // Main UI Elements
    zfsTree: null,
    statusIndicator: null,
    detailsPlaceholder: null,
    detailsContent: null,
    detailsTitle: null,
    detailsTabContent: null,
    
    // Tables
    propertiesTable: null,
    propertiesTableBody: null,
    snapshotsTable: null,
    snapshotsTableBody: null,
    
    // Pool Status & Edit
    poolStatusContent: null,
    poolEditTreeContainer: null,
    poolStatusBtn: null,
    poolLayoutBtn: null,
    poolIostatBtn: null,
    
    // Refresh Button
    refreshButton: null,
    
    // Action Modal Elements
    modalElement: null,
    actionModal: null,
    actionModalBody: null,
    actionModalLabel: null,
    actionModalFooter: null
};

/**
 * Initialize all DOM element references
 * Must be called after DOMContentLoaded
 */
export function initDomElements() {
    // --- Body Element ---
    dom.bodyElement = document.body;

    // --- Authentication Elements ---
    dom.loginSection = document.getElementById('login-section');
    dom.appSection = document.getElementById('app-section');
    dom.loginForm = document.getElementById('login-form');
    dom.loginError = document.getElementById('login-error');
    dom.userMenu = document.getElementById('user-menu');
    dom.usernameDisplay = document.getElementById('username-display');
    dom.logoutButton = document.getElementById('logout-button');
    dom.shutdownButtonItem = document.getElementById('shutdown-button-item');
    dom.navbarContentLoggedIn = document.getElementById('navbar-content-loggedin');

    // --- Change Password Modal Elements ---
    dom.changePasswordModalElement = document.getElementById('changePasswordModal');
    dom.changePasswordModal = dom.changePasswordModalElement ? new bootstrap.Modal(dom.changePasswordModalElement) : null;
    dom.changePasswordForm = document.getElementById('change-password-form');
    dom.changePasswordError = document.getElementById('change-password-error');
    dom.changePasswordSuccess = document.getElementById('change-password-success');
    dom.changePasswordConfirmButton = document.getElementById('changePasswordConfirmButton');

    // --- Main UI Elements ---
    dom.zfsTree = document.getElementById('zfs-tree');
    dom.statusIndicator = document.getElementById('status-indicator');
    dom.detailsPlaceholder = document.getElementById('details-placeholder');
    dom.detailsContent = document.getElementById('details-content');
    dom.detailsTitle = document.getElementById('details-title');
    dom.detailsTabContent = document.getElementById('details-tab-content');

    // --- Tables ---
    dom.propertiesTable = document.getElementById('properties-table');
    dom.propertiesTableBody = dom.propertiesTable ? dom.propertiesTable.querySelector('tbody') : null;
    dom.snapshotsTable = document.getElementById('snapshots-table');
    dom.snapshotsTableBody = dom.snapshotsTable ? dom.snapshotsTable.querySelector('tbody') : null;

    // --- Pool Status & Edit ---
    dom.poolStatusContent = document.getElementById('pool-status-content');
    dom.poolEditTreeContainer = document.getElementById('pool-edit-tree-container');
    dom.poolStatusBtn = document.getElementById('pool-status-btn');
    dom.poolLayoutBtn = document.getElementById('pool-layout-btn');
    dom.poolIostatBtn = document.getElementById('pool-iostat-btn');

    // --- Refresh Button ---
    dom.refreshButton = document.getElementById('refresh-button');

    // --- Action Modal Elements ---
    dom.modalElement = document.getElementById('actionModal');
    dom.actionModal = dom.modalElement ? new bootstrap.Modal(dom.modalElement) : null;
    dom.actionModalBody = document.getElementById('actionModalBody');
    dom.actionModalLabel = document.getElementById('actionModalLabel');
    dom.actionModalFooter = document.getElementById('actionModalFooter');
}

/**
 * Get a button element by ID
 * @param {string} id - Button element ID
 * @returns {HTMLElement|null} - Button element or null
 */
export function getButton(id) {
    return document.getElementById(id);
}

/**
 * Toggle disabled state of a button
 * @param {string} id - Button element ID
 * @param {boolean} disabled - Whether to disable
 */
export function toggleButtonDisabled(id, disabled) {
    const btn = getButton(id);
    if (btn) {
        btn.classList.toggle('disabled', disabled);
    }
}

// Export the dom object as default
export default dom;
