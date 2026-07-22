import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import backup_routes


class RecordingClient:
    def __init__(self):
        self.requests = []
        self.closed = False

    def _send_request(self, command, *args, **kwargs):
        self.requests.append((command, args, kwargs))
        return {"status": "success", "data": {"job_id": "job-1"}}

    def close(self):
        self.closed = True


def call_route(route, payload):
    app = Flask(__name__)
    with app.test_request_context(json=payload):
        response = route.__wrapped__()
    return response


class BackupRouteTimeoutTests(unittest.TestCase):
    def test_send_to_agent_has_no_overall_daemon_timeout(self):
        client = RecordingClient()
        with patch.object(backup_routes, "_zfs_client_getter", lambda: client):
            response = call_route(backup_routes.send_to_agent, {
                "source_dataset": "tank/data@snapshot",
                "dest_host": "backup.example.com",
                "dest_password": "secret",
                "dest_dataset": "backup/data",
            })

        self.assertTrue(response.get_json()["success"])
        self.assertEqual(client.requests[0][0], "send_backup")
        self.assertIsNone(client.requests[0][2]["timeout"])

    def test_resume_backup_has_no_overall_daemon_timeout(self):
        client = RecordingClient()
        with patch.object(backup_routes, "_zfs_client_getter", lambda: client):
            response = call_route(backup_routes.resume_backup, {
                "job_id": "job-1",
                "dest_password": "secret",
            })

        self.assertTrue(response.get_json()["success"])
        self.assertEqual(client.requests[0][0], "resume_backup")
        self.assertIsNone(client.requests[0][2]["timeout"])

    def test_agent_to_agent_has_no_overall_daemon_timeout(self):
        client = RecordingClient()
        with patch.object(
            backup_routes,
            "_create_temp_client",
            lambda host, port, password, use_tls: (client, None),
        ):
            response = call_route(backup_routes.agent_to_agent, {
                "sender_host": "sender.example.com",
                "sender_password": "sender-secret",
                "source_dataset": "tank/data@snapshot",
                "dest_host": "receiver.example.com",
                "dest_password": "receiver-secret",
                "dest_dataset": "backup/data",
            })

        self.assertTrue(response.get_json()["success"])
        self.assertEqual(client.requests[0][0], "send_backup")
        self.assertIsNone(client.requests[0][2]["timeout"])
        self.assertTrue(client.closed)

    def test_local_backup_has_no_overall_daemon_timeout(self):
        client = RecordingClient()
        with patch.object(backup_routes, "_zfs_client_getter", lambda: client):
            response = call_route(backup_routes.local_backup, {
                "source_snapshot": "tank/data@snapshot",
                "dest_dataset": "backup/data",
            })

        self.assertTrue(response.get_json()["success"])
        self.assertEqual(client.requests[0][0], "local_backup")
        self.assertIsNone(client.requests[0][2]["timeout"])

    def test_export_to_file_has_no_overall_daemon_timeout(self):
        client = RecordingClient()
        with patch.object(backup_routes, "_zfs_client_getter", lambda: client):
            response = call_route(backup_routes.export_to_file, {
                "source_snapshot": "tank/data@snapshot",
                "file_path": "/backups/data.zfs",
            })

        self.assertTrue(response.get_json()["success"])
        self.assertEqual(client.requests[0][0], "export_to_file")
        self.assertIsNone(client.requests[0][2]["timeout"])

    def test_send_to_ssh_has_no_overall_daemon_timeout(self):
        client = RecordingClient()
        with patch.object(backup_routes, "_zfs_client_getter", lambda: client):
            response = call_route(backup_routes.send_to_ssh, {
                "source_snapshot": "tank/data@snapshot",
                "ssh_host": "backup.example.com",
                "ssh_user": "root",
                "dest_dataset": "backup/data",
            })

        self.assertTrue(response.get_json()["success"])
        self.assertEqual(client.requests[0][0], "send_ssh")
        self.assertIsNone(client.requests[0][2]["timeout"])


if __name__ == "__main__":
    unittest.main()