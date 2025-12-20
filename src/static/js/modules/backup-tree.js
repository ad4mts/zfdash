/**
 * backup-tree.js - Unified Backup Tree View Component
 * 
 * Reusable tree view component for backup source selection.
 * Used by both "Backup to Agent" left pane and "Agent to Agent" modal.
 */

/**
 * BackupTreeView - Renders a filterable tree of pools/datasets/snapshots
 */
export class BackupTreeView {
    /**
     * @param {HTMLElement} container - Container element to render into
     * @param {Object} options - Configuration options
     * @param {Function} options.onSelect - Callback when item selected: (item) => {}
     * @param {boolean} options.showDatasets - Initially show datasets (default: false)
     */
    constructor(container, options = {}) {
        this.container = container;
        this.onSelect = options.onSelect || (() => { });
        this.showDatasets = options.showDatasets || false;
        this.filterText = '';
        this.pools = [];
        this.selection = null;
        this.expandedPools = new Set();
    }

    /**
     * Render tree from pool data
     * @param {Array} pools - Array of pool objects with children/snapshots
     */
    render(pools) {
        this.pools = pools || [];
        this._buildTree();
    }

    /**
     * Set search filter text
     * @param {string} text - Filter text
     */
    setFilter(text) {
        this.filterText = (text || '').toLowerCase().trim();
        this._buildTree();
    }

    /**
     * Toggle dataset visibility
     * @param {boolean} show - Show datasets
     */
    setShowDatasets(show) {
        this.showDatasets = show;
        this._buildTree();
    }

    /**
     * Get current selection
     * @returns {Object|null} Selected item {name, type}
     */
    getSelection() {
        return this.selection;
    }

    /**
     * Clear current selection
     */
    clearSelection() {
        this.selection = null;
        if (this.container) {
            this.container.querySelectorAll('.backup-tree-item.selected')
                .forEach(el => el.classList.remove('selected'));
        }
    }

    /**
     * Programmatically select an item by its full name (e.g. "pool/dataset@snap").
     * Expands the parent pool so the item is visible, highlights it,
     * scrolls it into view, and triggers the onSelect callback.
     * @param {string} name - Full item name (e.g. "rpool/data@mysnapshot")
     * @returns {boolean} true if item was found and selected
     */
    selectByName(name) {
        if (!name) return false;

        // Determine the pool name (first path component before / or @) and expand it
        const poolName = name.split('/')[0].split('@')[0];
        if (!this.expandedPools.has(poolName)) {
            const poolItem = this.container.querySelector(`.backup-tree-item.pool[data-name="${CSS.escape(poolName)}"]`);
            if (poolItem) {
                this.expandedPools.add(poolName);
                const childrenDiv = poolItem.nextElementSibling;
                const toggleIcon = poolItem.querySelector('.tree-toggle');
                if (childrenDiv) childrenDiv.style.display = 'block';
                if (toggleIcon) {
                    toggleIcon.classList.remove('bi-caret-right-fill');
                    toggleIcon.classList.add('bi-caret-down-fill');
                }
            }
        }

        // Find the target item by data-name
        const selector = `.backup-tree-item[data-name="${CSS.escape(name)}"]`;
        const item = this.container.querySelector(selector);
        if (!item) return false;

        // Clear previous selection
        this.clearSelection();

        // Select it
        item.classList.add('selected');
        this.selection = {
            name: item.dataset.name,
            type: item.dataset.type
        };

        // Scroll into view
        item.scrollIntoView({ behavior: 'smooth', block: 'center' });

        // Trigger callback
        this.onSelect(this.selection);
        return true;
    }

    /**
     * Build and render the tree HTML
     * @private
     */
    _buildTree() {
        if (!this.container) return;

        if (!this.pools || this.pools.length === 0) {
            this.container.innerHTML = `
                <div class="text-center text-muted py-4">
                    <i class="bi bi-inbox display-4"></i>
                    <p class="mt-2 mb-0 small">No pools found</p>
                </div>
            `;
            return;
        }

        let html = '';
        this.pools.forEach(pool => {
            html += this._renderPool(pool);
        });

        this.container.innerHTML = html || `
            <div class="text-center text-muted py-4">
                <i class="bi bi-search display-4"></i>
                <p class="mt-2 mb-0 small">No matches found</p>
            </div>
        `;

        this._attachEventListeners();
        this._restoreSelection();
    }

