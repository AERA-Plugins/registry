# AERA Plugin Registry

Official signed catalog consumed by AERA Recovery Project's Plugin Manager.

The recovery image pins the AERA Ed25519 public key. `catalog.json.sig` signs
the exact bytes of `catalog.json`; each listed plugin also publishes a signed
manifest that pins its payload size and SHA-256.

Only reviewed repositories in the `AERA-Plugins` organization may be added.
Changing a catalog URL cannot bypass manifest or payload verification.

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
