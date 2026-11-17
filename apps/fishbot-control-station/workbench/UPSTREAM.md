# Robot workbench upstream

This directory contains Lichtblick v1.29.1 source, imported from the official repository.

- Repository: https://github.com/lichtblick-suite/lichtblick
- Commit: `95713edb309d77589b130286642ab149995a5f7b`
- Archive: https://codeload.github.com/lichtblick-suite/lichtblick/tar.gz/95713edb309d77589b130286642ab149995a5f7b
- Archive SHA-256: `4476b6e75cf50202bc0c74c228b094b248de0a09de3a73ba4e362cbae4a3228f`
- Archive size: 17,376,926 bytes; source files: 2,297.
- License: MPL-2.0; retain LICENSE, file notices, and third-party declarations.
- Toolchain: Node >=20, Yarn 4.17.0, unchanged yarn.lock.

Use `../workbench-dev.sh install --immutable` for the pinned toolchain. The launcher isolates Corepack's cache from unrelated parent package scopes and disables installation of Git hooks and desktop browser binaries. It does not change global Node configuration.

Upstream AGENTS.md mentions an older Yarn version. The exact packageManager declaration and lockfile determine this import's version. The tracked `.yarn/yarn-wrapper.js` is required even though the upstream ignore rule matches it.

The application fork remains in the existing FishBot repository. Project-specific changes must keep upstream ownership notices and remain reviewable separately from the import. Simulation recordings and runtime reports remain outside the committed source.

## Project adaptation

The complete import is commit `0eaa6d9`. Subsequent project changes are isolated from that import:

- `packages/suite-base/src/panels/EpisodeReview/`: read-only project panel and parser tests, using the original Panel and MessagePipeline APIs.
- `packages/suite-base/src/panels/index.ts`: native panel registration.
- `packages/suite-base/src/providers/WorkspaceContextProvider.tsx`: collapse the settings sidebar for new users; persisted preferences retain precedence.
- `packages/suite-web/src/WebRoot.tsx`: default to seconds for the simulation workbench; persisted time preferences retain precedence.
- `robot-layouts/`: desktop and mobile layouts in the upstream layout format.
- `web/webpack.config.ts`: use the existing HTML options to declare a device-width mobile viewport.

Original contributions retain their own SPDX copyright and MPL notice. The three EpisodeReview files locally disable the upstream license-header lint rule because that rule hardcodes BMW ownership. Other lint rules remain enabled. Existing upstream ownership notices are unchanged.

The source import retains official test fixtures, including files matched by the parent repository's runtime-data ignore rules. Newly generated simulation data, MCAP files, media, manifests, and browser reports remain ignored.
