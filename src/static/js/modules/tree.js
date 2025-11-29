/**
 * tree.js - ZFS Tree View Module
 * 
 * Handles rendering and interaction with the ZFS pool/dataset tree view.
 */

import * as state from './state.js';
import dom from './dom-elements.js';
import { showErrorAlert, setDetailsVisible } from './ui.js';
import { findObjectByPath } from './utils.js';
import { renderDashboard } from './dashboard.js';

// Store reference to renderDetails and updateActionStates functions
let _renderDetailsRef = null;
let _updateActionStatesRef = null;
let _clearSelectionRef = null;

/**
 * Set callbacks needed by tree module
 * @param {Function} renderDetailsFn - renderDetails function
 * @param {Function} updateActionStatesFn - updateActionStates function
 * @param {Function} clearSelectionFn - clearSelection function
 */
export function setTreeCallbacks(renderDetailsFn, updateActionStatesFn, clearSelectionFn) {
    _renderDetailsRef = renderDetailsFn;
    _updateActionStatesRef = updateActionStatesFn;
    _clearSelectionRef = clearSelectionFn;
}

/**
 * Build HTML for tree view recursively
 * @param {Array} items - Array of ZFS objects
 * @param {number} level - Current nesting level
 * @returns {string} - HTML string
 */
export function buildTreeHtml(items, level = 0) {
    if (!items || items.length === 0) {
        return '<div class="text-muted ps-3">No pools found.</div>';
    }
    
    let html = '<ul class="list-unstyled mb-0">';
    items.forEach(item => {
        const indent = level * 20;
        const isPool = item.obj_type === 'pool';
        const isDataset = item.obj_type === 'dataset';
        const isVolume = item.obj_type === 'volume';
        const hasChildren = item.children && item.children.length > 0;

        let iconClass = 'bi-hdd';
        if (isDataset) iconClass = 'bi-folder';
        if (isVolume) iconClass = 'bi-hdd-stack';

        let healthClass = '';
        let healthIndicator = '';
        if (isPool) {
            const health = item.health?.toUpperCase();
            if (health === 'ONLINE') healthClass = 'text-success';
            else if (health === 'DEGRADED') healthClass = 'text-warning';
            else if (health === 'FAULTED' || health === 'UNAVAIL' || health === 'REMOVED') healthClass = 'text-danger';
            else if (health === 'OFFLINE') healthClass = 'text-muted';
            if (health && health !== 'ONLINE') {
                healthIndicator = `<span class="badge bg-${healthClass.replace('text-','')} ms-1">${health}</span>`;
            }
        }

        const nodeKey = state.nodeStorageKey(item.name, item.obj_type);
        const isExpanded = state.isNodeExpanded(nodeKey);
        
        let toggleHtml = '';
        if (hasChildren) {
            toggleHtml = `<i class="bi ${isExpanded ? 'bi-caret-down-fill' : 'bi-caret-right-fill'} me-1 tree-toggle"></i>`;
        } else {
            toggleHtml = `<i class="bi bi-dot me-1 text-muted"></i>`;
        }

        const displayName = isPool ? item.name : item.name.split('/').pop();
        const isSelected = state.currentSelection?.name === item.name && state.currentSelection?.obj_type === item.obj_type;

        html += `
        <li style="padding-left: ${indent}px;">
            <div class="tree-item ${isSelected ? 'selected' : ''}"
                data-path="${item.name}"
                data-type="${item.obj_type}"
                title="${item.name} (${item.obj_type})">
                ${toggleHtml}<i class="bi ${iconClass} me-1 ${healthClass}"></i>
                <span class="tree-item-name">${displayName}</span>
                ${healthIndicator}
                ${item.is_encrypted ? '<i class="bi bi-lock-fill text-warning ms-1" title="Encrypted"></i>' : ''}
                ${item.is_mounted ? '<i class="bi bi-cloud-arrow-up-fill text-info ms-1" title="Mounted"></i>' : ''}
            </div>
            ${hasChildren ? `<div class="tree-children" style="display: ${isExpanded ? 'block' : 'none'};">${buildTreeHtml(item.children, level + 1)}</div>` : ''}
        </li>
        `;
    });
    html += '</ul>';
    return html;
}

/**
 * Render the ZFS tree view
 * @param {Array} data - ZFS data to render
 */
