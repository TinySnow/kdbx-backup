#!/usr/bin/env python3
"""Cross-platform Docker management. Python 3.9+, no third-party dependencies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import bootstrap_rclone
from scripts.layout import (validate_profile, profile_root, known_profiles, initialize,
                            initialize_container_user, data_directory)


class Manager:
    def __init__(self, root=ROOT, environment=None, profile="default"):
        self.root = Path(root).resolve()
        self.profile = validate_profile(profile)
        self.instance_root = profile_root(self.root, profile)
        self.environment = dict(os.environ if environment is None else environment)
        self.data_dir = data_directory(self.root, profile, self.environment)
        self.environment.update({
            "KDBX_BACKUP_CONFIG_DIR": (self.instance_root / "config").as_posix(),
            "KDBX_BACKUP_DATA_ROOT": self.data_dir.parent.as_posix(),
            "KDBX_BACKUP_PROFILE": profile,
            "KDBX_BACKUP_DATA_DIR": self.data_dir.as_posix(),
            "KDBX_BACKUP_RCLONE_DIR": (self.instance_root / ".secrets/rclone").as_posix(),
        })

    def run(self, *command):
        subprocess.run(list(map(str, command)), cwd=self.root,
                       env=self.environment, check=True)

    def compose_command(self, *arguments, build=False):
        files = ["-f", "compose.yaml"]
        project = ["-p", "kdbx-backup" + ("-" + self.profile if self.profile != "default" else "")]
        return ["docker", "compose", *project, *files, *arguments]

    def compose(self, *arguments, build=False):
        self.run(*self.compose_command(*arguments, build=build))

    def capture(self, *command):
        return subprocess.run(list(map(str, command)), cwd=self.root, env=self.environment,
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True).stdout

    def status(self):
        output = self.capture(*self.compose_command("ps", "--all", "--format", "json"))
        if not output.strip():
            containers = []
        else:
            try:
                value = json.loads(output)
                containers = value if isinstance(value, list) else [value]
            except json.JSONDecodeError:
                containers = [json.loads(line) for line in output.splitlines() if line.strip()]
        container = next((value for value in containers if value.get("Service") == "backup"), {})
        result = {"profile": self.profile, "container_state": container.get("State", "not_created"),
                  "health": container.get("Health") or None, "backup": None}
        if result["container_state"] == "running":
            result["backup"] = json.loads(self.capture(*self.compose_command(
                "exec", "-T", "backup", "python", "-m", "kdbx_backup.service", "status")))
        return result

    def native_rclone(self):
        executable = "rclone.exe" if platform.system() == "Windows" else "rclone"
        binary = self.root / ".tools" / executable
        if not binary.is_file():
            raise ValueError("Run 'python scripts/manage.py bootstrap' first")
        return binary

    def test_integration(self, architecture=None):
        suffix = architecture.split("/")[-1] if architecture else "native"
        image = "kdbx-backup:test-" + suffix
        target = ["--platform", architecture] if architecture else []
        self.run("docker", "buildx", "build", "--load", *target, "-f", "deploy/Dockerfile", "-t", image, ".")
        mounts = []
        for source, destination in (("tests", "/tests"), ("scripts", "/app/scripts")):
            mounts += ["--mount", "type=bind,src=%s,dst=%s,readonly" % (self.root / source, destination)]
        self.run("docker", "run", "--rm", *target, "--read-only", "--cap-drop=ALL",
                 "--security-opt=no-new-privileges:true", "--tmpfs", "/tmp:mode=1777,size=67108864",
                 "-e", "RCLONE_INTEGRATION=1", "-e", "PYTHONPATH=/app", *mounts,
                 "--entrypoint", "python", image, "-m", "unittest", "discover", "-s", "/tests", "-v")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    def add_profile(command):
        command.add_argument("--profile", type=validate_profile, default=argparse.SUPPRESS,
                             help="instance name (default uses the original directories)")
    add_profile(result)
    commands = result.add_subparsers(dest="action", required=True)
    for name in ("init", "stop", "restart", "status", "logs", "check"):
        command = commands.add_parser(name)
        add_profile(command)
        if name in ("stop", "restart", "status"):
            command.add_argument("--all", action="store_true", help="operate on all initialized instances")
    for name in ("bootstrap", "test", "profiles"):
        commands.add_parser(name)
    configure = commands.add_parser("configure", help="configure credentials on host or headless server")
    add_profile(configure)
    configure.add_argument("--headless", action="store_true", help="use rclone in Docker; answer N to browser login")
    configure.add_argument("--pull", action="store_true", help="use published image for headless configuration")
    start = commands.add_parser("start", help="build locally, or pull KDBX_BACKUP_IMAGE")
    add_profile(start)
    start.add_argument("--pull", action="store_true")
    start.add_argument("--all", action="store_true", help="start all initialized instances; build/pull once")
    integration = commands.add_parser("test-integration")
    integration.add_argument("--platform", choices=["linux/amd64", "linux/arm64"])
    for name in ("rclone", "authorize"):
        command = commands.add_parser(name)
        if name == "rclone":
            add_profile(command)
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    verify = commands.add_parser("verify", help="verify snapshot against its .sha256 sidecar")
    verify.add_argument("snapshot", type=Path)
    return result


def status_all(root=ROOT):
    results, failed = [], False
    for profile in known_profiles(root):
        try:
            results.append(Manager(root, profile=profile).status())
        except (OSError, ValueError, subprocess.CalledProcessError):
            # Do not include Docker/provider responses that could contain credentials.
            results.append({"profile": profile, "container_state": "error",
                            "error": "could not read container status"})
            failed = True
    print(json.dumps({"profiles": results}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def operate_all(action, pull=False, root=ROOT):
    managers = [Manager(root, profile=profile) for profile in known_profiles(root)]
    if not managers:
        print("No initialized profiles.")
        return 0
    if action == "start":
        if pull:
            managers[0].compose("pull", "backup")
        else:
            managers[0].compose("build", "backup", build=True)
    failed = False
    for manager in managers:
        try:
            if action == "start":
                manager.compose("up", "-d", "--no-build")
            else:
                manager.compose(action, "backup")
        except (OSError, ValueError, subprocess.CalledProcessError):
            print("Operation failed for profile: " + manager.profile, file=sys.stderr)
            failed = True
    return 1 if failed else 0


def verify_snapshot(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    expected = Path(str(path) + ".sha256").read_text(encoding="utf-8").strip()
    if expected != digest.hexdigest() + "  " + path.name:
        raise ValueError("Snapshot verification FAILED")
    print("OK: " + path.name)


def main(arguments=None):
    cli = parser()
    args = cli.parse_args(arguments)
    if getattr(args, "all", False) and hasattr(args, "profile"):
        cli.error("--all cannot be combined with --profile")
    if hasattr(args, "profile") and args.action in ("verify", "test", "test-integration", "bootstrap", "authorize", "profiles"):
        cli.error(args.action + " is shared across profiles; omit --profile")
    os.umask(0o077)
    if args.action == "verify":
        verify_snapshot(args.snapshot)
        return 0
    if args.action == "test":
        # Host tests must not inherit this instance's derived production mount paths.
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_tools.py", "-v"],
                       cwd=ROOT, check=True)
        return 0
    if args.action == "test-integration":
        Manager().test_integration(args.platform)
        return 0
    if args.action == "profiles":
        print(json.dumps({"profiles": [{"name": name, "directory": str(profile_root(ROOT, name))}
                                       for name in known_profiles()]}, ensure_ascii=False, indent=2))
        return 0
    if getattr(args, "all", False):
        if args.action == "status":
            return status_all()
        return operate_all(args.action, getattr(args, "pull", False))
    profile = getattr(args, "profile", "default")
    if profile == "default":
        initialize()
    elif args.action == "init":
        initialize(profile=profile)
    elif not (profile_root(ROOT, profile) / "config/config.json").is_file():
        raise ValueError("Profile is not initialized. Run: python scripts/manage.py init --profile " + profile)
    manager = Manager(profile=profile)
    if args.action == "init":
        print("Initialized profile '%s' at %s. Existing files were preserved." % (profile, manager.instance_root))
    elif args.action == "bootstrap":
        bootstrap_rclone.main()
    elif args.action == "configure":
        # Stop before touching credentials; token refresh uses atomic rename.
        binary = None if args.headless else manager.native_rclone()
        manager.compose("stop", "backup")
        if args.headless:
            if args.pull:
                manager.compose("pull", "backup")
            else:
                manager.compose("build", "backup", build=True)
            manager.compose("run", "--rm", "--no-deps", "--entrypoint", "/usr/local/bin/rclone", "backup", "config")
        else:
            manager.run(binary, "--config", manager.instance_root / ".secrets/rclone/rclone.conf", "config")
    elif args.action == "authorize":
        manager.run(manager.native_rclone(), "authorize", *args.arguments)
    elif args.action == "start":
        if args.pull:
            manager.compose("pull", "backup")
            manager.compose("up", "-d", "--no-build")
        else:
            manager.compose("up", "-d", "--build", build=True)
    elif args.action in ("stop", "restart"):
        manager.compose(args.action, "backup")
    elif args.action == "logs":
        manager.compose("logs", "--tail", "100", "-f", "backup")
    elif args.action == "status":
        print(json.dumps(manager.status(), ensure_ascii=False, indent=2))
    elif args.action == "check":
        manager.compose("run", "--rm", "--no-deps", "backup", "check-config")
    elif args.action == "rclone":
        manager.compose("run", "--rm", "--no-deps", "--entrypoint", "/usr/local/bin/rclone", "backup", *args.arguments)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("Error: %s" % error, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
