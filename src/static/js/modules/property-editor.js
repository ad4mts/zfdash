/**
 * property-editor.js - Property Editing Module
 * 
 * Handles rendering and editing of ZFS properties.
 */

import * as state from './state.js';
import dom from './dom-elements.js';
import { formatSize, validateSizeOrNone } from './utils.js';
import { executeActionWithRefresh } from './api.js';
import { showModal, hideModal, showErrorAlert } from './ui.js';
import { 
    EDITABLE_PROPERTIES_WEB, 
    POOL_LEVEL_PROPERTIES, 
    AUTO_SNAPSHOT_PROPS, 
    AUTO_SNAPSHOT_SORT_ORDER_WEB 
} from './constants.js';

/**
 * Render properties table
 * @param {object|null} props - Properties object
 * @param {boolean} isLoading - Whether loading state should be shown
 */
export function renderProperties(props, isLoading = false) {
    if (!dom.propertiesTableBody) return;
    
    dom.propertiesTableBody.innerHTML = '';
    
    if (isLoading) {
        dom.propertiesTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-muted"><span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading properties...</td></tr>`;
        return;
    }
    
    if (!props) {
        dom.propertiesTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-danger">Failed to load properties or none available.</td></tr>`;
        return;
    }
    
    if (Object.keys(props).length === 0 && !Object.keys(EDITABLE_PROPERTIES_WEB || {}).length > 0) {
        dom.propertiesTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">No properties available for this item.</td></tr>`;
        return;
    }

    // Get all property keys returned by the backend
    const fetchedKeys = Object.keys(props);
    
    // Separate editable and non-editable properties
    const editableKeys = [];
    const nonEditableKeys = [];
    
    fetchedKeys.forEach(key => {
        const editInfo = EDITABLE_PROPERTIES_WEB?.[key];
        let isEditable = false;
        if (editInfo) {
            const isReadOnlyForObject = editInfo.readOnlyFunc && editInfo.readOnlyFunc(state.currentSelection);
            isEditable = !isReadOnlyForObject;
        }
        
        if (isEditable) {
            editableKeys.push(key);
        } else {
            nonEditableKeys.push(key);
        }
    });

    // Add missing editable properties
    Object.keys(EDITABLE_PROPERTIES_WEB || {}).forEach(editableKey => {
        if (!props.hasOwnProperty(editableKey)) {
            const editInfo = EDITABLE_PROPERTIES_WEB[editableKey];
            const isReadOnlyForObject = editInfo.readOnlyFunc && editInfo.readOnlyFunc(state.currentSelection);
            if (!isReadOnlyForObject) {
                if (!editableKeys.includes(editableKey)) { 
                    editableKeys.push(editableKey);
                }
            } else {
                if (!nonEditableKeys.includes(editableKey) && !editableKeys.includes(editableKey)) {
                    nonEditableKeys.push(editableKey);
                }
            }
        }
    });

    // Sort editable keys: Auto-snapshot first by custom order, then others alphabetically
    const autoSnapshotEditable = editableKeys.filter(k => AUTO_SNAPSHOT_PROPS.includes(k)).sort((a, b) => {
        const indexA = AUTO_SNAPSHOT_SORT_ORDER_WEB.indexOf(a);
        const indexB = AUTO_SNAPSHOT_SORT_ORDER_WEB.indexOf(b);
        if (indexA === -1 && indexB === -1) return a.localeCompare(b);
        if (indexA === -1) return 1;
        if (indexB === -1) return -1;
        return indexA - indexB;
    });
    const otherEditable = editableKeys.filter(k => !AUTO_SNAPSHOT_PROPS.includes(k)).sort();
    const sortedEditableKeys = [...autoSnapshotEditable, ...otherEditable];

    // Sort non-editable keys alphabetically
    nonEditableKeys.sort();
    
    // Render sections
    if (sortedEditableKeys.length > 0) {
        const headerRow = dom.propertiesTableBody.insertRow();
        headerRow.className = "table-primary table-group-header";
        headerRow.innerHTML = `<td colspan="4"><strong>Editable Properties</strong></td>`;
        
        renderPropertyGroup(sortedEditableKeys, props, true);
        
        if (nonEditableKeys.length > 0) {
            const spacerRow = dom.propertiesTableBody.insertRow();
            spacerRow.className = "table-light";
            spacerRow.style.height = "8px";
            spacerRow.innerHTML = `<td colspan="4"></td>`;
        }
    }
    
    if (nonEditableKeys.length > 0) {
        const nonEditableHeader = dom.propertiesTableBody.insertRow();
        nonEditableHeader.className = "table-secondary table-group-header";
        nonEditableHeader.innerHTML = `<td colspan="4"><strong>${sortedEditableKeys.length > 0 ? 'Other' : 'All'} Properties</strong></td>`;
        
        renderPropertyGroup(nonEditableKeys, props, false);
    }

    if (sortedEditableKeys.length === 0 && nonEditableKeys.length === 0) {
        dom.propertiesTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">No properties available for this item.</td></tr>`;
    }
}

/**
 * Render a group of properties
 * @param {Array} keys - Property keys to render
 * @param {object} props - All properties
 * @param {boolean} isEditable - Whether properties in this group are editable
 */
