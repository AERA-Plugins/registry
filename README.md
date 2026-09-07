# AERA Plugin Registry

Official signed catalog consumed by AERA Recovery Project's Plugin Manager.

The recovery image pins the AERA Ed25519 public key. `catalog.json.sig` signs
the exact bytes of `catalog.json`; each listed plugin also publishes a signed
manifest that pins its payload size and SHA-256.

Only reviewed repositories in the `AERA-Plugins` organization may be added.
Changing a catalog URL cannot bypass manifest or payload verification.
