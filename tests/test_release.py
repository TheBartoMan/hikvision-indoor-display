import importlib.util
import ipaddress
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_tools", ROOT / "scripts/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_release_source_audit(self):
        files, manifest = release.check(ROOT)
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertFalse(any(path.name == "MIGRATE.md" for path in files))

    def test_rejects_private_addresses_paths_keys_and_hostnames(self):
        values = [str(ipaddress.IPv4Address(0x0a010203)),
                  str(PurePosixPath("/", "Users", "example", "Documents", "file")),
                  ":".join(["ab"] * 6), ".".join(["device", "example", "home"]),
                  "-----" + "BEGIN OPENSSH " + "PRIVATE KEY-----"]
        for value in values:
            with self.subTest(kind=value.split()[0]), self.assertRaises(ValueError):
                release.audit_text(value)

    def test_allows_firmware_paths_and_reserved_test_addresses(self):
        release.audit_text("/home/app/hicore 192.0.2.1 127.0.0.1 https://github.com/example/repository")

    def test_metadata_configuration_and_reproducible_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in release.release_files(ROOT):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            manifest_path = root / release.MANIFEST
            manifest = json.loads(manifest_path.read_text())
            for key in ("documentation", "issue_tracker"):
                manifest.pop(key, None)
            manifest["codeowners"] = []
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                release.check(root, require_metadata=True)
            release.configure(root, "example-community/hikvision-indoor-display", "example-maintainer")
            release.check(root, require_metadata=True)
            path, first_hash = release.build(root, require_metadata=True)
            first_bytes = path.read_bytes()
            _, second_hash = release.build(root, require_metadata=True)
            self.assertEqual(first_hash, second_hash)
            self.assertEqual(first_bytes, path.read_bytes())
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    self.assertEqual(info.extra, b"")
                    self.assertEqual(info.comment, b"")
                    self.assertEqual(info.date_time, (2026, 1, 1, 0, 0, 0))
                    self.assertNotIn("dist/", info.filename)

    def test_rejects_unexpected_root_files_and_missing_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "unexpected.txt").write_text("fixture")
            with self.assertRaises(ValueError):
                release.release_files(root)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                release.check(Path(directory))

    def test_rejects_invalid_metadata_arguments(self):
        for repository, maintainer in [("invalid repository", "example"), ("example/repo", "../invalid")]:
            with self.assertRaises(ValueError):
                release.configure(ROOT, repository, maintainer)
