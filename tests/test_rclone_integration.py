"""Opt-in real-rclone smoke tests. Only synthetic data and temporary directories."""
import os
import json
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from kdbx_backup import service as app
from scripts import manage


@unittest.skipUnless(os.environ.get("RCLONE_INTEGRATION") == "1" and shutil.which("rclone"),
                     "enable RCLONE_INTEGRATION=1 inside the Docker image")
class RealRcloneTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source_dir = self.root / "source"
        self.source_dir.mkdir()
        self.source = self.source_dir / "passwords.kdbx"
        self.payload = struct.pack("<III", 0x9AA2D903, 0xB54BFB67, 0x00040001) + b"a" * 116
        self.source.write_bytes(self.payload)
        config_path = self.root / "rclone.conf"
        config_path.write_text("\n".join("[%s]\ntype = alias\nremote = %s\n" % (name, self.root / folder)
                                        for name, folder in (("onedrive", "source"), ("gdrive", "google"), ("jianguoyun", "nuts"))))
        self.environment = patch.dict(os.environ, {"RCLONE_CONFIG": str(config_path)})
        self.environment.start()
        self.store = app.Store(self.root / "data")
        self.config = {"source": "onedrive:", "settle_seconds": 0, "max_file_bytes": 1000,
                       "retry_seconds": 1, "health_grace_seconds": 900,
                       "targets": [{"name": "google", "path": "gdrive:KDBX-Backups"},
                                   {"name": "nuts", "path": "jianguoyun:KDBX-Backups"}]}
        self.rclone = app.Rclone(timeout=20)
        self.service = app.Backup(self.config, self.store, self.rclone)

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_capture_verify_restart_delete_and_backfill(self):
        first = self.service.scan()
        self.assertIsNone(self.service.scan())
        for target in self.config["targets"]:
            self.service.deliver_one(target)
        self.assertTrue(self.service.status()["healthy"])
        for folder in ("google", "nuts"):
            path = self.root / folder / "KDBX-Backups" / first
            self.assertEqual(path.read_bytes(), self.payload)
            self.assertIn(app.sha256(path), Path(str(path) + ".sha256").read_text())
        self.source.write_bytes(self.payload[:-1] + b"b")
        second = self.service.scan()
        self.source.unlink()
        with self.assertRaises(app.BackupError):
            self.service.scan()
        store = app.Store(self.store.root)
        store.recover()
        service = app.Backup(self.config, store, self.rclone)
        for target in self.config["targets"]:
            self.assertTrue(service.deliver_one(target))
            self.assertFalse(service.deliver_one(target))
        self.assertEqual((self.root / "nuts" / "KDBX-Backups" / second).read_bytes(), self.payload[:-1] + b"b")
        self.assertTrue((self.root / "nuts" / "KDBX-Backups" / first).exists())
        self.assertEqual(store.summary(self.config["targets"])["snapshots"], 2)

    def test_remote_existing_different_content_never_overwritten(self):
        name = self.service.scan()
        destination = self.root / "google" / "KDBX-Backups" / name
        destination.parent.mkdir(parents=True)
        wrong = self.payload[:-1] + b"x"
        destination.write_bytes(wrong)
        self.service.deliver_one(self.config["targets"][0])
        self.assertEqual(destination.read_bytes(), wrong)
        self.assertEqual(self.store.summary(self.config["targets"])["targets"]["google"]["pending"], 1)
        self.assertIn("google", self.service.target_errors)

    def test_webdav_readback_and_same_size_conflict_preserves_remote_bytes(self):
        directory = self.root / "webdav"
        directory.mkdir()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = subprocess.Popen(["rclone", "serve", "webdav", str(directory),
                                   "--addr", "127.0.0.1:%s" % port],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    if server.poll() is not None:
                        self.fail("test WebDAV server exited")
                    time.sleep(0.05)
            else:
                self.fail("test WebDAV server did not start")
            with Path(os.environ["RCLONE_CONFIG"]).open("a") as config:
                config.write("\n[webdav]\ntype = webdav\nvendor = other\nurl = http://127.0.0.1:%s/\n" % port)
            name = self.service.scan()
            target = {"name": "webdav", "path": "webdav:archives"}
            self.service.deliver_one(target)
            path = directory / "archives" / name
            self.assertEqual(path.read_bytes(), self.payload)
            self.assertEqual(self.store.summary([target])["targets"]["webdav"]["pending"], 0)
            wrong = self.payload[:-1] + b"x"
            path.write_bytes(wrong)
            with self.assertRaises(app.BackupError):
                self.rclone.upload(self.store.archives / name, target["path"], app.sha256(self.store.archives / name))
            self.assertEqual(path.read_bytes(), wrong)
        finally:
            server.terminate()
            server.wait(timeout=10)


@unittest.skipUnless(os.environ.get("RCLONE_INTEGRATION") == "1" and shutil.which("rclone"),
                     "enable RCLONE_INTEGRATION=1 inside the Docker image")
class ProfileProcessTests(unittest.TestCase):
    def test_two_accounts_with_identical_filenames_and_remote_names_are_isolated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "examples").mkdir()
            template = {"enabled": False, "source": "onedrive:", "poll_seconds": 1,
                        "settle_seconds": 0, "command_timeout_seconds": 20, "retry_seconds": 1,
                        "targets": [{"name": "drive", "path": "gdrive:KDBX-Backups"}]}
            (root / "examples/config.example.json").write_text(json.dumps(template))
            cloud = root / "shared-cloud"
            processes = []
            instances = {}
            storages = {}

            def payload(value):
                return struct.pack("<III", 0x9AA2D903, 0xB54BFB67, 0x00040001) + value * 116

            def wait_for(condition):
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    self.assertTrue(all(process.poll() is None for process in processes),
                                    "a profile service exited unexpectedly")
                    if condition():
                        return
                    time.sleep(0.1)
                self.fail("profile backup did not complete before deadline")

            try:
                for name, value in (("me", b"a"), ("family", b"b")):
                    instance = manage.initialize(root, name)
                    storages[name] = manage.data_directory(root, name)
                    source = root / (name + "-onedrive")
                    source.mkdir()
                    (source / "passwords.kdbx").write_bytes(payload(value))
                    credentials = instance / ".secrets/rclone/rclone.conf"
                    credentials.write_text("[onedrive]\ntype = alias\nremote = %s\n"
                                           "[gdrive]\ntype = alias\nremote = %s\n" % (source, cloud))
                    config_path = instance / "config/config.json"
                    config = json.loads(config_path.read_text())
                    config["enabled"] = True
                    config_path.write_text(json.dumps(config))
                    environment = manage.Manager(root, profile=name).environment
                    environment["RCLONE_CONFIG"] = str(credentials)
                    processes.append(subprocess.Popen(
                        [sys.executable, str(Path(app.__file__).resolve()), "run", "--config", str(config_path),
                         "--data", str(storages[name])], env=environment,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                    instances[name] = instance
                wait_for(lambda: all(len(list((cloud / "KDBX-Backups" / name).glob("*.kdbx.sha256"))) == 1
                                     for name in instances))
                for name, value in (("me", b"a"), ("family", b"b")):
                    uploaded = list((cloud / "KDBX-Backups" / name).glob("*.kdbx"))
                    self.assertEqual(len(uploaded), 1)
                    self.assertEqual(uploaded[0].read_bytes(), payload(value))
                # One account loses its source while the other continues saving versions.
                (root / "me-onedrive/passwords.kdbx").unlink()
                (root / "family-onedrive/passwords.kdbx").write_bytes(payload(b"c"))
                wait_for(lambda: len(list((cloud / "KDBX-Backups/family").glob("*.kdbx.sha256"))) == 2)
                self.assertEqual(len(list((cloud / "KDBX-Backups/me").glob("*.kdbx"))), 1)
                self.assertEqual(len(list((storages["me"] / "snapshots").glob("*.kdbx"))), 1)
                self.assertEqual(len(list((storages["family"] / "snapshots").glob("*.kdbx"))), 2)
                self.assertEqual({path.read_bytes() for path in (storages["family"] / "snapshots").glob("*.kdbx")},
                                 {payload(b"b"), payload(b"c")})
            finally:
                for process in processes:
                    process.terminate()
                for process in processes:
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
