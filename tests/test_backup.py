import json
import logging
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

from kdbx_backup import service as app


def fixture(value=b"a"):
    # Synthetic header fixture, not a decryptable database and not user data.
    return struct.pack("<III", 0x9AA2D903, 0xB54BFB67, 0x00040001) + value * 116


class FakeRclone:
    def __init__(self, source):
        self.source = source
        self.mutate = False
        self.fail_targets = set()
        self.uploads = []
        self.probes = []
        self.fail_probes = set()

    def resolve(self, source):
        return source

    def stat(self, source):
        stat = self.source.stat()
        return {"Size": stat.st_size, "ModTime": stat.st_mtime_ns}

    def download(self, source, destination):
        shutil.copyfile(self.source, destination)
        if self.mutate:
            self.source.write_bytes(fixture(b"b"))

    def upload(self, source, destination, digest):
        if any(destination.startswith(prefix) for prefix in self.fail_targets):
            raise app.BackupError("provider unavailable")
        if app.sha256(source) != digest:
            raise app.BackupError("bad hash")
        self.uploads.append(destination)

    def probe(self, destination):
        self.probes.append(destination)
        if destination in self.fail_probes:
            raise app.BackupError("target authorization unavailable")


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.kdbx"
        self.source.write_bytes(fixture())
        self.store = app.Store(self.root / "data")
        self.config = {
            "source": "onedrive:passwords.kdbx", "settle_seconds": 0,
            "max_file_bytes": 1000, "retry_seconds": 1, "health_grace_seconds": 900,
            "targets": [{"name": "a", "path": "a:archive"}, {"name": "b", "path": "b:archive"}],
        }
        self.remote = FakeRclone(self.source)
        self.service = app.Backup(self.config, self.store, self.remote)

    def tearDown(self):
        self.temporary.cleanup()

    def count(self):
        return self.store.summary(self.config["targets"])["snapshots"]

    def test_duplicate_skipped_but_reverting_to_older_content_is_a_new_version(self):
        first = self.service.scan()
        self.assertIsNone(self.service.scan())
        self.source.write_bytes(fixture(b"b"))
        second = self.service.scan()
        self.source.write_bytes(fixture())
        third = self.service.scan()
        self.assertEqual(self.count(), 3)
        self.assertEqual(len({first, second, third}), 3)
        self.assertEqual((self.store.archives / first).read_bytes(), fixture())
        self.assertEqual(app.sha256(self.store.archives / first), app.sha256(self.store.archives / third))

    def test_source_deleted_never_removes_history_and_pending_delivery_still_works(self):
        name = self.service.scan()
        self.source.unlink()
        with self.assertRaises(FileNotFoundError):
            self.service.scan()
        self.assertTrue(self.service.deliver_one(self.config["targets"][0]))
        self.assertTrue((self.store.archives / name).exists())
        self.assertEqual(self.count(), 1)

    def test_concurrent_source_change_rejected(self):
        self.remote.mutate = True
        with self.assertRaisesRegex(app.BackupError, "source changed"):
            self.service.scan()
        self.assertEqual(self.count(), 0)
        self.assertEqual(list(self.store.staging.iterdir()), [])

    def test_empty_invalid_and_oversize_sources_preserve_prior_snapshot(self):
        self.service.scan()
        for payload in (b"", b"not a kdbx" * 12, fixture() * 10):
            self.source.write_bytes(payload)
            with self.assertRaises(app.BackupError):
                self.service.scan()
        self.assertEqual(self.count(), 1)

    def test_one_provider_failure_does_not_block_other_provider_or_new_snapshots(self):
        self.service.scan()
        a, b = self.config["targets"]
        self.remote.fail_targets.add("a:")
        self.service.deliver_one(a)
        self.service.deliver_one(b)
        self.assertEqual(self.store.summary([a])["targets"]["a"]["pending"], 1)
        self.assertEqual(self.store.summary([b])["targets"]["b"]["pending"], 0)
        self.assertFalse(self.service.status()["healthy"])
        self.source.write_bytes(fixture(b"b"))
        self.service.scan()
        self.service.deliver_one(b)
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.store.summary([b])["targets"]["b"]["pending"], 0)

    def test_delivery_state_and_retry_survive_restart(self):
        self.service.scan()
        a, b = self.config["targets"]
        self.service.deliver_one(b)
        self.remote.fail_targets.add("a:")
        self.service.deliver_one(a)
        restarted = app.Store(self.store.root)
        restarted.recover()
        self.assertIsNone(restarted.pending(a["path"]))  # Backoff survived restart.
        self.assertIsNone(restarted.pending(b["path"]))  # Completion survived restart.
        with restarted.connect() as db:
            row = db.execute("SELECT attempts, done FROM deliveries WHERE destination=?", (a["path"],)).fetchone()
            self.assertEqual(tuple(row), (1, 0))
            db.execute("UPDATE deliveries SET next_try=0")
        self.remote.fail_targets.clear()
        service = app.Backup(self.config, restarted, self.remote)
        service.deliver_one(a)
        self.assertEqual(restarted.summary([a])["targets"]["a"]["pending"], 0)

    def test_new_destination_backfills_all_snapshots(self):
        self.service.scan()
        self.source.write_bytes(fixture(b"b"))
        self.service.scan()
        target = {"name": "new", "path": "new:archive"}
        self.assertEqual(self.store.summary([target])["targets"]["new"]["pending"], 2)
        self.service.deliver_one(target)
        self.service.deliver_one(target)
        self.assertFalse(self.service.deliver_one(target))
        self.assertEqual(self.store.summary([target])["targets"]["new"]["pending"], 0)

    def test_relocating_data_directory_preserves_snapshots_and_delivery_progress(self):
        self.service.scan()
        for target in self.config["targets"]:
            self.service.deliver_one(target)
        destination = self.root / "external-data/default"
        shutil.copytree(self.store.root, destination)
        relocated = app.Store(destination)
        relocated.recover()
        service = app.Backup(self.config, relocated, self.remote)
        self.assertIsNone(service.scan())
        for target in self.config["targets"]:
            self.assertFalse(service.deliver_one(target))
        result = relocated.summary(self.config["targets"])
        self.assertEqual(result["snapshots"], 1)
        self.assertTrue(all(target["pending"] == 0 for target in result["targets"].values()))

    def test_corrupt_local_snapshot_never_uploaded(self):
        name = self.service.scan()
        (self.store.archives / name).write_bytes(fixture(b"x"))
        self.service.deliver_one(self.config["targets"][0])
        self.assertEqual(self.remote.uploads, [])
        with self.assertRaisesRegex(app.BackupError, "corrupted"):
            self.store.recover()

    def test_missing_local_snapshot_not_silently_forgotten(self):
        name = self.service.scan()
        (self.store.archives / name).unlink()
        with self.assertRaisesRegex(app.BackupError, "missing"):
            self.store.recover()

    def test_crash_after_archive_publish_recovers_before_enqueue(self):
        name = self.service.scan()
        (self.store.archives / (name + ".sha256")).unlink()
        with self.store.connect() as db:
            db.execute("DELETE FROM snapshots")
        self.store.recover()
        self.assertEqual(self.count(), 1)
        self.assertTrue((self.store.archives / (name + ".sha256")).exists())
        self.assertIsNotNone(self.store.pending("new:archive"))

    def test_checksum_sidecar_corruption_rejected(self):
        name = self.service.scan()
        (self.store.archives / (name + ".sha256")).write_text("bad")
        with self.assertRaisesRegex(app.BackupError, "sidecar mismatch"):
            self.store.recover()

    def test_lost_sqlite_can_be_rebuilt_from_archive_files(self):
        self.service.scan()
        self.source.write_bytes(fixture(b"b"))
        self.service.scan()
        self.store.database.unlink()
        restarted = app.Store(self.store.root)
        restarted.recover()
        self.assertEqual(restarted.summary([])["snapshots"], 2)

    def test_idle_target_is_checked_daily_without_creating_a_snapshot(self):
        target = self.config["targets"][0]
        with patch.object(app.time, "monotonic", return_value=100) as clock:
            self.assertTrue(self.service.check_target(target))
            clock.return_value = 86499
            self.assertFalse(self.service.check_target(target))
            clock.return_value = 86500
            self.assertTrue(self.service.check_target(target))
        self.assertEqual(self.remote.probes, [target["path"]] * 2)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.remote.uploads, [])

    def test_restart_checks_immediately_and_preserves_previous_check_and_history(self):
        self.service.scan()
        for target in self.config["targets"]:
            self.service.deliver_one(target)
            self.service.check_target(target)
        target = self.config["targets"][0]
        previous = self.store.target_check(target["path"])
        store = app.Store(self.store.root)
        store.recover()
        self.assertEqual(store.target_check(target["path"]), previous)
        restarted = app.Backup(self.config, store, self.remote)
        self.assertTrue(restarted.check_target(target))
        self.assertEqual(self.count(), 1)
        self.assertIsNone(store.pending(target["path"]))
        self.assertEqual(self.remote.probes.count(target["path"]), 2)

    def test_probe_failure_retries_recovers_and_does_not_block_other_backups(self):
        a, b = self.config["targets"]
        self.remote.fail_probes.add(a["path"])
        with patch.object(app.time, "monotonic", return_value=100) as clock:
            self.assertTrue(self.service.check_target(a))
            self.assertTrue(self.service.check_target(b))
            self.assertFalse(self.service.status()["healthy"])
            self.assertEqual(self.store.target_check(a["path"])["failures"], 1)
            clock.return_value = 100.5
            self.assertFalse(self.service.check_target(a))
            clock.return_value = 101
            self.assertTrue(self.service.check_target(a))
            self.assertEqual(self.store.target_check(a["path"])["failures"], 2)
            self.service.scan()
            self.service.deliver_one(b)
            self.assertEqual(self.store.summary([b])["targets"]["b"]["pending"], 0)
            self.remote.fail_probes.clear()
            clock.return_value = 103
            self.assertTrue(self.service.check_target(a))
        check = self.store.target_check(a["path"])
        self.assertIsNone(check["error"])
        self.assertEqual(check["failures"], 0)
        self.assertIsNotNone(check["last_success"])
        self.assertEqual(self.count(), 1)

    def test_successful_probe_does_not_clear_failed_upload(self):
        a, b = self.config["targets"]
        self.service.scan()
        self.remote.fail_targets.add("a:")
        self.service.deliver_one(a)
        self.service.check_target(a)
        self.service.check_target(b)
        status = self.service.status()
        self.assertFalse(status["healthy"])
        self.assertIn("a", status["target_errors"])
        self.assertEqual(status["targets"]["a"]["connection_check"]["state"], "ok")

    def test_probe_error_and_overdue_check_affect_health_without_uploads(self):
        self.config["target_check_seconds"] = 10
        with patch.object(app.time, "time", return_value=1000) as clock:
            self.service.last_source_ok = 1000
            for target in self.config["targets"]:
                self.service.check_target(target)
            self.assertTrue(self.service.status()["healthy"])
            clock.return_value = 1911
            self.service.last_source_ok = 1911
            status = self.service.status()
            self.assertFalse(status["healthy"])
            self.assertEqual(status["targets"]["a"]["connection_check"]["state"], "stale")
            self.assertIn("a", status["target_errors"])

    def test_check_pending_is_explicit_before_the_first_probe(self):
        status = self.service.status()
        check = status["targets"]["a"]["connection_check"]
        self.assertEqual(check["state"], "pending")
        self.assertIsNone(check["last_attempt"])
        self.assertIsNone(check["last_success"])
        self.assertFalse(status["healthy"])

    def test_shutdown_during_probe_does_not_start_an_upload(self):
        self.service.scan()
        with patch.object(self.remote, "probe", side_effect=lambda _: self.service.stop.set()):
            self.service.target_loop(self.config["targets"][0])
        self.assertEqual(self.remote.uploads, [])
        self.assertIsNotNone(self.store.pending(self.config["targets"][0]["path"]))

    def test_file_logs_rotate_and_exclude_provider_response_credentials(self):
        level = app.LOG.level
        app.LOG.setLevel(logging.INFO)
        handler = app.configure_file_logging(self.store.root, max_bytes=700, backups=2)
        try:
            for index in range(40):
                app.LOG.info("target_check_ok target=a event=%s", index)
            failure = app.subprocess.CompletedProcess(
                ["rclone"], 1, stdout=b"",
                stderr=b"provider echoed synthetic-credential-should-not-appear")
            self.service.rclone = app.Rclone()
            with patch.object(app.subprocess, "run", return_value=failure):
                self.service.check_target(self.config["targets"][0])
            handler.flush()
            paths = list((self.store.root / "logs").glob("service.log*"))
            self.assertEqual(len(paths), 3)
            content = "".join(path.read_text() for path in paths)
            self.assertIn("target_check_ok", content)
            self.assertIn("target_check_failed", content)
            self.assertNotIn("synthetic-credential-should-not-appear", content)
            self.assertNotIn("event=0\n", content)
            self.assertEqual((self.store.root / "logs/service.log").stat().st_mode & 0o777, 0o600)
        finally:
            app.LOG.removeHandler(handler)
            handler.close()
            app.LOG.setLevel(level)


