# --- START OF FILE platform_block_devices.py ---
"""
Cross-platform block device enumeration using the Structured Adapter pattern.

This module provides a unified interface for listing block devices across
Linux, macOS, and FreeBSD. Instead of fragile regex parsing, it uses
structured output formats native to each OS:

- Linux: lsblk --json → Python json
- macOS: diskutil list -plist → Python plistlib  
- FreeBSD: sysctl -b kern.geom.confxml → Python xml.etree

DESIGN GOALS:
1. Tree-view ready: Returns ALL devices (disks + partitions) with parent links
2. Info-retrieval ready: Unified data model, get_device_by_name() helper
3. Filter-configurable: DeviceFilter class with toggleable rules

All platforms return the same normalized data structure for ZFS compatibility.
"""

import json
import platform
import plistlib
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set


# =============================================================================
# IMPORTS (with fallbacks for standalone testing)
# =============================================================================

try:
    import utils
    from paths import find_executable
except ImportError:
    utils = None
    def find_executable(name, paths=None):
        import shutil
        return shutil.which(name)


# =============================================================================
# ENUMS & CONSTANTS
# =============================================================================

class DisableReason(Enum):
    """Reasons why a device might be ineligible for pool creation."""
    NONE = auto()           # Device is eligible
    MOUNTED = auto()        # Device is mounted
    ZFS_MEMBER = auto()     # Device is part of a ZFS pool
    CRITICAL_FS = auto()    # Device has critical filesystem (swap, LUKS, LVM)
    VIRTUAL = auto()        # Virtual/synthesized device (APFS container, loop)
    PARENT_BLOCKED = auto() # Parent disk is blocked (child makes parent unusable)
    SYSTEM_DISK = auto()    # Boot/system disk
    ROM_DEVICE = auto()     # Read-only device (CD-ROM, etc.)


# Critical filesystem types by platform
CRITICAL_FS_LINUX = {'swap', 'crypto_luks', 'lvm2_member'}
CRITICAL_FS_MACOS = {'apfs', 'hfs', 'msdos', 'exfat', 'fat'}  # Substring match
CRITICAL_FS_FREEBSD = {'freebsd-swap', 'freebsd-ufs'}

# Device types to skip entirely (not even shown in tree)
SKIP_TYPES = {'loop', 'rom'}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class DeviceFilter:
    """
    Configurable filter for block device eligibility.
    
    Each flag controls whether that category of device is EXCLUDED.
    Set to False to INCLUDE devices of that category.
    
    Example:
        # Include ZFS members (for re-creating pools)
        filter = DeviceFilter(exclude_zfs_member=False)
        result = list_block_devices(filter)
    """
    exclude_mounted: bool = True
    exclude_zfs_member: bool = True
    exclude_critical_fs: bool = True
    exclude_virtual: bool = True
    exclude_parent_blocked: bool = True
    exclude_system_disk: bool = True
    exclude_rom: bool = True
    
    # Custom filter function: (device_dict) -> bool (True = exclude)
    custom_filter: Optional[Callable[[Dict[str, Any]], bool]] = None
    
    def should_exclude(self, device: Dict[str, Any]) -> bool:
        """Check if device should be excluded based on filter settings."""
        reason = device.get('disable_reason', DisableReason.NONE)
        
        if reason == DisableReason.MOUNTED and self.exclude_mounted:
            return True
        if reason == DisableReason.ZFS_MEMBER and self.exclude_zfs_member:
            return True
        if reason == DisableReason.CRITICAL_FS and self.exclude_critical_fs:
            return True
        if reason == DisableReason.VIRTUAL and self.exclude_virtual:
            return True
        if reason == DisableReason.PARENT_BLOCKED and self.exclude_parent_blocked:
            return True
        if reason == DisableReason.SYSTEM_DISK and self.exclude_system_disk:
            return True
        if reason == DisableReason.ROM_DEVICE and self.exclude_rom:
            return True
        
        if self.custom_filter and self.custom_filter(device):
            return True
        
        return False


