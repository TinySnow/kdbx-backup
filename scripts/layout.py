"""Host paths, settings and safe instance initialization."""
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def validate_profile(name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name):
        raise ValueError("profile must start with a lowercase letter and contain up to 32 lowercase letters, digits, _ or -")
    if name in {"con", "prn", "aux", "nul", *["com" + str(i) for i in range(1, 10)],
                *["lpt" + str(i) for i in range(1, 10)]}:
        raise ValueError("profile name is reserved on Windows")
    return name


def settings(root, environment=None):
    """Read path settings from .env, with process environment taking precedence."""
    values = {}
    file = Path(root) / ".env"
    if file.exists():
        for line in file.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if not match:
                continue
            name, value = match.groups()
            if value.startswith(("'", '"')):
                quote = value[0]
                end = value.find(quote, 1)
                if end < 0:
                    raise ValueError("Unclosed quote in .env setting: " + name)
                value = value[1:end]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            values[name] = value
    values.update(os.environ if environment is None else environment)
    return values


def data_root(root=ROOT, environment=None):
    root = Path(root).resolve()
    value = settings(root, environment).get("KDBX_BACKUP_DATA_ROOT") or "./var/data"
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def data_directory(root=ROOT, profile="default", environment=None):
    validate_profile(profile)
    base = data_root(root, environment)
    path = base / profile
    if path.is_symlink():
        raise ValueError("instance data directories must not be symbolic links")
    return path


def profile_root(root=ROOT, profile="default"):
    root = Path(root).resolve()
    validate_profile(profile)
    if profile == "default":
        return root
    directory = root / "profiles" / profile
    for path in (directory.parent, directory, directory / "config",
                 directory / ".secrets", directory / ".secrets/rclone",
                 directory / "config/config.json", directory / ".secrets/rclone/rclone.conf"):
        if path.is_symlink():
            raise ValueError("profile directories must not be symbolic links")
    return directory


def known_profiles(root=ROOT):
    root = Path(root).resolve()
    names = ["default"] if (root / "config/config.json").is_file() else []
    directory = root / "profiles"
    if directory.is_dir() and not directory.is_symlink():
        for child in sorted(directory.iterdir()):
            if child.name == "default" or not child.is_dir() or child.is_symlink():
                continue
            try:
                path = profile_root(root, child.name)
            except ValueError:
                continue
            if (path / "config/config.json").is_file():
                names.append(child.name)
    return names


def append_settings(root, values):
    path = Path(root) / ".env"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    configured = settings(root, {})
    missing = []
    for name, value in values.items():
        if name not in configured:
            value = str(value)
            if any(character in value for character in ('\n', '\r', '"', '$')):
                raise ValueError("Unsupported character in generated .env setting: " + name)
            rendered = '"' + value + '"' if re.search(r"\s|#", value) else value
            missing.append('%s=%s\n' % (name, rendered))
    if missing:
        with path.open("a", encoding="utf-8") as stream:
            if existing and not existing.endswith("\n"):
                stream.write("\n")
            stream.writelines(missing)
        if not existing and os.name != "nt":
            path.chmod(0o600)


def initialize_container_user(root):
    owner = Path(root).stat()
    append_settings(root, {"KDBX_BACKUP_UID": owner.st_uid, "KDBX_BACKUP_GID": owner.st_gid})


def initialize(root=ROOT, profile="default", storage_root=None):
    root = Path(root).resolve()
    instance = profile_root(root, profile)
    # Only the host-side initializer can see the surrounding homelab tree.
    # Docker initialization uses the configured /storage bind instead.
    homelab = root.parent.parent
    inferred = (homelab / "data/kdbx-backup"
                if root.parent.name in {"projects", "services"} and (homelab / "data").is_dir()
                else "./var/data")
    configured = settings(root)
    append_settings(root, {"KDBX_BACKUP_DATA_ROOT": configured.get("KDBX_BACKUP_DATA_ROOT") or inferred})
    destination = Path(storage_root) / profile if storage_root is not None else data_directory(root, profile)
    legacy = instance / "data"
    if legacy.is_dir() and legacy.resolve() != destination.resolve() and (
            (legacy / "state.sqlite3").exists() or list((legacy / "snapshots").glob("*.kdbx"))):
        raise ValueError("Legacy backup data found; stop and migrate it before initializing the new data root")
    for relative in ("config", ".secrets", ".secrets/rclone"):
        directory = instance / relative
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt" and relative != "config":
            directory.chmod(0o700)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        destination.chmod(0o700)
    (root / ".tools").mkdir(mode=0o700, exist_ok=True)
    config = instance / "config/config.json"
    if not config.exists():
        template = (root / "examples/config.example.json").read_bytes()
        if profile != "default":
            value = json.loads(template)
            value["enabled"] = False
            for target in value["targets"]:
                target["path"] = target["path"].rstrip("/") + "/" + profile
            template = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        try:
            with config.open("xb") as stream:
                stream.write(template)
        except FileExistsError:
            pass
    initialize_container_user(root)
    return instance
