"""Append-only KDBX snapshots and independently retried cloud deliveries.

No password, key file, database decryption, source write, or delete operation.
"""
import argparse
import concurrent.futures
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid

LOG = logging.getLogger("backup")
SNAPSHOT_NAME = re.compile(r"vault_\d{8}T\d{12}Z_[0-9a-f]{12}_[0-9a-f]{8}\.kdbx")


class BackupError(Exception):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_kdbx(path):
    """Header sanity only; authenticated integrity requires the user's key."""
    path = Path(path)
    with path.open("rb") as stream:
        header = stream.read(12)
    if len(header) != 12 or path.stat().st_size < 64:
        raise BackupError("source is empty or too short to be a KDBX database")
    magic1, magic2, version = struct.unpack("<III", header)
    if (magic1, magic2) != (0x9AA2D903, 0xB54BFB67) or version >> 16 not in (3, 4):
        raise BackupError("source does not have a supported KDBX 3/4 header")


def fsync_dir(path):
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_dir(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        # Keep newly rotated files private even if the caller has a broad umask.
        descriptor = os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            return os.fdopen(descriptor, self.mode, encoding=self.encoding, errors=self.errors)
        except Exception:
            os.close(descriptor)
            raise


def configure_file_logging(data, max_bytes=5 * 1024 * 1024, backups=3):
    directory = Path(data) / "logs"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "service.log"
    handler = PrivateRotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups,
                                         encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    return handler


def load_config(path):
    config = json.loads(Path(path).read_text())
    if not isinstance(config, dict):
        raise BackupError("configuration must be a JSON object")
    if type(config.get("enabled")) is not bool:
        raise BackupError("enabled must be true or false")
    if not isinstance(config.get("source"), str) or not config["source"].strip():
        raise BackupError("source must be a nonempty rclone path")
    defaults = {
        "poll_seconds": 60, "settle_seconds": 3,
        "command_timeout_seconds": 120, "max_file_bytes": 33554432,
        "retry_seconds": 60, "health_grace_seconds": 900,
        "target_check_seconds": 86400,
    }
    for name, default in defaults.items():
        value = config.setdefault(name, default)
        minimum = 0 if name == "settle_seconds" else 1
        if type(value) is not int or value < minimum:
            raise BackupError(name + " must be a valid integer")
    targets = config.get("targets")
    if not isinstance(targets, list) or not 1 <= len(targets) <= 8:
        raise BackupError("configure between one and eight targets")
    names, paths = set(), set()
    for target in targets:
        if not isinstance(target, dict):
            raise BackupError("invalid target")
        name, destination = target.get("name", ""), target.get("path", "")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name):
            raise BackupError("target names must contain only letters, digits, _ or -")
        if not isinstance(destination, str) or not destination.strip():
            raise BackupError("each target needs a path")
        destination = destination.rstrip("/")
        target["path"] = destination
        if name in names or destination in paths:
            raise BackupError("target names and paths must be unique")
        names.add(name)
        paths.add(destination)
    return config


