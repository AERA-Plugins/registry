#!/usr/bin/env python3
"""Atomically update and verify the signed AERA plugin catalog."""

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog.json"
SIGNATURE = ROOT / "catalog.json.sig"
PUBLIC_KEY = ROOT / "keys/catalog-public.pem"
HEX_SIGNATURE = re.compile(r"[0-9a-f]{128}\n?\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
RAW_PREFIX = "https://raw.githubusercontent.com/AERA-Plugins/"
RELEASE_PREFIX = "https://github.com/AERA-Plugins/"


def verify_signature(content: bytes, signature: bytes, public_key=PUBLIC_KEY):
    text = signature.decode("ascii", errors="strict")
    if not HEX_SIGNATURE.fullmatch(text):
        raise ValueError("signature must be 64 bytes encoded as 128 lowercase hex characters")
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        content_path = base / "content"
        raw_path = base / "signature.raw"
        content_path.write_bytes(content)
        raw_path.write_bytes(bytes.fromhex(text.strip()))
        subprocess.run([
            "openssl", "pkeyutl", "-verify", "-rawin", "-pubin",
            "-inkey", str(public_key), "-in", str(content_path),
            "-sigfile", str(raw_path),
        ], check=True, stdout=subprocess.DEVNULL)


def fetch(url: str, maximum: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AERA-catalog-validator/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        value = response.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError(f"remote file exceeds {maximum} bytes: {url}")
    return value


def load_json(data: bytes, source: str):
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON in {source}: {error}") from error


def validate_manifest(manifest, expected_id=None):
    required = {
        "schema", "id", "name", "version", "description", "type", "entry",
        "min_host_api", "payload", "payload_url", "payload_size",
        "payload_sha256", "expanded_size", "expanded_sha256", "member_count",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise ValueError(f"manifest is missing: {', '.join(missing)}")
    if manifest["schema"] != 1 or manifest["min_host_api"] not in (1, 2):
        raise ValueError("manifest schema/host API is unsupported")
    if manifest["min_host_api"] == 2:
        required_api2 = {"protocol_version", "executable", "permissions"}
        missing_api2 = sorted(required_api2 - manifest.keys())
        if missing_api2:
            raise ValueError(
                "Host API 2 manifest is missing: " + ", ".join(missing_api2))
        if (manifest["type"] != "ui-runtime" or manifest["entry"] != "main" or
                manifest["protocol_version"] != 2 or
                manifest["executable"] != "usr/bin/aera-plugin"):
            raise ValueError("Host API 2 entrypoint is unsupported")
        permissions = manifest["permissions"]
        allowed = {
            "display", "touch-input",
            "settings-backup", "settings-restore",
            "android-settings-backup", "android-settings-restore",
        }
        if (not isinstance(permissions, list) or
                not {"display", "touch-input"}.issubset(permissions) or
                any(not isinstance(item, str) or item not in allowed
                    for item in permissions)):
            raise ValueError("Host API 2 permissions violate host policy")
    if expected_id and manifest["id"] != expected_id:
        raise ValueError("catalog and manifest IDs differ")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", manifest["id"]):
        raise ValueError("plugin ID violates AERA policy")
    if manifest["payload"] != "runtime.xz":
        raise ValueError("payload must be named runtime.xz")
    if not manifest["payload_url"].startswith(RELEASE_PREFIX):
        raise ValueError("payload URL is outside AERA-Plugins")
    for field in ("payload_sha256", "expanded_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", manifest[field]):
            raise ValueError(f"invalid {field}")
    for field in ("payload_size", "expanded_size", "member_count"):
        if not isinstance(manifest[field], int) or manifest[field] <= 0:
            raise ValueError(f"invalid {field}")


def validate_catalog(catalog, online=False):
    if catalog.get("schema") != 1 or not isinstance(catalog.get("plugins"), list):
        raise ValueError("catalog schema is invalid")
    seen = set()
    for entry in catalog["plugins"]:
        plugin_id = entry.get("id", "")
        if plugin_id in seen:
            raise ValueError(f"duplicate plugin ID: {plugin_id}")
        seen.add(plugin_id)
        for field in ("id", "name", "version", "description", "manifest_url", "signature_url"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                raise ValueError(f"{plugin_id or 'entry'} has invalid {field}")
        expected_prefix = RAW_PREFIX + plugin_id.replace("appvault", "app-backup-vault") + "/"
        if not entry["manifest_url"].startswith(expected_prefix):
            raise ValueError(f"{plugin_id} manifest URL is outside its official repository")
        pieces = entry["manifest_url"][len(expected_prefix):].split("/")
        if len(pieces) != 2 or not COMMIT.fullmatch(pieces[0]) or pieces[1] != "plugin.json":
            raise ValueError(f"{plugin_id} manifest URL is not pinned to an immutable commit")
        if entry["signature_url"] != entry["manifest_url"] + ".sig":
            raise ValueError(f"{plugin_id} signature URL does not match its manifest")
        package_url = entry.get("package_url", "")
        package_size = entry.get("package_size", 0)
        package_hash = entry.get("package_sha256", "")
        package_present = bool(package_url or package_size or package_hash)
        if package_present:
            repository = plugin_id.replace("appvault", "app-backup-vault")
            if not package_url.startswith(RELEASE_PREFIX + repository + "/releases/download/"):
                raise ValueError(f"{plugin_id} package URL is outside its official repository")
            if not package_url.endswith(".aerap"):
                raise ValueError(f"{plugin_id} package does not use the .aerap extension")
            if not isinstance(package_size, int) or package_size <= 0 or package_size > 513 * 1024 * 1024:
                raise ValueError(f"{plugin_id} has an invalid package size")
            if not re.fullmatch(r"[0-9a-f]{64}", package_hash):
                raise ValueError(f"{plugin_id} has an invalid package SHA-256")
        if online:
            manifest_data = fetch(entry["manifest_url"], 64 * 1024)
            signature_data = fetch(entry["signature_url"], 4096)
            verify_signature(manifest_data, signature_data)
            manifest = load_json(manifest_data, entry["manifest_url"])
            validate_manifest(manifest, plugin_id)
            if manifest["name"] != entry["name"] or manifest["version"] != entry["version"]:
                raise ValueError(f"{plugin_id} catalog metadata does not match its manifest")


def current_catalog(online=False):
    content = CATALOG.read_bytes()
    verify_signature(content, SIGNATURE.read_bytes())
    catalog = load_json(content, str(CATALOG))
    validate_catalog(catalog, online)
    return catalog


def sign(content: bytes, private_key: Path) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        content_path = base / "catalog.json"
        raw_path = base / "catalog.sig.raw"
        content_path.write_bytes(content)
        subprocess.run([
            "openssl", "pkeyutl", "-sign", "-rawin", "-inkey",
            str(private_key), "-in", str(content_path), "-out", str(raw_path),
        ], check=True)
        signature = raw_path.read_bytes().hex().encode("ascii") + b"\n"
    verify_signature(content, signature)
    return signature


def add(arguments):
    catalog = current_catalog(arguments.online)
    manifest_path = arguments.manifest.resolve(strict=True)
    manifest_data = manifest_path.read_bytes()
    manifest_signature = manifest_path.with_name(manifest_path.name + ".sig").read_bytes()
    verify_signature(manifest_data, manifest_signature)
    manifest = load_json(manifest_data, str(manifest_path))
    validate_manifest(manifest)
    if not COMMIT.fullmatch(arguments.commit):
        raise ValueError("--commit must be the full 40-character lowercase Git commit")
    repository = arguments.repository or manifest["id"]
    manifest_url = f"{RAW_PREFIX}{repository}/{arguments.commit}/plugin.json"
    package_path = arguments.package.resolve(strict=True)
    if package_path.suffix.lower() != ".aerap":
        raise ValueError("--package must point to an .aerap file")
    package_hash = hashlib.sha256(package_path.read_bytes()).hexdigest()
    release_base = manifest["payload_url"].rsplit("/", 1)[0]
    entry = {
        "id": manifest["id"], "name": manifest["name"],
        "version": manifest["version"], "description": manifest["description"],
        "manifest_url": manifest_url, "signature_url": manifest_url + ".sig",
        "package_url": release_base + "/" + package_path.name,
        "package_size": package_path.stat().st_size,
        "package_sha256": package_hash,
    }
    catalog["plugins"] = [item for item in catalog["plugins"] if item["id"] != manifest["id"]]
    catalog["plugins"].append(entry)
    catalog["generated"] = datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")
    validate_catalog(catalog, arguments.online)
    content = (json.dumps(catalog, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    signature = sign(content, arguments.key.resolve(strict=True))
    catalog_tmp = CATALOG.with_suffix(".json.new")
    signature_tmp = SIGNATURE.with_suffix(".sig.new")
    catalog_tmp.write_bytes(content)
    signature_tmp.write_bytes(signature)
    verify_signature(catalog_tmp.read_bytes(), signature_tmp.read_bytes())
    catalog_tmp.replace(CATALOG)
    signature_tmp.replace(SIGNATURE)
    print(f"Published {manifest['name']} {manifest['version']} locally; signature verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--online", action="store_true")
    publish = subparsers.add_parser("add")
    publish.add_argument("--manifest", type=Path, required=True)
    publish.add_argument("--commit", required=True)
    publish.add_argument("--repository")
    publish.add_argument("--package", type=Path, required=True)
    publish.add_argument("--key", type=Path, required=True)
    publish.add_argument("--online", action="store_true")
    arguments = parser.parse_args()
    if arguments.command == "verify":
        current_catalog(arguments.online)
        print("Catalog, signature, manifests, and immutable URLs are valid")
    else:
        add(arguments)


if __name__ == "__main__":
    main()
