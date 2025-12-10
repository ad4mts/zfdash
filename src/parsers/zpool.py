# --- START OF FILE parsers/zpool.py ---
"""
Parsers for `zpool` command outputs (status, list, import).
Uses native JSON output where available (ZFS >= 2.3.1).
"""

import json
import sys
import re
import subprocess
from typing import Dict, Any, Optional, List


def _detect_legacy_mode() -> bool:
    """Check ZFS version. Returns True if legacy parsing needed (< 2.3.1)."""
    try:
        out = subprocess.run(['zpool', '--version'], capture_output=True, text=True, timeout=5)
        match = re.search(r'zfs-(\d+)\.(\d+)\.(\d+)', out.stdout)
        if match:
            major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return (major, minor, patch) < (2, 3, 1)
    except Exception:
        pass
    return True  # Fallback to legacy on any error


class ZPoolParser:
    """Parses output from various `zpool` commands."""
    
    # --- Auto-detect: Use JSON if ZFS >= 2.3.1 ---
    USE_LEGACY_PARSER = _detect_legacy_mode()
    # ---------------------------------------------

    @classmethod
    def get_status_command(cls, pool_name: Optional[str] = None) -> List[str]:
        """Returns the appropriate zpool status command based on the parser mode."""
        base_cmd = ['zpool', 'status', '-P']
        json_flag = [] if cls.USE_LEGACY_PARSER else ['-j']
        pool_arg = [pool_name] if pool_name else []
        return base_cmd + json_flag + pool_arg

    @classmethod
    def parse_status(cls, raw_output: str, pool_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Dispatches parsing to the appropriate method based on parser mode.
        No if/else blocks - uses method reference selection.
        """
        parser_fn = cls._parse_from_text if cls.USE_LEGACY_PARSER else cls._parse_from_json
        return parser_fn(raw_output, pool_name)

    @staticmethod
    def _parse_from_json(raw_output: str, pool_name: Optional[str] = None) -> Dict[str, Any]:
        """Internal: Parses JSON string output."""
        try:
            json_data = json.loads(raw_output)
            return ZPoolParser.parse_status_json(json_data, pool_name)
        except json.JSONDecodeError:
            return {"pools": {}}

    @staticmethod
    def _parse_from_text(raw_output: str, pool_name: Optional[str] = None) -> Dict[str, Any]:
        """Internal: Parses legacy text output."""
        return ZPoolParser.parse_status_text(raw_output, pool_name)

    @staticmethod
    def parse_status_json(raw_json: Dict[str, Any], pool_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Parses the JSON output of `zpool status -j [-P] [pool_name]`.

        Args:
            raw_json: The parsed JSON dictionary from `zpool status -j`.
            pool_name: Optional pool name to extract. If None, returns all pools.

        Returns:
            A dictionary containing a standardized, UI-ready representation of the pool(s).
            Structure:
            {
                "pools": {
                    "<pool_name>": {
                        "name": str,
                        "state": str,
                        "scan": dict | None,
                        "errors": str,
                        "vdev_tree": {
                            "name": str,
                            "type": str,  # "root", "mirror", "raidz", "disk", etc.
                            "state": str,
                            "read_errors": str,
                            "write_errors": str,
                            "checksum_errors": str,
                            "path": str | None,  # Device path for leaves
                            "children": [...]  # Recursive list of child vdevs
                        }
                    }
                }
            }
        """
        print(f"ZpoolParser: DEBUG: Using ZPoolParser JSON Mode for pool: {pool_name}", file=sys.stderr)
        result: Dict[str, Any] = {"pools": {}}

        pools_data = raw_json.get("pools", {})
        if not pools_data:
            return result

        target_pools = [pool_name] if pool_name else list(pools_data.keys())

        for pname in target_pools:
            if pname not in pools_data:
                continue

            pool_info = pools_data[pname]
            parsed_pool: Dict[str, Any] = {
                "name": pool_info.get("name", pname),
                "state": pool_info.get("state", "UNKNOWN"),
                "scan": pool_info.get("scan_stats"),
                "errors": pool_info.get("error_count", "0"),
                "vdev_tree": ZPoolParser._parse_vdev_tree(pool_info.get("vdevs", {}))
            }
            result["pools"][pname] = parsed_pool

        return result

    @staticmethod
    def _parse_vdev_tree(vdevs_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively parses the nested 'vdevs' dictionary from `zpool status -j`.

        Args:
            vdevs_dict: The 'vdevs' dictionary from a pool or parent vdev.

        Returns:
            A standardized dictionary representing the VDEV and its children.
        """
        # The root 'vdevs' dict usually has one key: the pool name itself as root.
        # We iterate through all keys to handle any structure.
        if not vdevs_dict:
            return {}

        # If there's a single key and it's the root, start from it.
        # Otherwise, build a synthetic root containing all top-level vdevs.
        keys = list(vdevs_dict.keys())

        if len(keys) == 1:
            root_key = keys[0]
            root_vdev = vdevs_dict[root_key]
            return ZPoolParser._parse_single_vdev(root_vdev)
        else:
            # Multiple top-level vdevs (unusual but handle it)
            return {
                "name": "root",
                "type": "root",
                "state": "ONLINE",
                "children": [ZPoolParser._parse_single_vdev(vdevs_dict[k]) for k in keys]
            }

    @staticmethod
    def _parse_single_vdev(vdev_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parses a single vdev entry and its children recursively.

        Args:
            vdev_data: A dictionary representing a single VDEV node.

        Returns:
            A standardized dictionary for this VDEV.
        """
        parsed: Dict[str, Any] = {
            "name": vdev_data.get("name", "unknown"),
            "type": vdev_data.get("vdev_type", "unknown"),
            "state": vdev_data.get("state", "UNKNOWN"),
            "read_errors": vdev_data.get("read_errors", "0"),
            "write_errors": vdev_data.get("write_errors", "0"),
            "checksum_errors": vdev_data.get("checksum_errors", "0"),
            "path": vdev_data.get("path"),  # Only present for leaf devices
            "guid": vdev_data.get("guid"),
            "alloc_space": vdev_data.get("alloc_space"),
            "total_space": vdev_data.get("total_space"),
        }

        # Recursively parse children
        children_dict = vdev_data.get("vdevs", {})
        if children_dict:
            parsed["children"] = [
                ZPoolParser._parse_single_vdev(children_dict[child_key])
                for child_key in children_dict
            ]
        else:
            parsed["children"] = []

        return parsed


    @staticmethod
    def parse_status_text(raw_text: str, pool_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Parses the legacy text output of `zpool status [-v] [pool_name]`.
        Acts as a fallback for systems without JSON output support (< OpenZFS 2.3).
        
        Args:
            raw_text: The stdout text from `zpool status`.
            pool_name: Optional pool name to filter/validate.
            
        Returns:
            A dictionary structure identical to `parse_status_json`.
        """
        print(f"ZpoolParser: DEBUG: Using ZPoolParser Legacy Text Mode for pool: {pool_name}", file=sys.stderr)
        result: Dict[str, Any] = {"pools": {}}
        if not raw_text:
            return result
            
        # Regex patterns
        # Identify pool name from "  pool: <name>"
        pool_name_re = re.compile(r'^\s*pool:\s+(\S+)')
        # Identify state from " state: <state>"
        state_re = re.compile(r'^\s*state:\s+(\S+)')
        # Standard config line: indent | name | state | R | W | C
        # Group 1: indent, 2: name, 3: state, 4: read, 5: write, 6: cksum
        config_line_re = re.compile(r'^(\s+)(.+?)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)')
        # Simple line (e.g. cache/logs headers or just name): indent | name
        simple_line_re = re.compile(r'^(\s+)(\S+.*)')
        
        lines = raw_text.splitlines()
        current_pool_info = {}
        in_config = False
        
        # Stack for hierarchical parsing: [(indent_level, node_dict, list_of_children)]
        # We'll build the tree during the config section
        stack = [] 
        
        # If raw_text contains multiple pools, we need to handle that. 
        # But complex logic for multiple pools in one text blob is tricky with indentation.
        # We'll assume the text typically starts with "pool: name" or is for a single pool.
        
        # Find the pool name first if not provided
        detected_pool_name = None
        
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped: continue
            
            # Header parsing
            m_pool = pool_name_re.match(line)
            if m_pool:
                detected_pool_name = m_pool.group(1)
                # Initialize new pool structure
                current_pool_info = {
                    "name": detected_pool_name,
                    "state": "UNKNOWN",
                    "errors": "No known data errors",
                    "vdev_tree": {}
                }
                result["pools"][detected_pool_name] = current_pool_info
                in_config = False
                continue
                
            if not current_pool_info:
                # If we haven't found a "pool:" line yet, skip (or it's partial output)
                continue
                
            m_state = state_re.match(line)
            if m_state:
                current_pool_info["state"] = m_state.group(1)
                continue
                
            if line_stripped.startswith("config:"):
                in_config = True
                stack = [] # Reset stack
                continue
                
            if not in_config:
                continue
                
            if line_stripped.startswith("errors:"):
                current_pool_info["errors"] = line_stripped.split(":", 1)[1].strip()
                in_config = False
                continue
                
            # --- Config Section Parsing ---
            # Skip headers
            if "NAME" in line and "STATE" in line:
                continue
                
            # Parse indentation and content
            indent = 0
            name = ""
            state = "ONLINE"
            read_err = "0"
            write_err = "0"
            cksum_err = "0"
            vdev_type = "disk" # Default, refine later
            
            m_config = config_line_re.match(line)
            m_simple = simple_line_re.match(line)
            
            if m_config:
                indent = len(m_config.group(1))
                name = m_config.group(2).strip()
                state = m_config.group(3)
                read_err = m_config.group(4)
                write_err = m_config.group(5)
                cksum_err = m_config.group(6)
            elif m_simple:
                indent = len(m_simple.group(1))
                name = m_simple.group(2).strip()
            else:
                continue
                
            # Determine type based on name
            if name.startswith("mirror"): vdev_type = "mirror"
            elif name.startswith("raidz"): vdev_type = "raidz"
            elif name.startswith("draid"): vdev_type = "draid"
            elif name in ["logs", "cache", "special", "spares"]: vdev_type = name
            else: vdev_type = "disk"
            
            # Create node
            node = {
                "name": name,
                "type": vdev_type,
                "state": state,
                "read_errors": read_err,
                "write_errors": write_err,
                "checksum_errors": cksum_err,
                "children": []
            }
            if vdev_type == "disk" and "/" in name:
                 # Guess path if it looks like one, or default to name
                 node["path"] = name
            elif vdev_type == "disk":
                 # For simple disk names (sda, etc), path might not be full
                 node["path"] = name
            
            # --- Tree Building Logic ---
            
            # Root node (pool name itself in config)
            if name == current_pool_info["name"]:
                # This is the root vdev
                current_pool_info["vdev_tree"] = node
                # Base indentation for root
                stack = [(indent, node)]
                continue
                
            # Adjust stack based on indentation
            while stack and indent <= stack[-1][0]:
                stack.pop()
                
            if stack:
                parent_node = stack[-1][1]
                parent_node["children"].append(node)
                stack.append((indent, node))
            else:
                # Fallback if hierarchy is unclear or multiple roots
                # (Shouldn't happen in standard `zpool status`, but safe fallback)
                pass 
                
        return result

# --- END OF FILE parsers/zpool.py ---
