"""Host management tests: run on Windows, macOS and Linux without Docker."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import manage
from scripts import layout
from scripts import bootstrap_rclone as bootstrap


class BootstrapTests(unittest.TestCase):
    platforms = (("Darwin", "arm64", "osx-arm64", "rclone"),
                 ("Darwin", "x86_64", "osx-amd64", "rclone"),
                 ("Linux", "aarch64", "linux-arm64", "rclone"),
                 ("Linux", "x86_64", "linux-amd64", "rclone"),
                 ("Windows", "ARM64", "windows-arm64", "rclone.exe"),
                 ("Windows", "AMD64", "windows-amd64", "rclone.exe"))

    def test_release_assets_and_verified_install_for_all_supported_hosts(self):
        for system, machine, suffix, executable in self.platforms:
            with self.subTest(system=system, machine=machine), tempfile.TemporaryDirectory() as root:
                stem, name = bootstrap.release_asset(system, machine)
                self.assertEqual(stem, "rclone-v%s-%s" % (bootstrap.VERSION, suffix))
                self.assertEqual(name, executable)
                payload = b"synthetic executable"
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    archive.writestr(stem + "/" + executable, payload)
                    archive.writestr("../unexpected", b"never extracted")
                data = buffer.getvalue()

                def download(url, destination):
                    if url.endswith(".zip"):
                        Path(destination).write_bytes(data)
                    else:
                        Path(destination).write_text(hashlib.sha256(data).hexdigest() + "  " + stem + ".zip\n")

                with patch.object(bootstrap, "download", side_effect=download):
                    binary = bootstrap.install(root, system, machine)
                self.assertEqual(binary.name, executable)
                self.assertEqual(binary.read_bytes(), payload)
                self.assertFalse((Path(root) / ".tools/unexpected").exists())

    def test_unsupported_architecture_does_not_silently_download_wrong_binary(self):
        for system, machine in (("Linux", "armv7l"), ("FreeBSD", "amd64"), ("Windows", "x86")):
            with self.assertRaises(ValueError):
                bootstrap.release_asset(system, machine)

    def test_checksum_mismatch_preserves_existing_installation(self):
        with tempfile.TemporaryDirectory() as root:
            binary = Path(root) / ".tools/rclone"
            binary.parent.mkdir()
            binary.write_bytes(b"existing")

            def download(url, destination):
                Path(destination).write_bytes(b"bad data" if url.endswith(".zip") else b"0" * 64 + b"  wrong.zip")

            with patch.object(bootstrap, "download", side_effect=download):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    bootstrap.install(root, "Linux", "x86_64")
            self.assertEqual(binary.read_bytes(), b"existing")

    def test_missing_or_duplicate_manifest_entry_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            archive, manifest = Path(root) / "file.zip", Path(root) / "SHA256SUMS"
            archive.write_bytes(b"payload")
            entry = hashlib.sha256(b"payload").hexdigest() + "  file.zip\n"
            for content in ("", entry * 2, "0" * 64 + "  file.zip\n"):
                manifest.write_text(content)
                with self.assertRaises(ValueError):
                    bootstrap.verify_archive(archive, manifest)


class ManagerTests(unittest.TestCase):
    def test_container_user_defaults_preserve_existing_environment_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = root / ".env"
            settings.write_text("TZ=Asia/Shanghai\nKDBX_BACKUP_UID=1234")
            manage.initialize_container_user(root)
            content = settings.read_text()
            self.assertIn("TZ=Asia/Shanghai\nKDBX_BACKUP_UID=1234\n", content)
            self.assertIn("KDBX_BACKUP_GID=%s\n" % root.stat().st_gid, content)
            manage.initialize_container_user(root)
            self.assertEqual(settings.read_text(), content)

    def test_init_preserves_existing_config_and_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "examples").mkdir()
            (root / "examples/config.example.json").write_text('{"enabled": false}')
            manage.initialize(root)
            actual = root / "config/config.json"
            self.assertEqual(actual.read_text(), '{"enabled": false}')
            actual.write_text("custom config")
            secret = root / ".secrets/rclone/rclone.conf"
            secret.write_text("private token fixture")
            manage.initialize(root)
            self.assertEqual(actual.read_text(), "custom config")
            self.assertEqual(secret.read_text(), "private token fixture")

    def test_subprocess_arguments_preserve_spaces_and_never_use_shell(self):
        with tempfile.TemporaryDirectory(prefix="kdbx with spaces ") as root:
            manager = manage.Manager(root, {"TEST": "value"})
            with patch("scripts.manage.subprocess.run") as run:
                manager.run("docker", "one argument with spaces", "$(not-a-shell)")
            self.assertEqual(run.call_args.args[0], ["docker", "one argument with spaces", "$(not-a-shell)"])
            self.assertEqual(run.call_args.kwargs["cwd"], Path(root).resolve())
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_compose_source_override_is_explicit(self):
        manager = manage.Manager()
        with patch.object(manager, "run") as run:
            manager.compose("up", "-d")
            self.assertNotIn("compose.build.yaml", run.call_args.args)
            manager.compose("up", "-d", build=True)
            self.assertNotIn("compose.build.yaml", run.call_args.args)

    def test_integration_uses_separate_image_and_no_live_data_or_credentials(self):
        manager = manage.Manager()
        for architecture in ("linux/amd64", "linux/arm64"):
            with self.subTest(platform=architecture), patch.object(manager, "run") as run:
                manager.test_integration(architecture)
                build, test = [call.args for call in run.call_args_list]
                self.assertIn(architecture, build)
                self.assertIn("kdbx-backup:test-" + architecture.split("/")[-1], build)
                self.assertIn(architecture, test)
                self.assertIn("--read-only", test)
                self.assertFalse(any(".secrets" in str(argument) or "src=%s/data" % manager.root in str(argument)
                                     for argument in test))

    def test_windows_selects_exe(self):
        with tempfile.TemporaryDirectory() as root:
            binary = Path(root) / ".tools/rclone.exe"
            binary.parent.mkdir()
            binary.write_bytes(b"fixture")
            with patch("scripts.manage.platform.system", return_value="Windows"):
                self.assertEqual(manage.Manager(root).native_rclone(), binary.resolve())

    def test_start_pull_does_not_build_or_retag_release(self):
        with patch("scripts.manage.initialize"), patch("scripts.manage.Manager") as manager:
            manage.main(["start", "--pull"])
            self.assertEqual(manager.return_value.compose.call_args_list[0].args, ("pull", "backup"))
            self.assertEqual(manager.return_value.compose.call_args_list[1].args, ("up", "-d", "--no-build"))

    def test_headless_configuration_stops_service_before_credentials_change(self):
        with patch("scripts.manage.initialize"), patch("scripts.manage.Manager") as manager:
            manage.main(["configure", "--headless", "--pull"])
            calls = manager.return_value.compose.call_args_list
            self.assertEqual(calls[0].args, ("stop", "backup"))
            self.assertEqual(calls[1].args, ("pull", "backup"))
            self.assertIn("config", calls[2].args)
            manager.return_value.native_rclone.assert_not_called()

    def test_raw_rclone_and_authorize_arguments_preserved(self):
        token_fixture = "example-base64-argument"
        self.assertEqual(manage.parser().parse_args(["authorize", "onedrive", token_fixture]).arguments,
                         ["onedrive", token_fixture])
        with patch("scripts.manage.initialize"), patch("scripts.manage.Manager") as manager:
            manage.main(["rclone", "lsjson", "onedrive:with spaces/", "--stat"])
            self.assertEqual(manager.return_value.compose.call_args.args[-3:],
                             ("lsjson", "onedrive:with spaces/", "--stat"))

    def test_snapshot_verification_works_without_unix_utilities(self):
        with tempfile.TemporaryDirectory() as root:
            snapshot = Path(root) / "vault.kdbx"
            snapshot.write_bytes(b"encrypted database fixture")
            Path(str(snapshot) + ".sha256").write_text(hashlib.sha256(snapshot.read_bytes()).hexdigest() + "  " + snapshot.name + "\n")
            with patch("builtins.print"):
                manage.verify_snapshot(snapshot)
            snapshot.write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "FAILED"):
                manage.verify_snapshot(snapshot)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="kdbx profiles ")
        self.root = Path(self.temporary.name)
        (self.root / "examples").mkdir()
        self.example = {"enabled": False, "source": "onedrive:",
                        "targets": [{"name": "drive", "path": "gdrive:KDBX-Backups"}]}
        (self.root / "examples/config.example.json").write_text(json.dumps(self.example))

    def tearDown(self):
        self.temporary.cleanup()

    def test_named_profiles_keep_credentials_config_state_and_targets_separate(self):
        default = manage.initialize(self.root)
        default_config = default / "config/config.json"
        default_config.write_text('{"enabled":true,"custom":"keep"}')
        default_secret = default / ".secrets/rclone/rclone.conf"
        default_secret.write_text("default-account-token-fixture")
        me = manage.initialize(self.root, "me")
        family = manage.initialize(self.root, "family")
        self.assertNotEqual(me, family)
        for directory, name in ((me, "me"), (family, "family")):
            config = json.loads((directory / "config/config.json").read_text())
            self.assertFalse(config["enabled"])
            self.assertEqual(config["source"], "onedrive:")
            self.assertEqual(config["targets"][0]["path"], "gdrive:KDBX-Backups/" + name)
            self.assertFalse((directory / ".secrets/rclone/rclone.conf").exists())
            self.assertTrue(manage.data_directory(self.root, name).is_dir())
        (family / ".secrets/rclone/rclone.conf").write_text("family-token-fixture")
        manage.initialize(self.root, "family")
        self.assertEqual((family / ".secrets/rclone/rclone.conf").read_text(), "family-token-fixture")
        self.assertEqual(default_config.read_text(), '{"enabled":true,"custom":"keep"}')
        self.assertEqual(default_secret.read_text(), "default-account-token-fixture")
        self.assertEqual(manage.known_profiles(self.root), ["default", "family", "me"])

    def test_compose_names_and_mounts_are_isolated_even_with_inherited_overrides(self):
        environment = {"COMPOSE_PROJECT_NAME": "unrelated", "KDBX_BACKUP_DATA_DIR": "/wrong/shared"}
        me = manage.Manager(self.root, environment, profile="me")
        family = manage.Manager(self.root, environment, profile="family")
        for manager in (me, family):
            self.assertIn("kdbx-backup-" + manager.profile, manager.compose_command("up", "-d"))
            for variable in ("KDBX_BACKUP_CONFIG_DIR", "KDBX_BACKUP_DATA_DIR", "KDBX_BACKUP_RCLONE_DIR"):
                if variable == "KDBX_BACKUP_DATA_DIR":
                    self.assertEqual(Path(manager.environment[variable]), manage.data_directory(self.root, manager.profile))
                else:
                    self.assertIn("/profiles/" + manager.profile + "/", manager.environment[variable])
                self.assertNotEqual(me.environment[variable], family.environment[variable])
        self.assertIn("kdbx-backup", manage.Manager(self.root).compose_command("ps"))

    def test_invalid_names_rejected_before_creating_files(self):
        for name in ("../family", "", "Family", "a/b", "a\\b", "-family", "a" * 33, "con", "com1", "nul"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                manage.initialize(self.root, name)
        self.assertFalse((self.root / "profiles").exists())

    def test_symlink_profile_cannot_alias_another_person(self):
        me = manage.initialize(self.root, "me")
        try:
            (self.root / "profiles/family").symlink_to(me, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation requires extra permissions on this host")
        with self.assertRaisesRegex(ValueError, "symbolic"):
            manage.Manager(self.root, profile="family")
        self.assertEqual(manage.known_profiles(self.root), ["me"])

    def test_profile_flag_supported_before_and_after_command(self):
        for arguments in (["--profile", "family", "start"], ["start", "--profile", "family"],
                          ["rclone", "--profile", "family", "listremotes"]):
            self.assertEqual(manage.parser().parse_args(arguments).profile, "family")
        with self.assertRaises(SystemExit), patch("sys.stderr", new=io.StringIO()):
            manage.main(["status", "--all", "--profile", "family"])

    def test_unknown_profile_does_not_silently_create_a_new_configuration(self):
        with patch("scripts.manage.ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "not initialized"):
                manage.main(["start", "--profile", "missing"])
        self.assertFalse((self.root / "profiles/missing").exists())

    def test_native_configuration_uses_selected_credentials_and_stops_only_that_profile(self):
        manage.initialize(self.root, "family")
        original = manage.Manager
        manager = original(self.root, profile="family")
        with patch.object(manager, "native_rclone", return_value=Path("rclone")), \
             patch.object(manager, "run") as run, patch("scripts.manage.Manager", return_value=manager), \
             patch("scripts.manage.ROOT", self.root):
            manage.main(["configure", "--profile", "family"])
        stop, configure = [call.args for call in run.call_args_list]
        self.assertIn("kdbx-backup-family", stop)
        self.assertIn("stop", stop)
        self.assertEqual(configure[-2], manager.instance_root / ".secrets/rclone/rclone.conf")

    def test_status_handles_not_created_stopped_and_running_without_stale_state(self):
        manager = manage.Manager(self.root, profile="family")
        with patch.object(manager, "capture", return_value="[]") as capture:
            self.assertEqual(manager.status()["container_state"], "not_created")
            self.assertEqual(capture.call_count, 1)
        for output in ('[{"Service":"backup","State":"exited"}]',
                       '{"Service":"backup","State":"exited"}\n'):
            with patch.object(manager, "capture", return_value=output) as capture:
                value = manager.status()
                self.assertEqual(value["container_state"], "exited")
                self.assertIsNone(value["backup"])
                self.assertEqual(capture.call_count, 1)
        with patch.object(manager, "capture", side_effect=[
                '{"Service":"backup","State":"running","Health":"unhealthy"}\n',
                '{"mode":"waiting_config","healthy":false}']):
            self.assertEqual(manager.status()["backup"]["mode"], "waiting_config")

    def test_status_all_keeps_other_results_when_one_instance_fails(self):
        manage.initialize(self.root, "me")
        manage.initialize(self.root, "family")
        with patch("scripts.manage.Manager") as factory, patch("sys.stdout", new=io.StringIO()) as output:
            factory.return_value.status.side_effect = [subprocess.CalledProcessError(1, ["docker"]),
                                                       {"profile": "me", "container_state": "running"}]
            self.assertEqual(manage.status_all(self.root), 1)
            value = json.loads(output.getvalue())
            self.assertEqual(value["profiles"][0]["container_state"], "error")
            self.assertEqual(value["profiles"][1]["profile"], "me")

    def test_start_all_builds_once_then_uses_shared_image(self):
        manage.initialize(self.root, "me")
        manage.initialize(self.root, "family")
        with patch.object(manage.Manager, "compose", autospec=True) as compose:
            self.assertEqual(manage.operate_all("start", root=self.root), 0)
            calls = compose.call_args_list
            self.assertEqual(calls[0].args[1:], ("build", "backup"))
            self.assertTrue(calls[0].kwargs["build"])
            self.assertEqual([call.args[1:] for call in calls[1:]], [("up", "-d", "--no-build")] * 2)
            self.assertEqual({call.args[0].profile for call in calls[1:]}, {"me", "family"})

    def test_stop_all_continues_after_one_profile_failure(self):
        manage.initialize(self.root, "me")
        manage.initialize(self.root, "family")
        with patch.object(manage.Manager, "compose", autospec=True) as compose, \
                patch("sys.stderr", new=io.StringIO()):
            compose.side_effect = [subprocess.CalledProcessError(1, ["docker"]), None]
            self.assertEqual(manage.operate_all("stop", root=self.root), 1)
            self.assertEqual(compose.call_count, 2)


class DataLocationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        (self.root / "examples").mkdir(parents=True)
        (self.root / "examples/config.example.json").write_text(json.dumps({
            "enabled": False, "source": "onedrive:",
            "targets": [{"name": "drive", "path": "gdrive:backup"}]}))

    def tearDown(self):
        self.temporary.cleanup()

    def test_custom_absolute_data_root_is_honored_by_initializer_and_manager(self):
        storage = self.base / "external storage"
        (self.root / ".env").write_text('KDBX_BACKUP_DATA_ROOT="%s"\n' % storage.as_posix())
        for profile in ("default", "family", "parents"):
            layout.initialize(self.root, profile)
            manager = manage.Manager(self.root, profile=profile)
            self.assertEqual(manager.data_dir, storage.resolve() / profile)
            self.assertTrue(manager.data_dir.is_dir())
            self.assertEqual(manager.environment["KDBX_BACKUP_DATA_ROOT"], storage.resolve().as_posix())
            self.assertEqual(manager.environment["KDBX_BACKUP_PROFILE"], profile)
        self.assertFalse((self.root / "data").exists())
        self.assertFalse((self.root / "profiles/family/data").exists())

    def test_relative_dotenv_path_uses_project_directory_and_supports_spaces(self):
        (self.root / ".env").write_text("KDBX_BACKUP_DATA_ROOT='./runtime with spaces' # local storage\n")
        self.assertEqual(layout.data_directory(self.root, "family", {}),
                         (self.root / "runtime with spaces/family").resolve())

    def test_process_environment_overrides_dotenv(self):
        (self.root / ".env").write_text("KDBX_BACKUP_DATA_ROOT=from-file\n")
        environment = {"KDBX_BACKUP_DATA_ROOT": str(self.base / "from-environment")}
        manager = manage.Manager(self.root, environment, profile="family")
        self.assertEqual(manager.data_dir, (self.base / "from-environment/family").resolve())

    def test_new_manager_reads_changed_data_root(self):
        path = self.root / ".env"
        path.write_text("KDBX_BACKUP_DATA_ROOT=first\n")
        first = manage.Manager(self.root).data_dir
        path.write_text("KDBX_BACKUP_DATA_ROOT=second\n")
        self.assertNotEqual(first, manage.Manager(self.root).data_dir)

    def test_host_initialization_detects_homelab_data_layout(self):
        root = self.base / "homelab/projects/kdbx-backup"
        (root / "examples").mkdir(parents=True)
        (self.base / "homelab/data").mkdir()
        (root / "examples/config.example.json").write_bytes((self.root / "examples/config.example.json").read_bytes())
        layout.initialize(root)
        expected = (self.base / "homelab/data/kdbx-backup/default").resolve()
        self.assertTrue(expected.is_dir())
        self.assertEqual(layout.data_directory(root), expected)

    def test_docker_initializer_uses_storage_mount_without_writing_host_absolute_path(self):
        (self.root / ".env").write_text("KDBX_BACKUP_DATA_ROOT=/host-only/kdbx-backup\n")
        storage = self.base / "mounted-storage"
        layout.initialize(self.root, "family", storage_root=storage)
        self.assertTrue((storage / "family").is_dir())
        self.assertEqual(layout.settings(self.root, {})["KDBX_BACKUP_DATA_ROOT"], "/host-only/kdbx-backup")

    def test_legacy_state_requires_explicit_migration(self):
        legacy = self.root / "data"
        legacy.mkdir()
        marker = legacy / "state.sqlite3"
        marker.write_bytes(b"state fixture")
        with self.assertRaisesRegex(ValueError, "Legacy backup data"):
            layout.initialize(self.root)
        self.assertEqual(marker.read_bytes(), b"state fixture")
        self.assertFalse((layout.data_directory(self.root) / "state.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
