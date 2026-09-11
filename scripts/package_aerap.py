#!/usr/bin/env python3
"""Build a deterministic AERA plugin package from signed release files."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile


MAX_MANIFEST = 64 * 1024
MAX_SIGNATURE = 4096
MAX_PAYLOAD = 512 * 1024 * 1024
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}[a-z0-9]$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_signature(manifest: Path, signature: Path, public_key: Path) -> None:
    text = signature.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{128}", text):
        raise ValueError("signature must be 64 bytes encoded as lowercase hex")
    with tempfile.TemporaryDirectory(prefix="aerap-signature-") as directory:
        raw = Path(directory) / "signature.raw"
        raw.write_bytes(bytes.fromhex(text))
        subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-rawin", "-pubin",
             "-inkey", str(public_key), "-sigfile", str(raw),
             "-in", str(manifest)],
            check=True,
            stdout=subprocess.DEVNULL,
        )


def add_file(archive: zipfile.ZipFile, name: str, source: Path) -> None:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100444 << 16
    with source.open("rb") as input_file, archive.open(info, "w") as output_file:
        shutil.copyfileobj(input_file, output_file, 1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--signature", type=Path)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    manifest = arguments.manifest.resolve(strict=True)
    payload = arguments.payload.resolve(strict=True)
    signature = (arguments.signature.resolve(strict=True)
                 if arguments.signature else None)
    if manifest.stat().st_size > MAX_MANIFEST:
        raise ValueError("plugin manifest exceeds the AERA limit")
    if payload.stat().st_size <= 0 or payload.stat().st_size > MAX_PAYLOAD:
        raise ValueError("plugin payload is empty or exceeds the AERA limit")
    if signature and signature.stat().st_size > MAX_SIGNATURE:
        raise ValueError("plugin signature exceeds the AERA limit")

    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    plugin_id = metadata.get("id", "")
    if metadata.get("schema") != 1 or not SAFE_ID.fullmatch(plugin_id):
        raise ValueError("unsupported plugin manifest or unsafe plugin id")
    if metadata.get("payload") != "runtime.xz":
        raise ValueError("AERA host API 1 requires payload name runtime.xz")
    if metadata.get("payload_size") != payload.stat().st_size:
        raise ValueError("payload size does not match plugin.json")
    if metadata.get("payload_sha256", "").lower() != sha256(payload):
        raise ValueError("payload SHA-256 does not match plugin.json")
    if signature and arguments.public_key:
        verify_signature(manifest, signature,
                         arguments.public_key.resolve(strict=True))

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", metadata["name"]).strip("-")
    output = (arguments.output or
              Path(f"{safe_name}-{metadata['version']}.aerap")).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".new")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
        add_file(archive, "plugin.json", manifest)
        if signature:
            add_file(archive, "plugin.json.sig", signature)
        add_file(archive, "runtime.xz", payload)
    temporary.replace(output)
    print(json.dumps({
        "path": str(output),
        "official": signature is not None,
        "size": output.stat().st_size,
        "sha256": sha256(output),
    }, indent=2))


if __name__ == "__main__":
    main()