@dataclass
class BlockDeviceResult:
    """
    Result container for block device enumeration.
    
    Attributes:
        all_devices: Complete list of ALL devices (for tree view)
        devices: Filtered list of eligible devices (for simple list view)
        error: Error message (None on success)
        platform: Platform name string
    """
    all_devices: List[Dict[str, Any]] = field(default_factory=list)
    devices: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    platform: str = ""
    
    @property
    def success(self) -> bool:
        """Returns True if no error occurred."""
        return self.error is None
    
    def __iter__(self):
        """Iterate over filtered devices (backward compatibility)."""
        return iter(self.devices)
    
    def __len__(self):
        """Count of filtered devices (backward compatibility)."""
        return len(self.devices)
    
    def get_device(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a device by its path/name from all_devices."""
        for dev in self.all_devices:
            if dev.get('name') == name:
                return dev
        return None
    
    def get_children(self, parent_name: str) -> List[Dict[str, Any]]:
        """Get all children of a device (for tree building)."""
        # Extract base name (e.g., "sda" from "/dev/sda")
        parent_base = parent_name.split('/')[-1] if '/' in parent_name else parent_name
        return [
            dev for dev in self.all_devices
            if dev.get('pkname') == parent_base
        ]
    
    def get_root_devices(self) -> List[Dict[str, Any]]:
        """Get top-level devices (disks with no parent)."""
        return [
            dev for dev in self.all_devices
            if dev.get('type') == 'disk' and not dev.get('pkname')
        ]
    
    def build_tree(self) -> List[Dict[str, Any]]:
        """
        Build a hierarchical tree structure for tree view rendering.
        
        Returns list of root devices, each with 'children' key containing
        nested child devices.
        """
        def add_children(device: Dict[str, Any]) -> Dict[str, Any]:
            dev_copy = dict(device)
            children = self.get_children(device['name'])
            if children:
                dev_copy['children'] = [add_children(c) for c in children]
            else:
                dev_copy['children'] = []
            return dev_copy
        
        roots = self.get_root_devices()
        return [add_children(root) for root in roots]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _format_size(size_bytes: Optional[int]) -> str:
    """Format bytes to human readable string."""
    if utils is not None:
        try:
            return utils.format_size(size_bytes)
        except Exception:
            pass
    # Fallback formatting
    if size_bytes is None or not isinstance(size_bytes, (int, float)) or size_bytes < 0:
        return "?"
    if size_bytes == 0:
        return "0B"
    units = ['B', 'K', 'M', 'G', 'T', 'P']
    i = 0
    float_size = float(size_bytes)
    while float_size >= 1024 and i < len(units) - 1:
        float_size /= 1024.0
        i += 1
    if i == 0:
        return f"{int(float_size)}{units[i]}"
    elif float_size < 10:
        return f"{float_size:.2f}{units[i]}"
    elif float_size < 100:
        return f"{float_size:.1f}{units[i]}"
    return f"{int(round(float_size))}{units[i]}"


def _run_command(cmd: List[str], binary: bool = False) -> tuple:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if binary:
            return result.returncode, result.stdout, result.stderr.decode('utf-8', errors='replace')
        return result.returncode, result.stdout.decode('utf-8', errors='replace'), result.stderr.decode('utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        return -1, "" if not binary else b"", "Command timed out"
    except FileNotFoundError:
        return -1, "" if not binary else b"", f"Command not found: {cmd[0]}"
    except Exception as e:
        return -1, "" if not binary else b"", str(e)


def _make_device_dict(
    name: str,
    size_bytes: Optional[int] = None,
    dev_type: str = 'disk',
    mountpoint: Optional[str] = None,
    fstype: Optional[str] = None,
    label: Optional[str] = None,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    serial: Optional[str] = None,
    wwn: Optional[str] = None,
    pkname: Optional[str] = None,
    disable_reason: DisableReason = DisableReason.NONE,
) -> Dict[str, Any]:
    """
    Create a standardized device dictionary.
    
    This ensures all platforms return the same structure.
    """
    size_formatted = _format_size(size_bytes)
    display_label = label or ''
    display_name = f"{name} ({size_formatted}) {display_label}".strip()
    
    return {
        'name': name,
        'size_bytes': size_bytes,
        'size': size_formatted,
        'type': dev_type,
        'mountpoint': mountpoint,
        'fstype': fstype,
        'label': label,
        'vendor': vendor,
        'model': model,
        'serial': serial,
        'wwn': wwn,
        'pkname': pkname,
        'disable_reason': disable_reason,
        'is_eligible': disable_reason == DisableReason.NONE,
        'display_name': display_name,
    }


def _apply_parent_blocking(devices: List[Dict[str, Any]]) -> None:
    """
    Mark parent disks as blocked if any child is blocked/critical.
    
    Modifies devices in-place.
    """
    blocked_parents: Set[str] = set()
    
    # First pass: collect blocked parents
    for dev in devices:
        if dev['disable_reason'] != DisableReason.NONE:
            pkname = dev.get('pkname')
            if pkname:
                blocked_parents.add(pkname)
    
    # Second pass: mark parent disks
    for dev in devices:
        if dev['type'] == 'disk' and dev['disable_reason'] == DisableReason.NONE:
            # Check if this disk's base name is in blocked_parents
            base_name = dev['name'].split('/')[-1]
            if base_name in blocked_parents:
                dev['disable_reason'] = DisableReason.PARENT_BLOCKED
                dev['is_eligible'] = False


def _apply_filter(
    all_devices: List[Dict[str, Any]],
    device_filter: Optional[DeviceFilter]
) -> List[Dict[str, Any]]:
    """Apply filter to get eligible devices only."""
    if device_filter is None:
        device_filter = DeviceFilter()
    
    eligible = []
    for dev in all_devices:
        if not device_filter.should_exclude(dev):
            eligible.append(dev)
    
    return eligible


# =============================================================================
# LINUX: lsblk --json
# =============================================================================

def _list_block_devices_linux() -> tuple:
    """
    List block devices on Linux using lsblk JSON output.
    
    Returns: (all_devices, error_string)
    """
    lsblk_path = find_executable("lsblk", ['/usr/bin', '/bin'])
    if not lsblk_path:
        return [], "'lsblk' command not found. Please install util-linux package."

    all_devices = []
    try:
        cmd = [lsblk_path, '-Jpbn', '-o', 
               'PATH,SIZE,TYPE,MOUNTPOINT,FSTYPE,PARTLABEL,LABEL,VENDOR,MODEL,SERIAL,WWN,PKNAME']
        retcode, stdout, stderr = _run_command(cmd)
        if retcode != 0:
            return [], f"lsblk command failed (code {retcode}): {stderr.strip()}"

        lsblk_data = json.loads(stdout)

        def process_node(node: Dict, parent_path: Optional[str] = None):
            dev_path = node.get('path')
            dev_type = node.get('type', '')
            fstype = node.get('fstype')
            mountpoint = node.get('mountpoint')
            pkname = node.get('pkname')

            if not dev_path:
                return

            # Skip certain device types entirely
            if dev_type in SKIP_TYPES:
                return

            # Determine disable reason
            disable_reason = DisableReason.NONE
            
            if dev_type == 'rom':
                disable_reason = DisableReason.ROM_DEVICE
            elif mountpoint and mountpoint != '[SWAP]':
                disable_reason = DisableReason.MOUNTED
            elif fstype and fstype.lower() == 'zfs_member':
                disable_reason = DisableReason.ZFS_MEMBER
            elif fstype and fstype.lower() in CRITICAL_FS_LINUX:
                disable_reason = DisableReason.CRITICAL_FS

            # Only include disk and part types
            if dev_type in ('disk', 'part'):
                # print(f"DEBUG: {dev_path} | Type: '{dev_type}' | FSType: '{fstype}' | Reason: {disable_reason}")
                device = _make_device_dict(
                    name=dev_path,
                    size_bytes=node.get('size'),
                    dev_type=dev_type,
                    mountpoint=mountpoint,
                    fstype=fstype,
                    label=node.get('label') or node.get('partlabel'),
                    vendor=(node.get('vendor') or '').strip(),
                    model=(node.get('model') or '').strip(),
                    serial=node.get('serial'),
                    wwn=node.get('wwn'),
                    pkname=pkname,
                    disable_reason=disable_reason,
                )
                all_devices.append(device)

            # Process children
            for child_node in node.get('children', []):
                process_node(child_node, dev_path)

        for top_level_device in lsblk_data.get('blockdevices', []):
            process_node(top_level_device)

        # Apply parent blocking
        _apply_parent_blocking(all_devices)

    except json.JSONDecodeError as e:
        return [], f"Failed to parse lsblk JSON output: {e}"
    except Exception as e:
        return [], f"Unexpected error: {e}"

    return all_devices, None


# =============================================================================
# macOS: diskutil list -plist
# =============================================================================

def _list_block_devices_macos(
    plist_data: Optional[bytes] = None,
    info_func: Optional[Callable[[str], Dict]] = None
) -> tuple:
    """
    List block devices on macOS using diskutil plist output.
    
    Args:
        plist_data: Optional pre-loaded plist bytes (for testing)
        info_func: Optional function to get disk info (for testing)
    
    Returns: (all_devices, error_string)
    """
    diskutil_path = find_executable("diskutil", ['/usr/sbin', '/sbin', '/usr/bin'])
    
    # If no test data provided, run actual commands
    if plist_data is None:
        if not diskutil_path:
            return [], "'diskutil' command not found."
        
        cmd = [diskutil_path, 'list', '-plist']
        retcode, stdout, stderr = _run_command(cmd)
        if retcode != 0:
            return [], f"diskutil list failed (code {retcode}): {stderr.strip()}"
        plist_data = stdout.encode('utf-8')

    all_devices = []
    try:
        disk_list = plistlib.loads(plist_data)
        all_disks = disk_list.get('AllDisks', [])
        whole_disks = set(disk_list.get('WholeDisks', []))

        # Helper to get disk info
        def get_disk_info(disk_id: str) -> Dict:
            if info_func:
                return info_func(disk_id)
            
            if not diskutil_path:
                return {}
            
            cmd_info = [diskutil_path, 'info', '-plist', disk_id]
            retcode_info, stdout_info, _ = _run_command(cmd_info)
            if retcode_info != 0:
                return {}
            return plistlib.loads(stdout_info.encode('utf-8'))

        # Process ALL disks (whole disks and partitions)
        for disk_id in all_disks:
            dev_path = f"/dev/{disk_id}"
            is_whole_disk = disk_id in whole_disks
            
            disk_info = get_disk_info(disk_id)
            if not disk_info:
                continue
            
            size_bytes = disk_info.get('TotalSize') or disk_info.get('Size', 0)
            content = disk_info.get('Content', '')
            fstype = disk_info.get('FilesystemType', '') or content
            mountpoint = disk_info.get('MountPoint', '')
            is_virtual = disk_info.get('VirtualOrPhysical', '') == 'Virtual'
            media_name = disk_info.get('MediaName', '')
            volume_name = disk_info.get('VolumeName', '')
            
            # Determine parent (pkname) for partitions
            pkname = None
            if not is_whole_disk:
                # Extract parent: disk0s1 -> disk0, disk12s3 -> disk12
                match = re.match(r'^(disk\d+)', disk_id)
                if match:
                    pkname = match.group(1)
            
            # Determine disable reason
            disable_reason = DisableReason.NONE
            
            if is_virtual:
                disable_reason = DisableReason.VIRTUAL
            elif mountpoint:
                disable_reason = DisableReason.MOUNTED
            elif fstype:
                fstype_lower = fstype.lower()
                if 'zfs' in fstype_lower or 'linux filesystem' in fstype_lower:
                    disable_reason = DisableReason.ZFS_MEMBER
                elif 'efi' in content.lower():
                    disable_reason = DisableReason.SYSTEM_DISK
                elif any(fs in fstype_lower for fs in CRITICAL_FS_MACOS):
                    disable_reason = DisableReason.CRITICAL_FS

            # print(f"DEBUG: {dev_path} | Content: '{content}' | FSType: '{fstype}' | Reason: {disable_reason}")

            device = _make_device_dict(
                name=dev_path,
                size_bytes=size_bytes,
                dev_type='disk' if is_whole_disk else 'part',
                mountpoint=mountpoint or None,
                fstype=fstype or None,
                label=volume_name or media_name or None,
                vendor=None,
                model=media_name or None,
                serial=disk_info.get('DeviceIdentifier'),
                wwn=None,
                pkname=pkname,
                disable_reason=disable_reason,
            )
            all_devices.append(device)

        # Apply parent blocking (only adds PARENT_BLOCKED as disable reason)
        _apply_parent_blocking(all_devices)

    except plistlib.InvalidFileException as e:
        return [], f"Failed to parse diskutil plist output: {e}"
    except Exception as e:
        return [], f"Unexpected error: {e}"

    return all_devices, None


# =============================================================================
# FreeBSD: sysctl -b kern.geom.confxml
# =============================================================================

def _list_block_devices_freebsd(
    xml_data: Optional[bytes] = None,
    mount_output: Optional[str] = None
) -> tuple:
    """
    List block devices on FreeBSD using GEOM XML configuration.
    
    Args:
        xml_data: Optional pre-loaded XML bytes (for testing)
        mount_output: Optional mount command output (for testing)
    
    Returns: (all_devices, error_string)
    """
    sysctl_path = find_executable("sysctl", ['/sbin', '/usr/sbin', '/bin', '/usr/bin'])
    
    if xml_data is None:
        if not sysctl_path:
            return [], "'sysctl' command not found."
        
        cmd = [sysctl_path, '-b', 'kern.geom.confxml']
        retcode, stdout_bytes, stderr = _run_command(cmd, binary=True)
        if retcode != 0:
            return [], f"sysctl kern.geom.confxml failed (code {retcode}): {stderr.strip()}"
        xml_data = stdout_bytes

    all_devices = []
    try:
        # Strip trailing null bytes often returned by sysctl -b (fix not formed well xml error)
        if isinstance(xml_data, bytes):
            xml_data = xml_data.rstrip(b'\x00')
            
        root = ET.fromstring(xml_data)
        
        # Get mounted devices
        mounted_devices: Set[str] = set()
        if mount_output is None:
            mount_cmd = [find_executable("mount", ['/sbin', '/bin']) or 'mount']
            retcode_m, mount_output, _ = _run_command(mount_cmd)
            if retcode_m != 0:
                mount_output = ""
        
        for line in mount_output.splitlines():
            if line.startswith('/dev/'):
                parts = line.split()
                if parts:
                    mounted_devices.add(parts[0])

        # Build provider ID -> info map for DISK class (for model/serial lookup)
        disk_info_map: Dict[str, Dict] = {}
        for geom_class in root.findall('.//class'):
            class_name = geom_class.findtext('name', '')
            if class_name == 'DISK':
                for geom in geom_class.findall('geom'):
                    config = geom.find('config')
                    descr = ''
                    ident = ''
                    if config is not None:
                        descr = config.findtext('descr', '') or ''
                        ident = config.findtext('ident', '') or ''
                    
                    for provider in geom.findall('provider'):
                        prov_name = provider.findtext('name', '')
                        disk_info_map[prov_name] = {
                            'model': descr.strip(),
                            'serial': ident.strip(),
                        }

        # Process DISK class (whole disks)
        for geom_class in root.findall('.//class'):
            class_name = geom_class.findtext('name', '')
            
            if class_name == 'DISK':
                for geom in geom_class.findall('geom'):
                    for provider in geom.findall('provider'):
                        prov_name = provider.findtext('name', '')
                        dev_path = f"/dev/{prov_name}"
                        
                        mediasize = provider.findtext('mediasize', '0')
                        try:
                            size_bytes = int(mediasize)
                        except ValueError:
                            size_bytes = 0

                        info = disk_info_map.get(prov_name, {})
                        is_mounted = dev_path in mounted_devices

                        disable_reason = DisableReason.NONE
                        if is_mounted:
                            disable_reason = DisableReason.MOUNTED

                        # print(f"DEBUG: {dev_path} | Type: 'DISK' | Model: '{info.get('model')}' | Reason: {disable_reason}")

                        device = _make_device_dict(
                            name=dev_path,
                            size_bytes=size_bytes,
                            dev_type='disk',
                            mountpoint=dev_path if is_mounted else None,
                            fstype=None,
                            label=None,
                            vendor=None,
                            model=info.get('model'),
                            serial=info.get('serial'),
                            wwn=None,
                            pkname=None,
                            disable_reason=disable_reason,
                        )
                        all_devices.append(device)

            elif class_name == 'PART':
                for geom in geom_class.findall('geom'):
                    parent_name = geom.findtext('name', '')
                    
                    for provider in geom.findall('provider'):
                        prov_name = provider.findtext('name', '')
                        dev_path = f"/dev/{prov_name}"
                        
                        mediasize = provider.findtext('mediasize', '0')
                        try:
                            size_bytes = int(mediasize)
                        except ValueError:
                            size_bytes = 0

                        config = provider.find('config')
                        part_type = ''
                        label = ''
                        if config is not None:
                            part_type = config.findtext('type', '') or ''
                            label = config.findtext('label', '') or ''

                        is_mounted = dev_path in mounted_devices
                        
                        # Determine disable reason
                        disable_reason = DisableReason.NONE
                        part_type_lower = part_type.lower()
                        
                        if is_mounted:
                            disable_reason = DisableReason.MOUNTED
                        elif 'zfs' in part_type_lower or 'zfs' in label.lower():
                            disable_reason = DisableReason.ZFS_MEMBER
                        elif part_type_lower in CRITICAL_FS_FREEBSD:
                            disable_reason = DisableReason.CRITICAL_FS

                        # print(f"DEBUG: {dev_path} | Type: 'PART' | FSType: '{part_type}' | Reason: {disable_reason}")

                        device = _make_device_dict(
                            name=dev_path,
                            size_bytes=size_bytes,
                            dev_type='part',
                            mountpoint=dev_path if is_mounted else None,
                            fstype=part_type or None,
                            label=label or None,
                            vendor=None,
                            model=None,
                            serial=None,
                            wwn=None,
                            pkname=parent_name,
                            disable_reason=disable_reason,
                        )
                        all_devices.append(device)

        # Apply parent blocking
        _apply_parent_blocking(all_devices)

    except ET.ParseError as e:
        return [], f"Failed to parse GEOM XML: {e}"
    except Exception as e:
        return [], f"Unexpected error: {e}"

    return all_devices, None


# =============================================================================
# PUBLIC API
# =============================================================================

def list_block_devices(
    device_filter: Optional[DeviceFilter] = None
) -> BlockDeviceResult:
    """
    List available block devices for ZFS pool creation.
    
    Automatically detects the platform and uses the appropriate method:
    - Linux: lsblk --json
    - macOS (Darwin): diskutil list -plist
    - FreeBSD/BSD: sysctl -b kern.geom.confxml
    
    Args:
        device_filter: Optional DeviceFilter to customize eligibility rules.
                      If None, uses default filter (exclude all blocked devices).
    
    Returns:
        BlockDeviceResult with:
        - all_devices: Complete list of ALL devices (for tree view)
        - devices: Filtered list of eligible devices (for simple list)
        - error: Error message (None on success)
        - platform: Platform name
        
        The result object provides helper methods:
        - get_device(name): Get device by path
        - get_children(name): Get children of a device
        - get_root_devices(): Get top-level disks
        - build_tree(): Build hierarchical tree structure
    
    Each device dict contains:
        - name: Device path (e.g., /dev/sda)
        - size_bytes: Size in bytes
        - size: Human-readable size string
        - type: 'disk' or 'part'
        - mountpoint: Mount point or None
        - fstype: Filesystem type or None
        - label: Label or None
        - vendor, model, serial, wwn: Hardware info
        - pkname: Parent kernel name (for hierarchy)
        - disable_reason: DisableReason enum value
        - is_eligible: Boolean (True if no disable_reason)
        - display_name: Formatted string for UI
    
    Example:
        # Get all devices with default filter
        result = list_block_devices()
        
        # Build a tree view
        tree = result.build_tree()
        
        # Include ZFS members
        from platform_block_devices import DeviceFilter
        filter = DeviceFilter(exclude_zfs_member=False)
        result = list_block_devices(filter)
        
        # Get specific device info
        device = result.get_device('/dev/sda')
    """
    system = platform.system()
    
    if system == 'Linux':
        all_devices, error = _list_block_devices_linux()
        plat = "Linux"
    elif system == 'Darwin':
        all_devices, error = _list_block_devices_macos()
        plat = "macOS"
    elif 'BSD' in system:
        all_devices, error = _list_block_devices_freebsd()
        plat = "FreeBSD"
    else:
        return BlockDeviceResult(
            error=f"Unsupported platform: {system}. Supported: Linux, macOS, FreeBSD.",
            platform=system
        )
    
    if error:
        return BlockDeviceResult(error=error, platform=plat)
    
    # Sort all devices
    all_devices.sort(key=lambda x: x.get('name', ''))
    
    # Apply filter
    filtered_devices = _apply_filter(all_devices, device_filter)
    
    return BlockDeviceResult(
        all_devices=all_devices,
        devices=filtered_devices,
        platform=plat
    )


def get_platform_info() -> Dict[str, str]:
    """Return information about the current platform for debugging."""
    return {
        'system': platform.system(),
        'release': platform.release(),
        'version': platform.version(),
        'machine': platform.machine(),
    }


# =============================================================================
# STANDALONE TESTING
# =============================================================================

if __name__ == '__main__':
    import pprint
    
    print("=" * 60)
    print("Platform Block Devices - Standalone Test")
    print("=" * 60)
    
    print("\nPlatform Info:")
    pprint.pprint(get_platform_info())
    
    print("\n" + "-" * 60)
    print("All Block Devices (unfiltered):")
    print("-" * 60)
    
    result = list_block_devices()
    
    if result.error:
        print(f"\n  ERROR [{result.platform}]: {result.error}")
    else:
        for dev in result.all_devices:
            status = "✓" if dev['is_eligible'] else f"✗ ({dev['disable_reason'].name})"
            indent = "  " if dev['type'] == 'disk' else "    "
            print(f"{indent}{status} {dev['display_name']}")
            if dev.get('pkname'):
                print(f"{indent}   └─ Parent: {dev['pkname']}")
        
        print(f"\n  Total: {len(result.all_devices)} devices, {len(result.devices)} eligible")
        
        print("\n" + "-" * 60)
        print("Tree View:")
        print("-" * 60)
        
        def print_tree(nodes, indent=0):
            for node in nodes:
                status = "✓" if node['is_eligible'] else "✗"
                print(f"{'  ' * indent}{status} {node['name']} ({node['size']})")
                if node.get('children'):
                    print_tree(node['children'], indent + 1)
        
        tree = result.build_tree()
        print_tree(tree)

# --- END OF FILE platform_block_devices.py ---