class Rclone:
    def __init__(self, timeout=120, binary="rclone"):
        self.timeout = timeout
        self.binary = binary

    def run(self, *arguments, output=None):
        command = [self.binary, "--ask-password=false", "--retries", "1",
                   "--low-level-retries", "2", "--contimeout", "15s",
                   "--timeout", "60s", "--stats", "0", *map(str, arguments)]
        try:
            result = subprocess.run(command, stdout=output or subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=self.timeout,
                                    check=False, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as error:
            raise BackupError("rclone operation timed out") from error
        except OSError as error:
            raise BackupError("rclone could not be started") from error
        if result.returncode:
            # Avoid logging provider responses, URLs, tokens or filenames.
            raise BackupError("rclone operation failed (exit %s); check authorization, path and network"
                              % result.returncode)
        return result.stdout

    def resolve(self, source):
        if not (source.endswith(":") or source.endswith("/")):
            return source
        listing = json.loads(self.run("lsjson", "--files-only", "--max-depth", "1", "--", source))
        candidates = [entry["Name"] for entry in listing
                      if not entry.get("IsDir") and entry["Name"].lower().endswith(".kdbx")]
        if len(candidates) != 1:
            raise BackupError("source directory must contain exactly one .kdbx; specify its full path")
        return source + ("" if source.endswith((":", "/")) else "/") + candidates[0]

    def stat(self, source):
        value = json.loads(self.run("lsjson", "--stat", "--", source))
        if value.get("IsDir"):
            raise BackupError("source must be a file")
        return {key: value.get(key) for key in ("Size", "ModTime", "ID", "Hashes")}

    def download(self, source, destination):
        self.run("copyto", "--ignore-times", "--", source, destination)

    def probe(self, directory):
        # Read metadata only; do not enumerate archives or create a marker file.
        value = json.loads(self.run("lsjson", "--stat", "--", directory))
        if not isinstance(value, dict) or not value.get("IsDir"):
            raise BackupError("backup target must be an accessible directory")

    def upload(self, source, directory, digest):
        # rclone 1.75.2's single-file copy/copyto path bypasses immutable checks.
        # Force its directory-copy path and include exactly this generated name.
        source = Path(source)
        self.run("copy", "--immutable", "--checksum", "--include", "/" + source.name,
                 "--", source.parent, directory)
        destination = directory + ("" if directory.endswith(":") else "/") + Path(source).name
        # WebDAV may not provide remote checksums. Read back bytes to verify,
        # including on retries where an existing file could be skipped by rclone.
        with tempfile.TemporaryFile() as stream:
            self.run("cat", "--", destination, output=stream)
            stream.seek(0)
            actual = hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else self._hash_stream(stream)
        if actual != digest:
            raise BackupError("remote verification failed; existing archive was not overwritten")

    @staticmethod
    def _hash_stream(stream):
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.archives = self.root / "snapshots"
        self.staging = self.root / "staging"
        for directory in (self.root, self.archives, self.staging):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.database = self.root / "state.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    name TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL, captured REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS deliveries (
                    name TEXT NOT NULL REFERENCES snapshots(name),
                    destination TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_try REAL NOT NULL DEFAULT 0, verified REAL,
                    PRIMARY KEY(name, destination));
                CREATE TABLE IF NOT EXISTS target_checks (
                    destination TEXT PRIMARY KEY,
                    last_attempt REAL NOT NULL, last_success REAL,
                    next_check REAL NOT NULL,
                    failures INTEGER NOT NULL, error TEXT);
            """)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        """Recover a crash between durable file creation and SQLite commit."""
        with self.connect() as db:
            known = {row["name"]: dict(row) for row in db.execute("SELECT * FROM snapshots")}
        for name, record in known.items():
            path = self.archives / name
            if not path.is_file() or sha256(path) != record["sha256"]:
                raise BackupError("local archive missing or corrupted: " + name)
        for path in sorted(self.archives.glob("*.kdbx")):
            if not SNAPSHOT_NAME.fullmatch(path.name):
                raise BackupError("unexpected filename in snapshot directory")
            validate_kdbx(path)
            digest = known[path.name]["sha256"] if path.name in known else sha256(path)
            if digest[:12] != path.name.split("_")[2]:
                raise BackupError("archive filename hash mismatch")
            self.sidecar(path, digest)
            with self.connect() as db:
                db.execute("INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?, ?)",
                           (path.name, digest, path.stat().st_size, self.capture_time(path.name)))
        # Only this application uses staging; abandoned downloads are not archives.
        for path in self.staging.glob("capture-*"):
            if path.is_file():
                path.unlink()

    @staticmethod
    def capture_time(name):
        return dt.datetime.strptime(name.split("_")[1], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=dt.timezone.utc).timestamp()

    @staticmethod
    def sidecar(path, digest):
        sidecar = Path(str(path) + ".sha256")
        content = (digest + "  " + path.name + "\n").encode()
        if sidecar.exists():
            if sidecar.read_bytes() != content:
                raise BackupError("archive checksum sidecar mismatch")
        else:
            atomic_write(sidecar, content)
        return sidecar

    def capture(self, temporary):
        temporary = Path(temporary)
        validate_kdbx(temporary)
        digest = sha256(temporary)
        with self.connect() as db:
            previous = db.execute("SELECT sha256 FROM snapshots ORDER BY captured DESC, name DESC LIMIT 1").fetchone()
        if previous and previous["sha256"] == digest:
            return None
        now = dt.datetime.now(dt.timezone.utc)
        stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        name = "vault_%s_%s_%s.kdbx" % (stamp, digest[:12], uuid.uuid4().hex[:8])
        path = self.archives / name
        os.chmod(temporary, 0o600)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        # Hard link publishes without replacing an existing archive, even on collision.
        os.link(temporary, path)
        fsync_dir(self.archives)
        self.sidecar(path, digest)
        with self.connect() as db:
            db.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?)",
                       (name, digest, path.stat().st_size, now.timestamp()))
        return name

    def enqueue(self, destination):
        with self.connect() as db:
            db.execute("""INSERT OR IGNORE INTO deliveries (name, destination)
                          SELECT name, ? FROM snapshots""", (destination,))

    def pending(self, destination):
        self.enqueue(destination)
        with self.connect() as db:
            row = db.execute("""SELECT s.*, d.attempts FROM deliveries d
                                JOIN snapshots s ON s.name=d.name
                                WHERE destination=? AND done=0 AND next_try<=?
                                ORDER BY captured, name LIMIT 1""",
                             (destination, time.time())).fetchone()
        return dict(row) if row else None

    def delivered(self, name, destination):
        with self.connect() as db:
            db.execute("UPDATE deliveries SET done=1, verified=? WHERE name=? AND destination=?",
                       (time.time(), name, destination))

    def failed(self, name, destination, attempts, base_retry):
        delay = min(base_retry * (2 ** min(attempts, 10)), 3600)
        with self.connect() as db:
            db.execute("""UPDATE deliveries SET attempts=attempts+1, next_try=?
                          WHERE name=? AND destination=?""", (time.time() + delay, name, destination))

    def target_check(self, destination):
        with self.connect() as db:
            row = db.execute("""SELECT last_attempt, last_success, next_check,
                                       failures, error FROM target_checks
                                WHERE destination=?""", (destination,)).fetchone()
        return dict(row) if row else {
            "last_attempt": None, "last_success": None, "next_check": None,
            "failures": 0, "error": None,
        }

    def record_target_check(self, destination, checked, delay, error):
        with self.connect() as db:
            db.execute("""INSERT INTO target_checks VALUES (?, ?, ?, ?, ?, ?)
                          ON CONFLICT(destination) DO UPDATE SET
                            last_attempt=excluded.last_attempt,
                            last_success=COALESCE(excluded.last_success, target_checks.last_success),
                            next_check=excluded.next_check,
                            failures=CASE WHEN excluded.error IS NULL THEN 0
                                          ELSE target_checks.failures+1 END,
                            error=excluded.error""",
                       (destination, checked, checked if error is None else None,
                        checked + delay, 0 if error is None else 1, error))

    def summary(self, targets):
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*), MAX(captured) FROM snapshots").fetchone()
            result = {"snapshots": total[0], "last_snapshot": total[1], "targets": {}}
            for target in targets:
                row = db.execute("""SELECT COUNT(*), MIN(s.captured) FROM snapshots s
                                    LEFT JOIN deliveries d ON s.name=d.name AND d.destination=?
                                    WHERE COALESCE(d.done,0)=0""", (target["path"],)).fetchone()
                result["targets"][target["name"]] = {"pending": row[0], "oldest_pending": row[1]}
        return result


class Backup:
    def __init__(self, config, store, rclone, stop=None):
        self.config, self.store, self.rclone = config, store, rclone
        self.stop = stop or threading.Event()
        self.source = None
        self.last_source_ok = None
        self.source_error = None
        self.target_errors = {}
        self.error_lock = threading.Lock()
        # Always check on startup, regardless of the persisted next_check.
        # A monotonic deadline keeps clock changes from postponing live checks.
        self.next_target_checks = {}

    def scan(self):
        if self.source is None:
            self.source = self.rclone.resolve(self.config["source"])
        before = self.rclone.stat(self.source)
        size = before["Size"]
        if type(size) is not int or not 64 <= size <= self.config["max_file_bytes"]:
            raise BackupError("source size is invalid or exceeds max_file_bytes")
        if self.stop.wait(self.config["settle_seconds"]):
            return
        descriptor, temporary = tempfile.mkstemp(prefix="capture-", dir=self.store.staging)
        os.close(descriptor)
        try:
            self.rclone.download(self.source, temporary)
            after = self.rclone.stat(self.source)
            if before != after or Path(temporary).stat().st_size != size:
                raise BackupError("source changed during capture; retry on next poll")
            name = self.store.capture(temporary)
            if name:
                LOG.info("snapshot_saved name=%s", name)
            self.last_source_ok = time.time()
            self.source_error = None
            return name
        finally:
            Path(temporary).unlink(missing_ok=True)

    def deliver_one(self, target):
        item = self.store.pending(target["path"])
        if item is None:
            return False
        name = item["name"]
        try:
            path = self.store.archives / name
            if sha256(path) != item["sha256"]:
                raise BackupError("local snapshot hash mismatch; upload stopped")
            sidecar = self.store.sidecar(path, item["sha256"])
            self.rclone.upload(path, target["path"], item["sha256"])
            self.rclone.upload(sidecar, target["path"], sha256(sidecar))
            self.store.delivered(name, target["path"])
            with self.error_lock:
                self.target_errors.pop(target["name"], None)
            # The first upload may have created a missing target directory.
            # Recheck immediately instead of retaining the startup failure.
            if self.store.target_check(target["path"])["error"] is not None:
                self.next_target_checks[target["path"]] = 0
            LOG.info("snapshot_verified target=%s name=%s", target["name"], name)
        except (BackupError, OSError) as error:
            self.store.failed(name, target["path"], item["attempts"], self.config["retry_seconds"])
            with self.error_lock:
                self.target_errors[target["name"]] = str(error)
            LOG.error("delivery_failed target=%s reason=%s", target["name"], error)
        return True

    def check_target(self, target):
        destination = target["path"]
        if time.monotonic() < self.next_target_checks.get(destination, 0):
            return False
        error = None
        delay = self.config.get("target_check_seconds", 86400)
        try:
            self.rclone.probe(destination)
        except (BackupError, OSError, ValueError) as failure:
            error = str(failure)
            failures = self.store.target_check(destination)["failures"]
            delay = min(self.config["retry_seconds"] * 2 ** min(failures, 10), 3600)
        checked = time.time()
        self.store.record_target_check(destination, checked, delay, error)
        self.next_target_checks[destination] = time.monotonic() + delay
        if error is None:
            LOG.info("target_check_ok target=%s", target["name"])
        else:
            LOG.error("target_check_failed target=%s reason=%s", target["name"], error)
        return True

    def scan_loop(self):
        while not self.stop.is_set():
            try:
                self.scan()
            except (BackupError, OSError, ValueError) as error:
                self.source_error = str(error)
                LOG.error("capture_failed reason=%s", error)
            self.stop.wait(self.config["poll_seconds"])

    def target_loop(self, target):
        while not self.stop.is_set():
            self.check_target(target)
            if self.stop.is_set():
                break
            if not self.deliver_one(target):
                self.stop.wait(5)

    def status(self):
        result = self.store.summary(self.config["targets"])
        now = time.time()
        grace = self.config["health_grace_seconds"]
        with self.error_lock:
            errors = dict(self.target_errors)
        healthy = self.last_source_ok is not None and now - self.last_source_ok <= grace
        healthy = healthy and self.source_error is None
        for configured in self.config["targets"]:
            name = configured["name"]
            target = result["targets"][name]
            check = self.store.target_check(configured["path"])
            if check["error"] is not None:
                check["state"] = "error"
                errors.setdefault(name, check["error"])
            elif check["last_success"] is None:
                check["state"] = "pending"
                healthy = False
            elif now - check["last_success"] > self.config.get("target_check_seconds", 86400) + grace:
                check["state"] = "stale"
                errors.setdefault(name, "target connection check overdue")
            else:
                check["state"] = "ok"
            target["connection_check"] = check
            if target["oldest_pending"] is not None and now - target["oldest_pending"] > grace:
                healthy = False
        healthy = healthy and not errors
        result.update(updated=now, mode="running", healthy=healthy,
                      last_source_ok=self.last_source_ok, source_error=self.source_error,
                      target_errors=errors)
        return result

    def run(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.config["targets"]) + 1) as pool:
            workers = [pool.submit(self.scan_loop)]
            workers.extend(pool.submit(self.target_loop, target) for target in self.config["targets"])
            try:
                while not self.stop.is_set():
                    for worker in workers:
                        if worker.done():
                            worker.result()  # Unexpected failures must not silently kill a worker.
                            raise BackupError("backup worker stopped unexpectedly")
                    atomic_write(self.store.root / "status.json", json.dumps(self.status(), indent=2).encode())
                    self.stop.wait(5)
            finally:
                self.stop.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=["run", "status", "health", "check-config"], default="run")
    parser.add_argument("--config", default="/config/config.json")
    parser.add_argument("--data", default="/data")
    args = parser.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    status_path = Path(args.data) / "status.json"
    if args.command in ("status", "health"):
        try:
            value = json.loads(status_path.read_text())
        except (OSError, ValueError):
            value = {"healthy": False, "mode": "no_status"}
        if args.command == "status":
            print(json.dumps(value, ensure_ascii=False, indent=2))
            return 0
        return 0 if value.get("healthy") and time.time() - value.get("updated", 0) < 45 else 1
    if args.command == "check-config":
        load_config(args.config)
        print("Configuration syntax OK (does not check cloud authorization).")
        return 0
    data = Path(args.data)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (data / "service.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise BackupError("another backup process already uses this data directory")
    configure_file_logging(data)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    # Waiting for first-time configuration is explicit, and is never reported healthy.
    while not stop.is_set():
        try:
            config = load_config(args.config)
            if config["enabled"]:
                break
            reason = "enable config after configuring cloud accounts"
        except (OSError, ValueError, BackupError) as error:
            reason = str(error)
        atomic_write(status_path, json.dumps({"updated": time.time(), "mode": "waiting_config",
                                             "healthy": False, "reason": reason}).encode())
        LOG.info("waiting_config reason=%s", reason)
        stop.wait(30)
    if stop.is_set():
        return 0
    store = Store(data)
    store.recover()
    service = Backup(config, store, Rclone(config["command_timeout_seconds"]), stop)
    LOG.info("service_started poll_seconds=%s targets=%s", config["poll_seconds"], len(config["targets"]))
    try:
        service.run()
    finally:
        atomic_write(status_path, json.dumps({"updated": time.time(), "mode": "stopped", "healthy": False}).encode())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BackupError, OSError, ValueError, sqlite3.Error) as error:
        LOG.error("service_failed reason=%s", error)
        sys.exit(1)