class RcloneTests(unittest.TestCase):
    def test_probe_reads_only_directory_metadata_and_rejects_file_targets(self):
        class Metadata(app.Rclone):
            def run(self, *args, **kwargs):
                self.arguments = args
                return json.dumps(self.value).encode()
        remote = Metadata()
        remote.value = {"IsDir": True}
        remote.probe("gdrive:archives")
        self.assertEqual(remote.arguments, ("lsjson", "--stat", "--", "gdrive:archives"))
        for value in ({"IsDir": False}, {}, []):
            remote.value = value
            with self.assertRaises(app.BackupError):
                remote.probe("gdrive:archives")

    def test_root_discovery_refuses_ambiguous_or_missing_database(self):
        class Listing(app.Rclone):
            def run(self, *args, **kwargs):
                return json.dumps(self.entries).encode()
        remote = Listing()
        remote.entries = [{"Name": "private.kdbx", "IsDir": False}, {"Name": "other.txt", "IsDir": False}]
        self.assertEqual(remote.resolve("onedrive:"), "onedrive:private.kdbx")
        remote.entries.append({"Name": "second.KDBX", "IsDir": False})
        with self.assertRaisesRegex(app.BackupError, "exactly one"):
            remote.resolve("onedrive:")
        remote.entries = []
        with self.assertRaises(app.BackupError):
            remote.resolve("onedrive:")

    def test_remote_readback_detects_same_size_wrong_content_after_skipped_upload(self):
        class WrongRemote(app.Rclone):
            def run(self, *args, output=None):
                if args[0] == "cat":
                    output.write(b"wrong")
                else:
                    self.arguments = args
        remote = WrongRemote()
        with self.assertRaisesRegex(app.BackupError, "verification failed"):
            remote.upload("local", "remote:file", "0" * 64)
        self.assertIn("--immutable", remote.arguments)
        self.assertEqual(remote.arguments[0], "copy")
        self.assertIn("--include", remote.arguments)
        self.assertEqual(remote.arguments[-2], Path("."))
        self.assertNotIn("--ignore-times", remote.arguments)

    def test_config_rejects_empty_duplicate_and_invalid_intervals(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            good = {"enabled": True, "source": "onedrive:", "targets": [{"name": "a", "path": "a:backup"}]}
            path.write_text(json.dumps(good))
            self.assertEqual(app.load_config(path)["poll_seconds"], 60)
            self.assertEqual(app.load_config(path)["target_check_seconds"], 86400)
            for change in ({"targets": []}, {"poll_seconds": 0}, {"enabled": "true"},
                           {"source": ""}, {"targets": good["targets"] * 2},
                           {"target_check_seconds": 0}, {"target_check_seconds": -1},
                           {"target_check_seconds": True}):
                path.write_text(json.dumps({**good, **change}))
                with self.assertRaises(app.BackupError):
                    app.load_config(path)


if __name__ == "__main__":
    unittest.main()