export function renderTree(data) {
    state.setZfsDataCache(data);
    const treeHtml = buildTreeHtml(data);
    
    if (dom.zfsTree) {
        dom.zfsTree.innerHTML = treeHtml;
        dom.zfsTree.querySelectorAll('.tree-item.selected').forEach(el => el.classList.remove('selected'));
    }

    if (!treeHtml || treeHtml.includes("No pools found")) {
        console.log("renderTree: No pools found or empty data.");
        if (_clearSelectionRef) _clearSelectionRef();
        if (_updateActionStatesRef) _updateActionStatesRef();
        return;
    }

    // Add event listeners
    try {
        dom.zfsTree.querySelectorAll('.tree-item').forEach(item => {
            item.addEventListener('click', handleTreeItemClick);
        });
        dom.zfsTree.querySelectorAll('.tree-toggle').forEach(toggle => {
            toggle.addEventListener('click', handleTreeToggle);
        });
    } catch (e) {
        console.error("Error adding event listeners to tree:", e);
        dom.zfsTree.innerHTML = '<div class="alert alert-warning">Error initializing tree view.</div>';
        if (_clearSelectionRef) _clearSelectionRef();
        if (_updateActionStatesRef) _updateActionStatesRef();
        return;
    }

    // Restore selection if possible
    let selectionRestored = false;
    if (state.currentSelection) {
        const escapedPath = CSS.escape(state.currentSelection.name);
        const selector = `.tree-item[data-path="${escapedPath}"][data-type="${state.currentSelection.obj_type}"]`;
        const selectedElement = dom.zfsTree.querySelector(selector);

        if (selectedElement) {
            try {
                selectedElement.classList.add('selected');
                // Ensure parents are expanded
                let parentLi = selectedElement.closest('li');
                while (parentLi) {
                    const childrenDiv = parentLi.querySelector(':scope > .tree-children');
                    const toggleIcon = parentLi.querySelector(':scope > .tree-item > .tree-toggle');
                    if (childrenDiv && toggleIcon && childrenDiv.style.display !== 'block') {
                        childrenDiv.style.display = 'block';
                        toggleIcon.classList.replace('bi-caret-right-fill', 'bi-caret-down-fill');
                        
                        // Persist expanded state for parent
                        try {
                            const parentItemDiv = parentLi.querySelector(':scope > .tree-item');
                            const parentPath = parentItemDiv?.dataset?.path;
                            const parentType = parentItemDiv?.dataset?.type;
                            if (parentPath) {
                                const parentKey = state.nodeStorageKey(parentPath, parentType);
                                state.addExpandedNode(parentKey);
                            }
                        } catch (e) {
                            console.warn('Failed to persist expanded parent:', e);
                        }
                    }
                    const parentUl = parentLi.parentElement;
                    parentLi = parentUl ? parentUl.closest('li') : null;
                }
                selectionRestored = true;
            } catch (e) {
                console.error("Error expanding parents for selected item:", e);
                selectionRestored = false;
            }
        } else {
            console.log(`renderTree: Could not find element for previous selection '${state.currentSelection.name}' with type '${state.currentSelection.obj_type}'`);
        }
    }

    if (!selectionRestored && _clearSelectionRef) {
        _clearSelectionRef();
    }
    
    if (_updateActionStatesRef) {
        _updateActionStatesRef();
    }
}

/**
 * Handle tree toggle click (expand/collapse)
 * @param {Event} event - Click event
 */
export function handleTreeToggle(event) {
    event.stopPropagation();
    const icon = event.target;
    const li = icon.closest('li');
    const childrenDiv = li.querySelector(':scope > .tree-children');
    
    if (childrenDiv) {
        const isVisible = childrenDiv.style.display === 'block';
        childrenDiv.style.display = isVisible ? 'none' : 'block';
        icon.classList.toggle('bi-caret-right-fill', isVisible);
        icon.classList.toggle('bi-caret-down-fill', !isVisible);
        
        // Update expanded state
        const treeItemDiv = li.querySelector(':scope > .tree-item');
        const itemPath = treeItemDiv?.dataset?.path;
        const itemType = treeItemDiv?.dataset?.type;
        if (itemPath) {
            const nodeKey = state.nodeStorageKey(itemPath, itemType);
            if (!isVisible) {
                state.addExpandedNode(nodeKey);
            } else {
                state.removeExpandedNode(nodeKey);
            }
        }
    }
}

/**
 * Handle tree item click (selection)
 * @param {Event} event - Click event
 */
export async function handleTreeItemClick(event) {
    const targetItem = event.currentTarget;
    const path = targetItem.dataset.path;
    const type = targetItem.dataset.type;
    
    if (!path || !type) {
        console.warn("Clicked tree item missing data-path or data-type attribute.");
        return;
    }

    // Remove selection from any previously selected items
    dom.zfsTree.querySelectorAll('.tree-item.selected').forEach(el => el.classList.remove('selected'));

    // Add selection to clicked item
    targetItem.classList.add('selected');
    
    // Show the main tab content area
    setDetailsVisible(true);

    // Find the corresponding object in the cache
    const selection = findObjectByPath(path, type);
    state.setCurrentSelection(selection);

    if (selection) {
        try {
            if (_renderDetailsRef) {
                await _renderDetailsRef(selection);
            }
            if (_updateActionStatesRef) {
                _updateActionStatesRef();
            }
            state.saveSelectionToStorage();
        } catch (error) {
            console.error(`Error rendering details on click for ${path} (Type: ${type}):`, error);
            showErrorAlert("Detail Render Error", `Could not render details for ${path}.\n\nError: ${error.message}`);
            clearSelection();
            if (_updateActionStatesRef) _updateActionStatesRef();
        }
    } else {
        console.warn("Could not find object for path:", path, "and type:", type);
        clearSelection();
        if (_updateActionStatesRef) _updateActionStatesRef();
    }
}

/**
 * Clear the current selection
 */
export function clearSelection() {
    state.clearCurrentSelection();
    
    if (dom.zfsTree) {
        dom.zfsTree.querySelectorAll('.tree-item.selected').forEach(el => el.classList.remove('selected'));
    }
    
    state.saveSelectionToStorage();
    
    // Clear dashboard
    renderDashboard(null);
    
    // Hide the tab content area
    setDetailsVisible(false);
    
    // Reset the title
    if (dom.detailsTitle) {
        dom.detailsTitle.textContent = 'Details';
    }
    
    // Update Pool Edit actions when selection is cleared
    // NOTE: updateActionStates() will be called by the function *triggering* the clear (e.g., fetch, click failure)
}