function renderPropertyGroup(keys, props, isEditable) {
    const datasetName = state.currentSelection?.name;

    keys.forEach(key => {
        const propData = props[key];
        const value = propData?.value ?? '-';
        const source = propData?.source ?? (datasetName?.includes('/') ? 'inherited' : 'default');
        const isInherited = source && !['-', 'local', 'default', 'received'].includes(source);
        const displayValue = (propData === undefined && isEditable) ? '-' : formatSize(value);
        const displaySource = (propData === undefined && isEditable) ? (datasetName?.includes('/') ? 'inherited' : 'default') : (source === '-' ? 'local/default' : source);
        
        const row = dom.propertiesTableBody.insertRow();
        
        if (EDITABLE_PROPERTIES_WEB?.[key]) { 
            row.className = "editable-property-config";
        }
        
        if (key === "com.sun:auto-snapshot") {
            row.classList.add("master-snapshot-switch");
        }

        row.innerHTML = `
            <td><span title="Internal: ${key}">${EDITABLE_PROPERTIES_WEB?.[key]?.displayName || key}</span></td>
            <td class="${isInherited ? 'text-muted' : ''}" title="Raw: ${value}">${displayValue}</td>
            <td>${displaySource}</td>
            <td class="text-end"></td>
        `;
        const actionCell = row.cells[3];

        // Add Edit button if editable
        if (isEditable) {
            const editBtn = document.createElement('button');
            editBtn.className = 'btn properties-table-btn edit-btn me-1';
            editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
            editBtn.title = `Edit ${key}`;
            editBtn.onclick = () => handleEditProperty(key, value, EDITABLE_PROPERTIES_WEB[key]); 
            actionCell.appendChild(editBtn);
        }

        // Allow inherit if source is 'local' or 'received'
        const isPoolProperty = state.currentSelection?.obj_type === 'pool' && POOL_LEVEL_PROPERTIES.has(key);
        if (propData && (source === 'local' || source === 'received') && !isPoolProperty) {
            const inheritBtn = document.createElement('button');
            inheritBtn.className = 'btn properties-table-btn inherit-btn';
            inheritBtn.innerHTML = '<i class="bi bi-arrow-down-left-circle"></i>';
            inheritBtn.title = `Inherit ${key}`;
            inheritBtn.onclick = () => handleInheritProperty(key);
            actionCell.appendChild(inheritBtn);
        }
    });
}

/**
 * Handle edit property action
 * @param {string} propName - Property name
 * @param {*} currentValue - Current value
 * @param {object} editInfo - Edit configuration
 */
export function handleEditProperty(propName, currentValue, editInfo) {
    if (!state.currentSelection) return;

    let inputHtml = '';
    if (editInfo.editor === 'lineedit') {
        inputHtml = `<input type="text" id="prop-edit-input" class="form-control" value="${currentValue}" placeholder="${editInfo.placeholder || ''}">`;
    } else if (editInfo.editor === 'combobox' && editInfo.options) {
        if (!Array.isArray(editInfo.options)) {
            console.error(`Configuration error: options for property '${propName}' is not an array.`, editInfo.options);
            showErrorAlert("Internal Error", `Cannot create editor for '${propName}' due to invalid configuration.`);
            return;
        }
        
        inputHtml = `<select id="prop-edit-input" class="form-select">`;
        editInfo.options.forEach(opt => {
            inputHtml += `<option value="${opt}" ${opt === currentValue ? 'selected' : ''}>${opt}</option>`;
        });
        inputHtml += `</select>`;
    } else {
        showErrorAlert("Edit Error", `Unsupported editor type for property '${propName}'.`);
        return;
    }

    showModal(`Edit Property: ${editInfo.displayName}`,
        `<p>Set '${editInfo.displayName}' for '${state.currentSelection.name}':</p>${inputHtml}`,
        () => {
            const inputElement = document.getElementById('prop-edit-input');
            const newValue = inputElement.value.trim();

            // Handle inherit for properties with '-' option
            if (editInfo.editor === 'combobox' && newValue === '-') {
                hideModal();
                setTimeout(() => handleInheritProperty(propName), 100); 
                return;
            }

            if (newValue === currentValue) {
                hideModal();
                return;
            }

            // Validation
            if (editInfo.validation === 'sizeOrNone' && !validateSizeOrNone(newValue)) {
                alert(`Invalid format for ${editInfo.displayName}. Use numbers, units (K, M, G, T...) or 'none'.`);
                inputElement.focus();
                return;
            }

            hideModal();
            
            const isPoolProperty = state.currentSelection.obj_type === 'pool' && POOL_LEVEL_PROPERTIES.has(propName);
            const setAction = isPoolProperty ? 'set_pool_property' : 'set_dataset_property';
            
            executeActionWithRefresh(
                setAction,
                [state.currentSelection.name, propName, newValue],
                {},
                `Property '${propName}' set successfully.`
            );
        }
    );
}

/**
 * Handle inherit property action
 * @param {string} propName - Property name
 */
export function handleInheritProperty(propName) {
    if (!state.currentSelection) return;
    
    const isPoolProperty = state.currentSelection.obj_type === 'pool' && POOL_LEVEL_PROPERTIES.has(propName);
    if (isPoolProperty) {
        showErrorAlert("Cannot Inherit", `Pool property '${propName}' cannot be inherited. Pool properties can only be set to specific values.`);
        return;
    }
    
    executeActionWithRefresh(
        'inherit_dataset_property',
        [state.currentSelection.name, propName],
        {},
        `Property '${propName}' set to inherit.`,
        true,
        `Are you sure you want to reset property '${propName}' for '${state.currentSelection.name}' to its inherited value?`
    );
}
