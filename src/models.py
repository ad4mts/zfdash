# --- START OF FILE models.py ---

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class ZfsObject:
    # Basic attributes compared by default
    name: str
    obj_type: str = "zfs" # 'pool', 'dataset', 'volume', 'snapshot'
    properties: Dict[str, Any] = field(default_factory=dict)

    # Exclude parent from comparison to prevent recursion
    parent: Optional['ZfsObject'] = field(default=None, compare=False, repr=False) # repr=False reduces clutter

    def get_property(self, key, default=None):
        return self.properties.get(key, default)

@dataclass
class Pool(ZfsObject):
    health: str = "UNKNOWN"
    size: int = 0 # bytes
    alloc: int = 0 # bytes
    free: int = 0 # bytes
    frag: str = "-" # percentage string
    cap: str = "-" # percentage string
    dedup: str = "off"
    guid: str = ""
    status_details: str = "" # Full output from zpool status
    obj_type: str = "pool"

    # Exclude children from comparison
    children: List['Dataset'] = field(default_factory=list, compare=False, repr=False) # Root datasets/volumes
    # Pools have no parent in our model, but added compare=False for consistency if base class changes
    parent: None = field(default=None, init=False, compare=False, repr=False) # Explicitly None and not compared


@dataclass
class Dataset(ZfsObject):
    pool_name: str = ""
    used: int = 0 # bytes
    available: int = 0 # bytes
    referenced: int = 0 # bytes
    mountpoint: str = ""
    obj_type: str = "dataset" # or 'volume'
    is_encrypted: bool = False
    is_mounted: bool = False

    # Exclude children and snapshots from comparison
    children: List['Dataset'] = field(default_factory=list, compare=False, repr=False)
    snapshots: List['Snapshot'] = field(default_factory=list, compare=False, repr=False)
    # Parent (Pool or Dataset) already excluded via base class field


@dataclass
class Snapshot(ZfsObject):
    pool_name: str = ""
    dataset_name: str = "" # Full dataset name (pool/path/to/fs@snap)
    used: int = 0 # bytes
    referenced: int = 0 # bytes
    creation_time: str = "" # Keep as string for simplicity for now
    obj_type: str = "snapshot"
    # Parent (the Dataset it belongs to) already excluded via base class field


# Helper function (remains the same)
def find_child(parent_list, name):
    for child in parent_list:
        if child.name == name:
            return child
    return None

# --- END OF FILE models.py ---
