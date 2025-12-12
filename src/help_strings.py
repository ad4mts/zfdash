# --- START OF FILE src/help_strings.py ---
"""
Centralized help content for ZfDash.
Used by both Desktop GUI and Web UI for tooltips, warnings, and guidance.
"""

HELP = {
    # === VDEV Types ===
    "vdev_types": {
        "disk": {
            "name": "Single Disk (Stripe)",
            "short": "No redundancy. Data loss if disk fails.",
            "when_to_use": "Testing only. Not recommended for important data.",
            "min_devices": 1
        },
        "mirror": {
            "name": "Mirror",
            "short": "Data is copied to all disks. Can survive disk failures.",
            "when_to_use": "Best balance of performance and safety for most users.",
            "min_devices": 2,
            "tip": "Recommended for most home users."
        },
        "raidz1": {
            "name": "RAID-Z1",
            "short": "Single parity. Can survive 1 disk failure.",
            "when_to_use": "Good for 3-4 disks. Balance of space and safety.",
            "min_devices": 3
        },
        "raidz2": {
            "name": "RAID-Z2",
            "short": "Double parity. Can survive 2 disk failures.",
            "when_to_use": "Recommended for 5+ disks or larger drives (4TB+).",
            "min_devices": 4
        },
        "raidz3": {
            "name": "RAID-Z3",
            "short": "Triple parity. Can survive 3 disk failures.",
            "when_to_use": "For very large arrays (8+ disks) with large drives.",
            "min_devices": 5
        },
        "log": {
            "name": "Log (SLOG)",
            "short": "Separate Intent Log for synchronous writes.",
            "when_to_use": "NFS/iSCSI servers, databases with sync=always.",
            "warning": "Use enterprise SSDs with power-loss protection.",
            "min_devices": 1
        },
        "cache": {
            "name": "Cache (L2ARC)",
            "short": "Read cache on fast storage (SSD).",
            "when_to_use": "When working set > RAM and random reads are common.",
            "tip": "Uses RAM for indexing. ~70 bytes RAM per block cached.",
            "min_devices": 1
        },
        "spare": {
            "name": "Hot Spare",
            "short": "Standby disk for automatic replacement.",
            "when_to_use": "Large arrays where quick recovery is critical.",
            "min_devices": 1
        },
        "special": {
            "name": "Special (Metadata) - DANGEROUS",
            "short": "Stores metadata and small files on fast storage.",
            "when_to_use": "Hybrid HDD+SSD pools for better performance.",
            "warning": "⚠️ CRITICAL: Loss of this VDEV = TOTAL POOL LOSS! Use 'Special Mirror' instead for redundancy!",
            "recommended_alternative": "special mirror",
            "min_devices": 1
        },
        "special mirror": {
            "name": "Special Mirror (Recommended)",
            "short": "Mirrored metadata storage on fast drives.",
            "when_to_use": "Production hybrid pools. Requires 2+ SSDs.",
            "tip": "✓ Safe choice for Fusion Pools / Metadata VDEVs.",
            "min_devices": 2
        },
        "dedup": {
            "name": "Dedup (DDT Storage) - DANGEROUS",
            "short": "Dedicated storage for deduplication tables.",
            "when_to_use": "When using dedup and want DDT on separate fast storage.",
            "warning": "⚠️ CRITICAL: Loss of this VDEV = TOTAL POOL LOSS! Use 'Dedup Mirror' instead!",
            "recommended_alternative": "dedup mirror",
            "min_devices": 1
        },
        "dedup mirror": {
            "name": "Dedup Mirror (Recommended)",
            "short": "Mirrored dedup table storage.",
            "when_to_use": "Production pools with deduplication enabled.",
            "tip": "✓ Safe choice for dedup-enabled pools.",
            "min_devices": 2
        }
    },

    # === Empty State Messages ===
    "empty_states": {
        "create_pool_vdev_tree": {
            "title": "No VDEVs configured yet",
            "message": "Click 'Add VDEV' to start building your pool layout.",
            "steps": [
                "Choose a VDEV type from the dropdown (e.g., Mirror, RAID-Z1)",
                "Click 'Add VDEV' to create it",
                "Select devices from the left panel",
                "Click the right arrow (→) to add them to the selected VDEV",
                "Click the trash icon (🗑) on a VDEV to remove it",
                "Repeat for additional VDEVs if needed"
            ]
        },
        "add_vdev_modal": {
            "title": "Add VDEVs to expand your pool",
            "message": "Select a VDEV type and add devices to it.",
            "steps": [
                "Choose a VDEV type from the dropdown (e.g., Mirror, Cache)",
                "Click 'Add VDEV' to create it",
                "Select devices from the available list",
                "Click the right arrow (→) to add them to the selected VDEV",
                "Click the trash icon (🗑) on a VDEV to remove it",
                "Click 'OK' when ready to add VDEVs to the pool"
            ]
        },
        "no_pools": {
            "title": "No ZFS pools found",
            "message": "Create a new pool or import an existing one.",
            "actions": ["Create Pool", "Import Pool"]
        },
        "no_datasets": {
            "title": "No datasets in this pool",
            "message": "This pool has no child datasets yet. Create one to organize your data."
        }
    },

    # === Dangerous Actions ===
    "warnings": {
        "destroy_pool": {
            "title": "Destroy Pool",
            "message": "This will PERMANENTLY DELETE all data in the pool!",
            "confirm_text": "Type the pool name to confirm:"
        },
        "destroy_dataset": {
            "title": "Destroy Dataset",
            "message": "This will delete the dataset and all its snapshots.",
            "confirm_text": "Type 'destroy' to confirm:"
        },
        "force_create": {
            "title": "Force Option Enabled",
            "message": "Using -f may override safety checks. Use with caution."
        },
        "single_special_vdev": {
            "title": "No Redundancy!",
            "message": "A single Special VDEV has no redundancy. If it fails, you lose the ENTIRE pool!"
        },
        "single_dedup_vdev": {
            "title": "No Redundancy!",
            "message": "A single Dedup VDEV has no redundancy. If it fails, you lose the ENTIRE pool!"
        }
    },

    # === Tooltips for UI Elements ===
    "tooltips": {
        "pool_name": "Pool names must start with a letter. Allowed: A-Z, a-z, 0-9, _, -, .",
        "force_checkbox": "Override safety checks (e.g., different disk sizes). Use carefully.",
        "show_all_devices": "Show all block devices including partitions and potentially unsafe disks.",
        "encryption": "Enable encryption for this pool/dataset. Cannot be disabled later.",
        "compression": "LZ4 compression is recommended. Provides good speed-to-compression ratio.",
        "dedup": "Deduplication requires significant RAM (~5GB per 1TB of unique data). Use carefully."
    },

    # === General Tips ===
    "tips": {
        "first_pool": "Tip: For your first pool, try a 'Mirror' with 2 disks for safety and simplicity.",
        "encryption": "Tip: Enable encryption at pool creation for full protection. It cannot be added later.",
        "compression": "Tip: LZ4 compression is recommended. It's fast and effective for most workloads.",
        "recordsize": "Tip: Default recordsize (128K) is good for general use. Databases may benefit from smaller sizes.",
        "fusion_pool": "Tip: Fusion Pool = HDD data VDEVs + SSD Special Mirror. Great for mixed workloads."
    },

    # === Quick Reference ===
    "quick_reference": {
        "vdev_types_summary": {
            "data": ["disk", "mirror", "raidz1", "raidz2", "raidz3"],
            "auxiliary": ["log", "cache", "spare"],
            "special_class": ["special", "special mirror", "dedup", "dedup mirror"]
        },
        "recommended_configs": [
            {"name": "Home NAS (2 disks)", "vdevs": ["mirror"]},
            {"name": "Home NAS (4 disks)", "vdevs": ["mirror", "mirror"]},
            {"name": "Large NAS (6+ disks)", "vdevs": ["raidz2"]},
            {"name": "Hybrid Performance", "vdevs": ["raidz1", "special mirror"]}
        ]
    }
}


def get_vdev_help(vdev_type: str) -> dict:
    """Get help info for a specific VDEV type."""
    return HELP["vdev_types"].get(vdev_type.lower(), {})


def get_empty_state(context: str) -> dict:
    """Get empty state message for a specific UI context."""
    return HELP["empty_states"].get(context, {})


def get_warning(action: str) -> dict:
    """Get warning info for a dangerous action."""
    return HELP["warnings"].get(action, {})


def get_tooltip(element: str) -> str:
    """Get tooltip text for a UI element."""
    return HELP["tooltips"].get(element, "")


def get_tip(topic: str) -> str:
    """Get a helpful tip on a topic."""
    return HELP["tips"].get(topic, "")


# --- END OF FILE src/help_strings.py ---
