# Public material and license audit

The source application is MIT licensed (root LICENSE). The English edition
continues the authors' earlier application with a standalone package, English
copy, samples, provider configuration and independent state. No private
dependency, model weights, provider login, personal recording or external photo
is required or included. Model names are identifiers, not endorsement claims.

## Font assets

| Asset | Attribution | License | Modification |
| --- | --- | --- | --- |
| `Gaegu-Bold-latin.woff2` | Copyright 2018 The Gaegu Project Authors; JIKJI SOFT | SIL OFL 1.1 | Latin subset / WOFF2 |
| `Nunito-latin-var.woff2` | Copyright 2014 The Nunito Project Authors; Vernon Adams, Cyreal, Jacques Le Bailly | SIL OFL 1.1 | Latin subset / WOFF2, weight range 200–1000 |

Complete font license texts and copyright statements are in
`ask_three_en/web/fonts/OFL-Gaegu.txt` and `OFL-Nunito.txt`. NOTICE identifies
the upstream sources and modifications. The source copyright declarations list
no Reserved Font Names. These fonts retain OFL, independently of the application
MIT license. Source and installed wheels include both full OFL texts and NOTICE.
FontTools and Brotli were build tools, not runtime dependencies or bundled code.

Upstream notices checked against the Google Fonts
[Gaegu license](https://github.com/google/fonts/blob/main/ofl/gaegu/OFL.txt) and
[Nunito license](https://github.com/google/fonts/blob/main/ofl/nunito/OFL.txt).
Asset hashes are recorded by `scripts/public_audit.py` and in
`docs/verification/public-audit.json`.

## Separately installed dependencies

Dependencies are fetched by pip and retain their own licenses. The tested
versions are in `constraints.txt`; no dependencies are vendored in this repo.
The complete tested installed distribution/version/license inventory is in
`docs/verification/dependency-licenses.json`, generated from wheel metadata.
This inventory covers development packages as well as runtime packages and
does not change their upstream terms.

The primary runtime libraries are FastAPI (MIT), Uvicorn (BSD-3-Clause), and
websockets (BSD-3-Clause). Their installed notices and those of transitive
dependencies remain in the respective distributions. Optional Playwright and
its separately downloaded browser have their own licenses; neither browser
binary nor provider CLI is bundled. Provider service terms and usage charges
are separate from the code license.

## Screenshots and publication boundary

All images in `docs/screenshots/` are browser captures of original CSS and the
bundled fictional examples, with fixture seats visibly stamped. They contain
no real users, voice recordings, account names, tokens or private endpoints.
The application screenshots are reusable under the application MIT license;
rendering the fonts in a screenshot does not relicense the font files.

`scripts/public_audit.py` scans the Git candidate set, including authored but
not yet tracked files. It rejects runtime state, credential files, private home
paths, local network addresses, secret-like strings, Korean text in shipped
text, unreviewed binary types and textual/EXIF screenshot metadata. It checks
font signatures and full license notices. This is a bounded automated check
plus manual provenance review, not a claim that pattern matching detects every
possible secret. Inspect the staged file list before creating any public remote.
