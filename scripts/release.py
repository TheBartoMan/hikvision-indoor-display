"""Audit and package a standalone release; never uploads or publishes anything."""
import argparse
import ast
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import struct
import sys
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("custom_components/hikvision_display/manifest.json")
ROOT_FILES = {
    "README.md", "LICENSE", "CHANGELOG.md", "ACCEPTANCE.md", "PUBLISHING.md",
    "SECURITY.md", "hacs.json", "install.sh", "requirements-test.txt", ".gitignore",
}
DIRECTORIES = {"custom_components", "tests", "scripts", ".github"}
EXAMPLE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                         ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "127.0.0.0/8"))


def release_files(root):
    files = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {".git", "dist", "__pycache__", ".venv", ".pytest_cache"} for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("Symbolic links must not be included in a release")
        if path.is_file():
            if len(relative.parts) == 1 and relative.name not in ROOT_FILES:
                raise ValueError("Unexpected release root file: " + relative.name)
            if len(relative.parts) > 1 and relative.parts[0] not in DIRECTORIES:
                raise ValueError("Unexpected release directory: " + relative.parts[0])
            if path.suffix in {".pyc", ".pem", ".key", ".log"} or path.name in {".DS_Store", ".env", "known_hosts"}:
                raise ValueError("Unpublishable file: " + str(relative))
            files.append(relative)
    return files


def audit_text(text):
    if re.search(r"/(?:Users/[^/\s]+/|home/[^/\s]+/(?:Documents|Downloads|Desktop|\.ssh|\.codex)/)", text):
        raise ValueError("Workstation home-directory reference")
    if re.search(r"/(?:private/)?var/folders/[A-Za-z0-9_-]+/|BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY", text):
        raise ValueError("Private workstation path or key material")
    for match in re.finditer(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])", text):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            continue
        if not any(address in network for network in EXAMPLE_NETWORKS):
            raise ValueError("Non-example IPv4 address")
    if re.search(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", text):
        raise ValueError("Literal MAC address")
    if re.search(r"(?i)(?:\b[a-z0-9-]+\.)+[a-z0-9-]+\.(?:home|lan|local)\b", text):
        raise ValueError("Private hostname")


def check_brand_png(data, size):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid brand PNG")
    offset, chunks = 8, []
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError("Truncated brand PNG")
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        end = offset + length + 12
        if end > len(data) or kind not in {b"IHDR", b"IDAT", b"IEND"}:
            raise ValueError("Brand PNG contains unexpected data or metadata")
        if zlib.crc32(kind + payload) != struct.unpack_from(">I", data, end - 4)[0]:
            raise ValueError("Brand PNG checksum mismatch")
        if kind == b"IHDR" and (length != 13 or struct.unpack(">IIBBBBB", payload) != (size, size, 8, 6, 0, 0, 0)):
            raise ValueError("Brand PNG must be correctly sized RGBA")
        chunks.append(kind)
        offset = end
    if not chunks or chunks[0] != b"IHDR" or chunks[-1] != b"IEND" or b"IDAT" not in chunks:
        raise ValueError("Incomplete brand PNG")


def check(root, require_metadata=False):
    files = release_files(root)
    if MANIFEST not in files:
        raise ValueError("Integration manifest missing")
    if not ROOT_FILES.issubset({path.as_posix() for path in files}):
        raise ValueError("Required release documentation or metadata missing")
    for name in ("__init__.py", "config_flow.py", "protocol.py", "coordinator.py", "solver.py", "seeds.bin"):
        if MANIFEST.parent / name not in files:
            raise ValueError("Required runtime file missing: " + name)
    for relative in files:
        path = root / relative
        if path.suffix == ".png":
            if (relative.parent != MANIFEST.parent / "brand" or relative.name not in
                    {"icon.png", "icon@2x.png", "dark_icon.png", "dark_icon@2x.png"}):
                raise ValueError("Unexpected image asset")
            check_brand_png(path.read_bytes(), 512 if "@2x" in relative.name else 256)
            continue
        if path.suffix == ".bin":
            if str(relative) != "custom_components/hikvision_display/seeds.bin":
                raise ValueError("Unexpected binary")
            if hashlib.sha256(path.read_bytes()).hexdigest() != "200e39498a2629a77e10dccb029692118db4de233ce97ed354060108dd5d52b7":
                raise ValueError("Generated seed table integrity failure")
            continue
        text = path.read_text(encoding="utf-8")
        try:
            audit_text(text)
        except ValueError as exc:
            raise ValueError(str(relative) + ": " + str(exc)) from None
        if path.suffix == ".py":
            ast.parse(text, filename=str(relative))
        elif path.suffix == ".json":
            json.loads(text)
    manifest = json.loads((root / MANIFEST).read_text())
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest["version"]):
        raise ValueError("Release version must be stable semantic versioning")
    if require_metadata:
        for key in ("documentation", "issue_tracker"):
            if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/issues)?", manifest.get(key, "")):
                raise ValueError("Configure real repository metadata before publishing: " + key)
        if not manifest.get("codeowners"):
            raise ValueError("Configure a public maintainer before publishing")
    return files, manifest


def configure(root, repository, maintainer):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Use an actual GitHub OWNER/REPOSITORY")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}(?:/[A-Za-z0-9-]+)?", maintainer):
        raise ValueError("Use an actual GitHub username or organisation/team")
    path = root / MANIFEST
    manifest = json.loads(path.read_text())
    manifest.update(documentation="https://github.com/" + repository,
                    issue_tracker="https://github.com/" + repository + "/issues",
                    codeowners=["@" + maintainer])
    manifest = {key: manifest[key] for key in ("domain", "name")} | {
        key: value for key, value in sorted(manifest.items()) if key not in {"domain", "name"}}
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def build(root, require_metadata=False):
    files, manifest = check(root, require_metadata)
    destination = root / "dist" / ("hikvision-indoor-display-" + manifest["version"] + ".zip")
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in files:
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (root / relative).read_bytes())
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(digest + "  " + destination.name + "\n", encoding="ascii")
    return destination, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "build"):
        commands.add_parser(name).add_argument("--require-metadata", action="store_true")
    config = commands.add_parser("configure")
    config.add_argument("--repository", required=True)
    config.add_argument("--maintainer", required=True)
    args = parser.parse_args()
    try:
        if args.command == "configure":
            configure(ROOT, args.repository, args.maintainer)
            print("Repository metadata configured; no repository was created or published.")
        elif args.command == "build":
            path, digest = build(ROOT, args.require_metadata)
            print("Built " + path.name + " SHA256 " + digest)
        else:
            files, manifest = check(ROOT, args.require_metadata)
            print("Source audit passed: " + manifest["version"] + ", " + str(len(files)) + " files")
    except (ValueError, OSError, SyntaxError) as exc:
        print("Release blocked: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
