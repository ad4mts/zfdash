/**
 * state.js - Application State Management
 * 
 * Centralized state management for the ZfDash application.
 * Contains all global state variables and functions for state persistence.
 * 
 * IMPORTANT: ES6 Module Export Pattern
 * -------------------------------------
 * ES6 module exports are live bindings that are READ-ONLY from the importing 
 * module's perspective. While we can read `state.currentSelection` directly,
 * we CANNOT assign to it like `state.currentSelection = value`.
 * 
 * Instead, use the provided setter functions:
 *   - state.setCurrentSelection(value)  ✓ Correct
 *   - state.currentSelection = value    ✗ Will throw error
 * 
 * This is a fundamental ES6 modules behavior - the exporting module can 
 * reassign its own variables, but importers cannot.
 */

import { EXPANDED_NODES_KEY, SELECTED_SELECTION_KEY } from './constants.js';

// --- Global State Variables ---
// These can be READ by other modules via: state.zfsDataCache
// They must be MODIFIED via setter functions: state.setZfsDataCache(data)
export let zfsDataCache = null;
export let currentSelection = null;
export let currentProperties = null;
export let currentPoolStatusText = null;
export let currentPoolLayout = null;
export let isAuthenticated = false;
export let currentUsername = null;

// --- Expanded Nodes State (for tree persistence) ---
export let expandedNodePaths = new Set();

// --- State Setters ---
// Use these functions to modify state from other modules
export function setZfsDataCache(data) {
    zfsDataCache = data;
}

export function setCurrentSelection(selection) {
    currentSelection = selection;
}

export function setCurrentProperties(props) {
    currentProperties = props;
}

export function setCurrentPoolStatusText(text) {
    currentPoolStatusText = text;
}

export function setCurrentPoolLayout(layout) {
    currentPoolLayout = layout;
}

export function setIsAuthenticated(authenticated) {
    isAuthenticated = authenticated;
}

export function setCurrentUsername(username) {
    currentUsername = username;
}

// --- Node Storage Key Helper ---
export function nodeStorageKey(name, objType) {
    return `${name}::${objType || ''}`;
}

// --- Expanded Nodes Persistence ---
export function initializeExpandedNodes() {
    try {
        const stored = JSON.parse(localStorage.getItem(EXPANDED_NODES_KEY) || '[]');
        if (Array.isArray(stored)) {
            const normalized = stored.map(entry => {
                entry = String(entry);
                if (entry.includes('::')) return entry;
                return nodeStorageKey(entry, '');
            });
            expandedNodePaths = new Set(normalized);
        }
    } catch (e) {
        console.warn('Failed to load expanded nodes from localStorage:', e);
        expandedNodePaths = new Set();
    }
}

export function saveExpandedNodes() {
    try {
        localStorage.setItem(EXPANDED_NODES_KEY, JSON.stringify(Array.from(expandedNodePaths)));
    } catch (e) {
        console.warn('Failed to save expanded nodes to localStorage', e);
    }
}

export function addExpandedNode(key) {
    expandedNodePaths.add(key);
    saveExpandedNodes();
}

export function removeExpandedNode(key) {
    expandedNodePaths.delete(key);
    saveExpandedNodes();
}

export function isNodeExpanded(key) {
    return expandedNodePaths.has(key);
}

// --- Selection Persistence ---
export function initializeSelection() {
    try {
        const storedSel = JSON.parse(localStorage.getItem(SELECTED_SELECTION_KEY) || 'null');
        if (storedSel && storedSel.name && storedSel.obj_type) {
            currentSelection = storedSel;
        }
    } catch (e) {
        console.warn('Failed to load selected item from localStorage:', e);
    }
}

export function saveSelectionToStorage() {
    try {
        if (currentSelection) {
            localStorage.setItem(SELECTED_SELECTION_KEY, JSON.stringify({ 
                name: currentSelection.name, 
                obj_type: currentSelection.obj_type 
            }));
        } else {
            localStorage.removeItem(SELECTED_SELECTION_KEY);
        }
    } catch (e) {
        console.warn('Failed to save selected item to localStorage:', e);
    }
}

// --- Clear All State ---
export function clearAllState() {
    zfsDataCache = null;
    currentSelection = null;
    currentProperties = null;
    currentPoolStatusText = null;
    currentPoolLayout = null;
    saveSelectionToStorage();
}

// --- Clear Current Selection Only ---
export function clearCurrentSelection() {
    currentSelection = null;
    currentProperties = null;
    currentPoolStatusText = null;
    currentPoolLayout = null;
}

// --- Initialize State on Load ---
export function initializeState() {
    initializeExpandedNodes();
    initializeSelection();
}