    /**
     * Render a pool and its children
     * @private
     */
    _renderPool(pool) {
        const poolName = pool.name || '';
        const isExpanded = this.expandedPools.has(poolName);
        const hasChildren = this._hasVisibleChildren(pool);

        // Check if pool matches filter (or any children do)
        if (this.filterText && !this._matchesFilter(pool)) {
            return '';
        }

        const toggleIcon = hasChildren
            ? (isExpanded ? 'bi-caret-down-fill' : 'bi-caret-right-fill')
            : 'bi-dot';

        let html = `
            <div class="backup-tree-item pool" 
                 data-name="${poolName}" data-type="pool" data-expandable="true">
                <i class="bi ${toggleIcon} tree-toggle me-1"></i>
                <i class="bi bi-database text-warning me-1"></i>
                <span>${poolName}</span>
            </div>
        `;

        // Children container
        if (hasChildren) {
            html += `<div class="backup-tree-children" style="display: ${isExpanded ? 'block' : 'none'};">`;
            html += this._renderChildren(pool, 1);
            html += `</div>`;
        }

        return html;
    }

    /**
     * Render children (datasets and snapshots) of an item
     * @private
     */
    _renderChildren(parent, indent) {
        let html = '';
        const parentName = parent.name || '';

        // Render datasets (if enabled)
        if (this.showDatasets && parent.children) {
            parent.children.forEach(child => {
                html += this._renderDataset(child, indent);
            });
        }

        // Render snapshots
        if (parent.snapshots) {
            parent.snapshots.forEach(snap => {
                html += this._renderSnapshot(snap, parentName, indent);
            });
        }

        // If showing datasets is off, recurse into children to find snapshots
        if (!this.showDatasets && parent.children) {
            parent.children.forEach(child => {
                html += this._renderSnapshotsOnly(child, indent);
            });
        }

        return html;
    }

    /**
     * Render a dataset item
     * @private
     */
    _renderDataset(dataset, indent) {
        const name = dataset.name || '';
        const displayName = name.includes('/') ? name.split('/').pop() : name;
        const paddingLeft = 12 + indent * 16;

        // Check filter
        if (this.filterText && !this._itemMatchesFilter(name)) {
            return '';
        }

        let html = `
            <div class="backup-tree-item dataset" 
                 data-name="${name}" data-type="dataset"
                 style="padding-left: ${paddingLeft}px;">
                <i class="bi bi-folder text-info me-1"></i>
                <span>${displayName}</span>
            </div>
        `;

        // Render this dataset's snapshots
        if (dataset.snapshots) {
            dataset.snapshots.forEach(snap => {
                html += this._renderSnapshot(snap, name, indent + 1);
            });
        }

        // Recurse into child datasets
        if (dataset.children) {
            dataset.children.forEach(child => {
                html += this._renderDataset(child, indent + 1);
            });
        }

        return html;
    }

    /**
     * Render snapshots only (when datasets are hidden), recursing into children
     * @private
     */
    _renderSnapshotsOnly(dataset, indent) {
        let html = '';
        const name = dataset.name || '';

        // Render this dataset's snapshots - pass showParent=true since datasets are hidden
        if (dataset.snapshots) {
            dataset.snapshots.forEach(snap => {
                html += this._renderSnapshot(snap, name, indent, true);
            });
        }

        // Recurse into children
        if (dataset.children) {
            dataset.children.forEach(child => {
                html += this._renderSnapshotsOnly(child, indent);
            });
        }

        return html;
    }

    /**
     * Render a snapshot item
     * @param {Object} snap - Snapshot object
     * @param {string} parentName - Parent dataset/pool name
     * @param {number} indent - Indentation level
     * @param {boolean} showParent - Whether to show parent name (when datasets hidden)
     * @private
     */
    _renderSnapshot(snap, parentName, indent, showParent = false) {
        const snapName = snap.name || '';
        const fullName = snap.properties?.full_snapshot_name || `${parentName}@${snapName}`;

        // When showing parent, strip the pool name since it's already visible
        // e.g., "pool/data/child@snap" -> "data/child@snap"
        let displayName;
        if (showParent) {
            // Remove pool prefix if present (everything before first /)
            const pathWithoutPool = parentName.includes('/')
                ? parentName.substring(parentName.indexOf('/') + 1)
                : parentName;
            displayName = `${pathWithoutPool}@${snapName}`;
        } else {
            displayName = `@${snapName}`;
        }

        const paddingLeft = 12 + indent * 16;

        // Check filter
        if (this.filterText && !this._itemMatchesFilter(fullName)) {
            return '';
        }

        return `
            <div class="backup-tree-item snapshot" 
                 data-name="${fullName}" data-type="snapshot"
                 style="padding-left: ${paddingLeft}px;"
                 title="${fullName}">
                <i class="bi bi-camera text-success me-1"></i>
                <span>${displayName}</span>
            </div>
        `;
    }

