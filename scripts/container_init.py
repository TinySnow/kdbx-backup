"""Initialize config in /workspace and persistent data in the /storage bind."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.layout import initialize


def main():
    root = Path("/workspace")
    storage = Path("/storage")
    owner = root.stat()
    if os.getuid() == 0:
        # Docker may create a fresh host storage directory as root.
        # Only adjust ownership of an empty newly-created root, never existing data.
        if storage.stat().st_uid != owner.st_uid:
            if any(storage.iterdir()):
                raise ValueError("Existing data root has a different owner; set its ownership before initialization")
            os.chown(storage, owner.st_uid, owner.st_gid)
        os.setgroups([])
        os.setgid(owner.st_gid)
        os.setuid(owner.st_uid)
    os.umask(0o077)
    initialize(root, storage_root=storage)
    initialize(root, "family", storage_root=storage)
    print("Initialized default and family; persistent data is mounted at /storage.")


if __name__ == "__main__":
    main()
