# cloud-tasks

Native GTK4/libadwaita app and Bash-friendly CLI. Python's standard library owns
the application logic; PyGObject is only imported for the desktop UI. The iCloud Rust backend under `icloud/` is product-owned and ships privately;
only icloud-session is shared externally. The private helper and `gws` are
invoked as argument arrays, never shell code. No second authentication store or sync engine.

Run `bin/check` (provider rustfmt/clippy/tests, Python tests, native smoke test when GTK is
available); `.githooks/pre-push` runs it before a push (`git config core.hooksPath .githooks` once per
clone, `NO_CHECK=1` skips it).
Tests use temporary HOME/config and fake CLIs; never read live accounts, launch
the UI on the owner's desktop, or modify their contacts/tasks. Provider writes
are explicit. Preserve unknown fields, account IDs, and partial-result warnings.

CLI output, errors and exit codes follow the shared product contract in `cloud_tasks/cli_output.py`
(text on a terminal, JSON envelope when piped; exit 0/1/2 usage/3 auth/4 not found/5 unavailable). Keep that
file identical across product repositories.

Packaging: `packaging/aur/cloud-tasks/PKGBUILD` builds from the tag archive; `packaging/repo/` holds
the signed-repo `install.sh` and its tests (in `bin/check`). `bin/build-package <arch>` is the
native, unsigned package build (`sudo bin/arch-run bin/build-package "$(uname -m)" /output` runs
it in a disposable Arch chroot, as the `Native packages` workflow does for each tag);
`bin/release <version>` is maintainer-only signing and publishing; `bin/verify-release`.

Release: bump the version in `pyproject.toml`, `cloud_tasks/__init__.py`, `icloud/Cargo.toml`
(+ `icloud/Cargo.lock`) and `pkgver` in the PKGBUILD together, push, tag `vX.Y.Z` and push the tag,
`gh release create vX.Y.Z --draft --verify-tag --generate-notes`, then `bin/release X.Y.Z` (waits
for the tag's Native packages run; the signing key lives only in the maintainer's keyring, never
CI). Do not run release scripts unless asked.
