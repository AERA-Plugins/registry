# AERA Plugin Registry

Official signed catalog consumed by AERA Recovery Project's Plugin Manager.

The recovery image pins the AERA Ed25519 public key. `catalog.json.sig` signs
the exact bytes of `catalog.json`; each listed plugin also publishes a signed
manifest that pins its payload size and SHA-256.

Only reviewed repositories in the `AERA-Plugins` organization may be added.
Changing a catalog URL cannot bypass manifest or payload verification.

## Make a plugin

An AERA plugin is one `.aerap` file containing a manifest and a compressed
runtime:

```text
My-Plugin-1.0.0.aerap
├── plugin.json
├── plugin.json.sig       # official plugins only
└── runtime.xz
```

Build the files your plugin needs in a staging directory such as `stage/`.
Executables normally go in `stage/usr/bin`, libraries in `stage/usr/lib`, and
licenses in `stage/usr/share/licenses`. Do not include device nodes, absolute
paths, or links that leave the staging directory.

Use an existing plugin's `source/pack.py` to convert that directory into the
bounded AERA `runtime.xz` format:

```sh
python3 source/pack.py stage build
```

Create `plugin.json` using the values printed in `build/metadata.json`:

```json
{
  "schema": 1,
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "description": "A short description.",
  "type": "ui-runtime",
  "entry": "main",
  "min_host_api": 2,
  "protocol_version": 2,
  "executable": "usr/bin/aera-plugin",
  "icon": "plugin",
  "payload": "runtime.xz",
  "payload_url": "https://example.invalid/runtime.xz",
  "payload_size": 1234,
  "payload_sha256": "64-lowercase-hex-characters",
  "expanded_size": 5678,
  "expanded_sha256": "64-lowercase-hex-characters",
  "member_count": 3,
  "permissions": ["display", "touch-input", "read-only-storage"]
}
```

Host API 2 accepts new IDs without recovery-side routing. The isolated ARM64
worker communicates over file descriptor 4 while AERA owns all visible UI and
privileged operations. Its manifest must request `display` and `touch-input`.
See the `AERA-settings-backup-plugin` reference and recovery's
`ui2/plugin_api/README.md` for protocol negotiation, declarative UI, lifecycle,
resource limits, and mediated permissions.

Host API 1 remains compatible with the built-in `browser`, `retroarch`,
`telegram`, `gallery`, `media`, `recorder`, and `appvault` entries.

Finally, create the installable file:

```sh
python3 scripts/package_aerap.py \
  --manifest plugin.json \
  --payload build/runtime.xz \
  --output My-Plugin-1.0.0.aerap
```

This creates an **unofficial** plugin. AERA allows its installation after a
security warning and lists it under **Unofficial Apps**. Only AERA maintainers
can sign reviewed releases with the private release key and publish them as
**Official Apps**.

## Publishing without breaking the store

Do not edit or sign `catalog.json` by hand. After the plugin manifest and its
hex-encoded signature are pushed, run:

```sh
python3 scripts/catalog_tool.py add \
  --manifest ../AERA-example-plugin/plugin.json \
  --commit FULL_40_CHARACTER_COMMIT \
  --key ../.aera-plugin-release-key.pem \
  --online
```

The command verifies the current catalog, verifies the plugin signature,
requires an immutable Git commit URL, signs into AERA's required lowercase-hex
format, verifies the result again, and only then atomically replaces the two
catalog files. CI repeats the complete public-key and remote-URL validation.

## Downloadable `.aerap` packages

The Plugin Manager store and the recovery Files app use the same `.aerap`
artifact. An official bundle contains exactly `plugin.json`,
`plugin.json.sig`, and `runtime.xz`. Build it from the already signed release
files with:

```sh
python3 scripts/package_aerap.py \
  --manifest ../AERA-example-plugin/plugin.json \
  --signature ../AERA-example-plugin/plugin.json.sig \
  --payload ../AERA-example-plugin/build/runtime.xz \
  --public-key keys/catalog-public.pem
```

Third-party developers may omit `--signature` to create an unofficial bundle.
AERA presents an explicit privileged-code warning and requires an additional
confirmation before installing it. Renaming an unsigned package never makes it
official; the recovery derives trust from the embedded Ed25519 signature.
