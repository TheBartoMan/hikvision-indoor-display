# Release Tools

Run `python3 scripts/release.py check --require-metadata` from the repository root
to audit source and publishing metadata. Use `build --require-metadata` to create
the reproducible source archive in `dist/`.

These tools do not upload files, authenticate to GitHub or publish releases.
See `PUBLISHING.md` for the publication process and review requirements.
