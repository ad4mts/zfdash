"""
SSH-backed ZFS manager client.

This client mirrors the subset of ZfsManagerClient used by the Web UI, but
executes zfs/zpool/lsblk commands over SSH instead of talking to a ZfDash agent.
It is read-only by default; a small allowlist of low-risk actions can be enabled
per connection by Control Center configuration.
"""

import json
import shlex
import time
from typing import Any, Dict, List, Optional, Tuple

import constants
import utils
from models import Pool, Dataset, Snapshot, ZfsObject
from parsers.zpool import ZPoolParser
from zfs_manager import ZfsCommandError, ZfsClientCommunicationError, build_zfs_hierarchy

try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    paramiko = None
    PARAMIKO_AVAILABLE = False


SSH_ACTION_ALLOWLIST = {
    "scrub_pool",
    "clear_pool_errors",
    "mount_dataset",
    "unmount_dataset",
}


class SshZfsManagerClient:
    """ZFS manager client that runs commands on a remote host via SSH."""

    def __init__(
        self,
        host: str,
        *,
        port: int = 22,
        username: str = "root",
        password: Optional[str] = None,
        auth_method: str = "key",
        key_path: Optional[str] = None,
        allow_actions: bool = False,
        connect_timeout: float = 15.0,
        command_timeout: float = constants.CLIENT_ACTION_TIMEOUT,
        reconnect_ttl: float = 30.0,
    ):
        if not PARAMIKO_AVAILABLE:
            raise ZfsClientCommunicationError("paramiko is required for SSH remote monitoring")

        self.host = host
        self.port = int(port or 22)
        self.username = username or "root"
        self.password = password or None
        self.auth_method = auth_method or "key"
        self.key_path = key_path or None
        self.allow_actions = bool(allow_actions)
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.reconnect_ttl = reconnect_ttl
        self._client: Optional[paramiko.SSHClient] = None
        self._last_health_check = 0.0
        self._last_error: Optional[str] = None

        self._connect()

    def _connect(self) -> None:
        self.close()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.connect_timeout,
            "banner_timeout": self.connect_timeout,
            "auth_timeout": self.connect_timeout,
        }
        if self.auth_method == "password":
            if not self.password:
                raise ZfsClientCommunicationError("SSH password is required for password authentication")
            kwargs["password"] = self.password
            kwargs["look_for_keys"] = False
            kwargs["allow_agent"] = False
        else:
            kwargs["key_filename"] = self.key_path if self.key_path else None
            kwargs["look_for_keys"] = True
            kwargs["allow_agent"] = True
            if self.password:
                kwargs["passphrase"] = self.password

        try:
            client.connect(**kwargs)
            self._client = client
            self._last_error = None
            self._last_health_check = time.time()
        except Exception as e:
            self._last_error = str(e)
            try:
                client.close()
            except Exception:
                pass
            raise ZfsClientCommunicationError(f"SSH connection failed: {e}") from e

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None

    def _ensure_connected(self) -> None:
        if not self._client or not self.is_connection_healthy():
            self._connect()

    def _run_remote(self, argv: List[str], timeout: Optional[float] = None) -> Tuple[int, str, str]:
        self._ensure_connected()
        command = shlex.join([str(part) for part in argv])
        try:
            stdin, stdout, stderr = self._client.exec_command(
                command,
                timeout=timeout or self.command_timeout,
            )
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            self._last_error = None
            return rc, out, err
        except Exception as e:
            self._last_error = str(e)
            self.close()
            raise ZfsClientCommunicationError(f"SSH command failed: {e}") from e

    def _run_shell(self, command: str, timeout: Optional[float] = None) -> Tuple[int, str, str]:
        self._ensure_connected()
        try:
            stdin, stdout, stderr = self._client.exec_command(
                command,
                timeout=timeout or self.command_timeout,
            )
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            self._last_error = None
            return rc, out, err
        except Exception as e:
            self._last_error = str(e)
            self.close()
            raise ZfsClientCommunicationError(f"SSH command failed: {e}") from e

    def _raise_if_failed(self, rc: int, stderr: str, command: List[str], message: str) -> None:
        if rc != 0:
            raise ZfsCommandError(message, f"{shlex.join(command)}\n{stderr.strip()}")

    def _send_request(self, command: str, *args, timeout: float = constants.CLIENT_ACTION_TIMEOUT, **kwargs) -> Dict[str, Any]:
        handlers = {
            "list_pools": self._cmd_list_pools,
            "list_all_datasets_snapshots": self._cmd_list_all_datasets_snapshots,
            "get_pool_status": self._cmd_get_pool_status,
            "get_pool_status_structure": self._cmd_get_pool_status_structure,
            "get_pool_list_verbose": self._cmd_get_pool_list_verbose,
            "get_pool_iostat_verbose": self._cmd_get_pool_iostat_verbose,
            "get_all_properties_with_sources": self._cmd_get_all_properties_with_sources,
            "list_importable_pools": self._cmd_list_importable_pools,
            "list_block_devices": self._cmd_list_block_devices,
        }

        if command in SSH_ACTION_ALLOWLIST:
            if not self.allow_actions:
                raise ZfsCommandError("SSH remote is read-only. Enable SSH actions for this connection to run this command.")
            return {"status": "success", "data": self._cmd_allowed_action(command, *args, **kwargs)}

        if command not in handlers:
            raise ZfsCommandError(f"SSH remote is read-only or does not support command '{command}'")

        return {"status": "success", "data": handlers[command](*args, **kwargs)}

    def _cmd_list_pools(self) -> List[Dict[str, Any]]:
        cmd = ["zpool", "list", "-H", "-o", ",".join(constants.ZPOOL_PROPS)]
        rc, out, err = self._run_remote(cmd)
        self._raise_if_failed(rc, err, cmd, "Failed to list pools.")
        pools = []
        for line in out.strip().splitlines():
            if not line:
                continue
            values = line.strip().split("\t")
            if len(values) == len(constants.ZPOOL_PROPS):
                pools.append(dict(zip(constants.ZPOOL_PROPS, values)))
        return pools

    def _cmd_list_all_datasets_snapshots(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        ds_cmd = ["zfs", "list", "-H", "-r", "-o", ",".join(constants.ZFS_DATASET_PROPS), "-t", "filesystem,volume"]
        rc, out, err = self._run_remote(ds_cmd)
        self._raise_if_failed(rc, err, ds_cmd, "Failed to list datasets/volumes.")
        for line in out.strip().splitlines():
            values = line.strip().split("\t")
            if len(values) == len(constants.ZFS_DATASET_PROPS):
                items.append(dict(zip(constants.ZFS_DATASET_PROPS, values)))

        snap_cmd = ["zfs", "list", "-H", "-r", "-o", ",".join(constants.ZFS_SNAPSHOT_PROPS), "-t", "snapshot"]
        rc, out, err = self._run_remote(snap_cmd)
        if rc == 0:
            for line in out.strip().splitlines():
                values = line.strip().split("\t")
                if len(values) == len(constants.ZFS_SNAPSHOT_PROPS):
                    props = dict(zip(constants.ZFS_SNAPSHOT_PROPS, values))
                    props["type"] = "snapshot"
                    items.append(props)
        elif "does not exist" not in err.lower() and "no datasets available" not in err.lower():
            raise ZfsCommandError("Failed to list snapshots.", err)
        return items

    def _cmd_get_pool_status(self, pool_name: str) -> str:
        cmd = ["zpool", "status", "-v", "-P", pool_name]
        rc, out, err = self._run_remote(cmd)
        self._raise_if_failed(rc, err, cmd, f"Failed to get status for pool '{pool_name}'.")
        return out.strip()

    def _cmd_get_pool_status_structure(self, pool_name: Optional[str] = None) -> Dict[str, Any]:
        cmd = ZPoolParser.get_status_command(pool_name)
        rc, out, err = self._run_remote(cmd)
        self._raise_if_failed(rc, err, cmd, "Failed to get pool status structure.")
        return ZPoolParser.parse_status(out, pool_name)

    def _cmd_get_pool_list_verbose(self, pool_name: str) -> str:
        cmd = ["zpool", "list", "-v", pool_name]
        rc, out, err = self._run_remote(cmd)
        self._raise_if_failed(rc, err, cmd, f"Failed to get verbose list for pool '{pool_name}'.")
        return out.strip()

    def _cmd_get_pool_iostat_verbose(self, pool_name: str) -> str:
        cmd = ["zpool", "iostat", "-v", pool_name]
        rc, out, err = self._run_remote(cmd)
        self._raise_if_failed(rc, err, cmd, f"Failed to get iostat for pool '{pool_name}'.")
        return out.strip()

    def _cmd_get_all_properties_with_sources(self, obj_name: str) -> Dict[str, Dict[str, str]]:
        properties: Dict[str, Dict[str, str]] = {}
        if "/" not in obj_name:
            pool_cmd = ["zpool", "get", "-H", "-p", "-o", "name,property,value,source", "all", obj_name]
            rc, out, err = self._run_remote(pool_cmd)
            self._raise_if_failed(rc, err, pool_cmd, f"Failed to get pool properties for '{obj_name}'.")
            self._parse_properties(out, properties)

        zfs_cmd = ["zfs", "get", "-H", "-p", "-o", "name,property,value,source", "all", obj_name]
        rc, out, err = self._run_remote(zfs_cmd)
        self._raise_if_failed(rc, err, zfs_cmd, f"Failed to get properties for '{obj_name}'.")
        self._parse_properties(out, properties)
        return properties

    @staticmethod
    def _parse_properties(output: str, properties: Dict[str, Dict[str, str]]) -> None:
        for line in output.strip().splitlines():
            try:
                _name, prop, value, source = line.strip().split("\t", 3)
                properties[prop] = {"value": value, "source": source}
            except ValueError:
                continue

    def _cmd_list_importable_pools(self, search_dirs: Optional[List[str]] = None) -> List[Dict[str, str]]:
        cmd = ["zpool", "import"]
        if search_dirs:
            for path in search_dirs:
                cmd.extend(["-d", path])
        rc, out, err = self._run_remote(cmd)
        if "no pools available for import" in err.lower() or not out.strip():
            return []
        self._raise_if_failed(rc, err, cmd, "Failed to search for importable pools.")
        pools = []
        current = None
        config_lines = []
        for line in out.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                key, value = key.strip(), value.strip()
                if key == "pool":
                    if current:
                        current["config"] = "\n".join(config_lines).strip()
                        pools.append(current)
                    current = {"name": value, "id": "", "state": "", "action": "", "config": ""}
                    config_lines = []
                elif current and key in current:
                    current[key] = value
                elif current and key == "config":
                    config_lines.append(value)
            elif current and config_lines:
                config_lines.append(stripped)
        if current:
            current["config"] = "\n".join(config_lines).strip()
            pools.append(current)
        return pools

    def _cmd_list_block_devices(self) -> Dict[str, Any]:
        cmd = "lsblk -Jpbn -o PATH,NAME,KNAME,PKNAME,TYPE,SIZE,FSTYPE,MOUNTPOINT,MODEL,SERIAL,ROTA,RO,RM,TRAN 2>/dev/null"
        rc, out, err = self._run_shell(cmd, timeout=constants.CLIENT_REQUEST_TIMEOUT)
        if rc != 0:
            return {"error": err.strip() or "Failed to list remote block devices", "all_devices": [], "devices": [], "platform": "linux"}
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            return {"error": f"Failed to parse lsblk JSON: {e}", "all_devices": [], "devices": [], "platform": "linux"}

        all_devices = []

        def flatten(items):
            for item in items or []:
                path = item.get("path") or item.get("name")
                dev = {
                    "name": path,
                    "path": path,
                    "kname": item.get("kname"),
                    "pkname": item.get("pkname"),
                    "type": item.get("type"),
                    "size": utils.format_size(item.get("size")) if isinstance(item.get("size"), int) else item.get("size"),
                    "fstype": item.get("fstype") or "",
                    "mountpoint": item.get("mountpoint") or "",
                    "model": item.get("model") or "",
                    "serial": item.get("serial") or "",
                    "rota": item.get("rota"),
                    "ro": item.get("ro"),
                    "rm": item.get("rm"),
                    "tran": item.get("tran") or "",
                    "eligible": item.get("type") == "disk" and not item.get("mountpoint") and item.get("ro") != 1,
                }
                all_devices.append(dev)
                flatten(item.get("children"))

        flatten(data.get("blockdevices"))
        devices = [d for d in all_devices if d.get("eligible")]
        return {"all_devices": all_devices, "devices": devices, "platform": "linux"}

    def _cmd_allowed_action(self, command: str, *args, **kwargs):
        if command == "scrub_pool":
            pool_name = args[0] if args else kwargs.get("pool_name")
            stop = kwargs.get("stop", False)
            cmd = ["zpool", "scrub"]
            if stop:
                cmd.append("-s")
            cmd.append(pool_name)
        elif command == "clear_pool_errors":
            pool_name = args[0] if args else kwargs.get("pool_name")
            cmd = ["zpool", "clear", pool_name]
        elif command == "mount_dataset":
            dataset = args[0] if args else kwargs.get("full_dataset_name")
            cmd = ["zfs", "mount", dataset]
        elif command == "unmount_dataset":
            dataset = args[0] if args else kwargs.get("full_dataset_name")
            cmd = ["zfs", "unmount", dataset]
        else:
            raise ZfsCommandError(f"SSH action '{command}' is not allowed")

        if any(part is None or part == "" for part in cmd):
            raise ZfsCommandError(f"Missing required argument for SSH action '{command}'")
        rc, out, err = self._run_remote(cmd)
        self._raise_if_failed(rc, err, cmd, f"Failed to execute SSH action '{command}'.")
        return out.strip()

    def get_all_zfs_data(self) -> List[Pool]:
        try:
            pools_raw_data = self._send_request("list_pools")["data"]
            items_raw_data = self._send_request("list_all_datasets_snapshots")["data"]
        except Exception as e:
            raise ZfsCommandError(f"Failed initial data fetch: {e}") from e

        pool_statuses = {}
        pool_vdev_trees = {}
        for pool_props in pools_raw_data:
            pool_name = pool_props.get("name")
            if not pool_name:
                continue
            try:
                pool_statuses[pool_name] = self._send_request("get_pool_status", pool_name)["data"]
            except Exception as e:
                pool_statuses[pool_name] = f"Error fetching status: {e}"
            try:
                structure = self._send_request("get_pool_status_structure", pool_name)["data"]
                pool_vdev_trees[pool_name] = structure.get("pools", {}).get(pool_name, {}).get("vdev_tree", {})
            except Exception:
                pool_vdev_trees[pool_name] = {}

        flat_list: List[ZfsObject] = []
        for props in pools_raw_data:
            pool_name = props.get("name", "?")
            flat_list.append(Pool(
                name=pool_name,
                health=props.get("health", "?"),
                size=utils.parse_size(props.get("size")),
                alloc=utils.parse_size(props.get("alloc")),
                free=utils.parse_size(props.get("free")),
                frag=props.get("frag", "-"),
                cap=props.get("cap", "-"),
                dedup=props.get("dedup", "?"),
                guid=props.get("guid", ""),
                properties=props,
                status_details=pool_statuses.get(pool_name, "Status unavailable"),
                vdev_tree=pool_vdev_trees.get(pool_name, {}),
            ))

        for props in items_raw_data:
            item_type = props.get("type")
            name = props.get("name", "?")
            if not name or name == "?":
                continue
            if item_type == "snapshot":
                ds_name, s_name = (name.rsplit("@", 1) + [""])[:2] if "@" in name else ("", "")
                if not ds_name:
                    continue
                p_name = ds_name.split("/")[0] if "/" in ds_name else ds_name
                snap = Snapshot(
                    name=s_name,
                    pool_name=p_name,
                    dataset_name=ds_name,
                    used=utils.parse_size(props.get("used")),
                    referenced=utils.parse_size(props.get("referenced")),
                    creation_time=props.get("creation", "-"),
                    properties=props,
                )
                snap.obj_type = "snapshot"
                snap.properties["full_snapshot_name"] = name
                flat_list.append(snap)
            elif item_type in ["filesystem", "volume"]:
                p_name = name.split("/")[0] if "/" in name else name
                encryption_prop = props.get("encryption", "off")
                flat_list.append(Dataset(
                    name=name,
                    pool_name=p_name,
                    used=utils.parse_size(props.get("used")),
                    available=utils.parse_size(props.get("available")),
                    referenced=utils.parse_size(props.get("referenced")),
                    mountpoint=props.get("mountpoint", "-"),
                    obj_type="volume" if item_type == "volume" else "dataset",
                    properties=props,
                    is_encrypted=encryption_prop not in ("off", "-", None),
                    is_mounted=(props.get("mounted", "no") == "yes"),
                ))

        return build_zfs_hierarchy(flat_list)

    def get_all_properties_with_sources(self, obj_name: str) -> Tuple[bool, Dict[str, Dict[str, str]], str]:
        try:
            return True, self._send_request("get_all_properties_with_sources", obj_name)["data"], ""
        except Exception as e:
            return False, {}, str(e)

    def execute_generic_action(self, command: str, success_msg: str, *args, **kwargs) -> Tuple[bool, str]:
        response = self._send_request(command, *args, **kwargs)
        data = response.get("data")
        return True, f"{success_msg}{f': {data}' if data else ''}"

    def list_importable_pools(self, search_dirs: Optional[List[str]] = None) -> Tuple[bool, str, List[Dict[str, str]]]:
        try:
            return True, "", self._send_request("list_importable_pools", search_dirs=search_dirs)["data"]
        except Exception as e:
            return False, str(e), []

    def list_block_devices(self) -> Dict[str, Any]:
        try:
            return self._send_request("list_block_devices", timeout=constants.CLIENT_REQUEST_TIMEOUT)["data"]
        except Exception as e:
            return {"error": str(e), "all_devices": [], "devices": [], "platform": "linux"}

    def is_connection_healthy(self) -> bool:
        if not self._client:
            return False
        transport = self._client.get_transport()
        if not transport or not transport.is_active():
            return False
        now = time.time()
        if now - self._last_health_check < self.reconnect_ttl:
            return True
        try:
            stdin, stdout, stderr = self._client.exec_command("true", timeout=5.0)
            rc = stdout.channel.recv_exit_status()
            self._last_health_check = now
            return rc == 0
        except Exception as e:
            self._last_error = str(e)
            return False

    def get_connection_error(self) -> Optional[str]:
        return self._last_error
