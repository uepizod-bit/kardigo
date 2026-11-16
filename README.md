# KADRGO Studio

Windows desktop video editor. Read [README_UZ.md](README_UZ.md) for features and alpha limitations.

Run `python ci/prepare_assets.py --all` to retrieve SHA256-verified upstream models and native plugins excluded from Git. Original fonts, SFX and shader sources are included. Native Windows CI validates the editing engine, CPU integrations and Qt startup. GPU and installer validation remain separate.

The Windows workflow also builds the installer, performs a silent install, starts the private runtime/Qt window, then verifies uninstall preserves user data. Download its artifact only from a successful run.
