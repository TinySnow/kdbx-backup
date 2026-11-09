"""Install the official host rclone into .tools after SHA-256 verification."""
import hashlib
import os
from pathlib import Path
import platform
import shutil
import ssl
import tempfile
import urllib.request
import zipfile

VERSION = "1.75.2"
ROOT = Path(__file__).resolve().parents[1]


def release_asset(system=None, machine=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    operating_system = {"Darwin": "osx", "Linux": "linux", "Windows": "windows"}.get(system)
    architecture = {"arm64": "arm64", "aarch64": "arm64",
                    "x86_64": "amd64", "amd64": "amd64"}.get(machine)
    if operating_system is None or architecture is None:
        raise ValueError("Supported hosts: Windows, macOS, Linux on AMD64 or ARM64")
    stem = "rclone-v%s-%s-%s" % (VERSION, operating_system, architecture)
    executable = "rclone.exe" if system == "Windows" else "rclone"
    return stem, executable


def download(url, destination):
    # System certificate verification and standard HTTPS proxy variables.
    request = urllib.request.Request(url, headers={"User-Agent": "kdbx-backup-bootstrap/0.1.0"})
    with urllib.request.urlopen(request, timeout=60, context=ssl.create_default_context()) as response:
        with Path(destination).open("wb") as stream:
            shutil.copyfileobj(response, stream)


def verify_archive(archive, manifest):
    expected = [parts[0] for line in Path(manifest).read_text(encoding="utf-8").splitlines()
                if len(parts := line.split()) == 2 and parts[1].lstrip("*") == Path(archive).name]
    digest = hashlib.sha256()
    with Path(archive).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if expected != [digest.hexdigest()]:
        raise ValueError("Official release SHA-256 verification failed")


def install(root=ROOT, system=None, machine=None):
    stem, executable = release_asset(system, machine)
    directory = Path(root) / ".tools"
    directory.mkdir(mode=0o700, exist_ok=True)
    base = "https://downloads.rclone.org/v%s/" % VERSION
    with tempfile.TemporaryDirectory(prefix="rclone-", dir=directory) as temporary:
        temporary = Path(temporary)
        archive = temporary / (stem + ".zip")
        manifest = temporary / "SHA256SUMS"
        download(base + archive.name, archive)
        download(base + manifest.name, manifest)
        verify_archive(archive, manifest)
        with zipfile.ZipFile(archive) as package:
            # Read only a known member; never extract arbitrary archive paths.
            binary = temporary / executable
            binary.write_bytes(package.read(stem + "/" + executable))
        if executable != "rclone.exe":
            binary.chmod(0o700)
        os.replace(binary, directory / executable)
    return directory / executable


def main():
    os.umask(0o077)
    binary = install()
    print("Installed verified rclone %s at %s" % (VERSION, binary))


if __name__ == "__main__":
    main()
