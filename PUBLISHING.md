# Publishing

## Current Status

- Release source is version 1.0.0.
- Public repository/maintainer: `TheBartoMan/hikvision-indoor-display`, `@TheBartoMan`.
- Camera selection, display on/off and Home have been confirmed by an installation
  tester on the supported firmware profile; broader acceptance remains outstanding.
- GitHub source publication, hosted validation and release creation are in progress.
- Brands and default HACS catalog inclusion have not been approved.
- Local unit tests are not a substitute for live acceptance or hosted validation.

Do not claim publication, HACS approval or completed physical tests until those
steps have actually happened. Do not upload a development workspace or unrelated
archives. Publish only this audited release directory or its generated source archive.

## Repository Setup

1. Choose a GitHub user or organisation to own one public repository containing this
   integration. A community organisation can avoid using a private person's name in
   public repository URLs. Maintainers/codeowners are public GitHub identities, not
   station configuration.
2. Configure actual metadata, replacing the example arguments:

   ```sh
   python3 scripts/release.py configure --repository ORGANISATION/hikvision-indoor-display --maintainer GITHUB_USERNAME
   ```

3. Enable repository issues and private vulnerability reporting. Set a description
   and relevant topics such as `home-assistant`, `hacs`, `hikvision`, `intercom`.
4. Run tests and the local source audit:

   ```sh
   python3 -m pip install -r requirements-test.txt
   python3 -B -m unittest discover -s tests -v
   python3 scripts/release.py check --require-metadata
   python3 scripts/release.py build --require-metadata
   ```

   The build produces a source ZIP in `dist/`, with deterministic timestamps and no
   filesystem owner metadata. It excludes caches, Git history and unlisted files.
5. Push only this release directory. Git author/committer identity and the repository
   account are public GitHub metadata; configure an appropriate public identity and
   GitHub no-reply address separately if needed. Never publish private machine paths,
   backups, SSH keys, packet captures, diagnostic exports or device credentials.

## Store Availability

This is a custom integration for **HACS**, not a Supervisor app for the Apps store.
HACS requires a public GitHub repository. Once its metadata and validation are in
place, users can add the repository URL as a custom **Integration** repository.

Run the included HACS and hassfest GitHub Actions and resolve all findings. Add the
integration icon through the Home Assistant brands contribution process using an
asset with appropriate redistribution rights. Do not claim the brands check passes
before it does. The hosted actions have not been executed during local preparation.

Complete and record `ACCEPTANCE.md`. Create a GitHub release tagged `v1.0.0` with
the changelog and audited source archive. A tag by itself is not a GitHub release.
Publish it as a stable, non-prerelease release only after acceptance is confirmed.

For default HACS search/catalog inclusion, an owner or major contributor must submit
a separate pull request to `hacs/default` after the validation and brands checks
pass. A repository may be organisation-owned, but HACS asks that the editable
submission PR come from a personal fork, not an organisation fork. Inclusion depends
on HACS review and merge; publishing a GitHub release does not guarantee it.

References: [HACS general requirements](https://www.hacs.dev/docs/publish/start/),
[integration requirements](https://www.hacs.dev/docs/publish/integration/),
[default catalog submission](https://www.hacs.dev/docs/publish/include/).
