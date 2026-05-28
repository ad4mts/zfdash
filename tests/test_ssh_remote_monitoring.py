import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from control_center_manager import AgentConnection
from ssh_zfs_client import SshZfsManagerClient
from zfs_manager import ZfsCommandError


def make_ssh_client(allow_actions=False):
    client = SshZfsManagerClient.__new__(SshZfsManagerClient)
    client.allow_actions = allow_actions
    client.commands = []

    def fake_run_remote(argv, timeout=None):
        client.commands.append(argv)
        return 0, "ok", ""

    client._run_remote = fake_run_remote
    return client


def test_ssh_connection_serialization_round_trip():
    conn = AgentConnection(
        "pve",
        "192.168.15.10",
        22,
        connection_type="ssh",
        ssh_user="root",
        auth_method="key",
        ssh_key_path="/root/.ssh/id_ed25519",
        allow_ssh_actions=True,
    )

    restored = AgentConnection.from_dict(conn.to_dict())

    assert restored.connection_type == "ssh"
    assert restored.host == "192.168.15.10"
    assert restored.port == 22
    assert restored.ssh_user == "root"
    assert restored.auth_method == "key"
    assert restored.ssh_key_path == "/root/.ssh/id_ed25519"
    assert restored.allow_ssh_actions is True


def test_ssh_remote_blocks_mutating_actions_by_default():
    client = make_ssh_client(allow_actions=False)

    with pytest.raises(ZfsCommandError, match="read-only"):
        client._send_request("scrub_pool", "tank")


def test_ssh_remote_rejects_destructive_actions_even_when_actions_enabled():
    client = make_ssh_client(allow_actions=True)

    with pytest.raises(ZfsCommandError):
        client._send_request("destroy_pool", "tank")


def test_ssh_remote_allows_allowlisted_actions_when_enabled():
    client = make_ssh_client(allow_actions=True)

    response = client._send_request("scrub_pool", "tank")

    assert response["status"] == "success"
    assert client.commands == [["zpool", "scrub", "tank"]]