    /**
     * Check if pool or any of its descendants match filter
     * @private
     */
    _matchesFilter(pool) {
        if (!this.filterText) return true;

        if (this._itemMatchesFilter(pool.name)) return true;

        // Check children recursively
        if (pool.children) {
            for (const child of pool.children) {
                if (this._matchesFilter(child)) return true;
            }
        }

        // Check snapshots
        if (pool.snapshots) {
            for (const snap of pool.snapshots) {
                const fullName = snap.properties?.full_snapshot_name || `${pool.name}@${snap.name}`;
                if (this._itemMatchesFilter(fullName)) return true;
            }
        }

        return false;
    }

    /**
     * Check if item name matches filter
     * @private
     */
    _itemMatchesFilter(name) {
        if (!this.filterText) return true;
        return (name || '').toLowerCase().includes(this.filterText);
    }

    /**
     * Check if pool has visible children (considering showDatasets setting)
     * @private
     */
    _hasVisibleChildren(pool) {
        // Always check for snapshots
        if (pool.snapshots && pool.snapshots.length > 0) return true;

        // Check datasets if visible
        if (this.showDatasets && pool.children && pool.children.length > 0) return true;

        // Check nested snapshots
        if (pool.children) {
            for (const child of pool.children) {
                if (this._hasNestedSnapshots(child)) return true;
            }
        }

        return false;
    }

    /**
     * Check if dataset has any snapshots (including nested)
     * @private
     */
    _hasNestedSnapshots(dataset) {
        if (dataset.snapshots && dataset.snapshots.length > 0) return true;
        if (dataset.children) {
            for (const child of dataset.children) {
                if (this._hasNestedSnapshots(child)) return true;
            }
        }
        return false;
    }

    /**
     * Attach event listeners to tree items
     * @private
     */
    _attachEventListeners() {
        // Pool expand/collapse
        this.container.querySelectorAll('.backup-tree-item.pool').forEach(item => {
            item.addEventListener('click', (e) => this._handlePoolClick(e, item));
        });

        // Dataset/Snapshot selection
        this.container.querySelectorAll('.backup-tree-item.dataset, .backup-tree-item.snapshot').forEach(item => {
            item.addEventListener('click', (e) => this._handleItemClick(e, item));
        });
    }

    /**
     * Handle pool click (expand/collapse)
     * @private
     */
    _handlePoolClick(e, item) {
        e.stopPropagation();
        const poolName = item.dataset.name;
        const childrenDiv = item.nextElementSibling;
        const toggleIcon = item.querySelector('.tree-toggle');

        if (this.expandedPools.has(poolName)) {
            this.expandedPools.delete(poolName);
            if (childrenDiv) childrenDiv.style.display = 'none';
            if (toggleIcon) {
                toggleIcon.classList.remove('bi-caret-down-fill');
                toggleIcon.classList.add('bi-caret-right-fill');
            }
        } else {
            this.expandedPools.add(poolName);
            if (childrenDiv) childrenDiv.style.display = 'block';
            if (toggleIcon) {
                toggleIcon.classList.remove('bi-caret-right-fill');
                toggleIcon.classList.add('bi-caret-down-fill');
            }
        }
    }

    /**
     * Handle dataset/snapshot click (selection)
     * @private
     */
    _handleItemClick(e, item) {
        e.stopPropagation();

        // Clear previous selection
        this.container.querySelectorAll('.backup-tree-item.selected')
            .forEach(el => el.classList.remove('selected'));

        // Select this item
        item.classList.add('selected');

        this.selection = {
            name: item.dataset.name,
            type: item.dataset.type
        };

        // Call onSelect callback
        this.onSelect(this.selection);
    }

    /**
     * Restore selection after re-render
     * @private
     */
    _restoreSelection() {
        if (!this.selection) return;

        const selector = `.backup-tree-item[data-name="${CSS.escape(this.selection.name)}"][data-type="${this.selection.type}"]`;
        const item = this.container.querySelector(selector);
        if (item) {
            item.classList.add('selected');
        }
    }
}
