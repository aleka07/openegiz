# Vendored Grafana plugins

Grafana loads two frontend-only plugins at pod start. Upstream they were fetched
from `ertis-research` GitHub releases on **every** pod start, which made the
platform depend on GitHub availability at runtime and on a mutable `latest` tag.
The zips are vendored here instead, rebranded to OpenEgiz, and served from this
repository over `raw.githubusercontent.com`.

## Layout

| Path | Contents |
| --- | --- |
| `ertis-opentwins-app.zip` | Patched app plugin — consumed by the Grafana init container |
| `ertis-unity-panel.zip` | Patched panel plugin — consumed by the Grafana init container |
| `upstream/*.zip` | Unmodified originals, kept for provenance and diffing |
| `patch-branding.py` | Regenerates the two patched zips from `upstream/` |

Consumed by the `install-opentwins-plugins` init container in `values.yaml`
(under `grafana.extraInitContainers`).

## Upstream sources

| Plugin | Release asset URL | Release |
| --- | --- | --- |
| `ertis-opentwins-app` | `https://github.com/ertis-research/opentwins-in-grafana/releases/download/latest/ertis-opentwins-app.zip` → redirects to `ertis-research/grafana-app-opentwins` | tag `latest`, published 2026-04-15, target `main`, plugin version 2.0.2 |
| `ertis-unity-panel` | `https://github.com/ertis-research/grafana-panel-unity/releases/download/latest/ertis-unity-panel.zip` | tag `latest`, published 2025-01-09, target `main`, plugin version 1.0.0 |

Both upstream releases use a **rolling `latest` tag**, so the artifact behind
those URLs can change without notice. The `upstream/` copies are the exact bytes
downloaded on 2026-08-07.

### sha256 — originals (`upstream/`)

```
67e249a50fc772a85f25674db61b2afe41f57dfbe6ce74d6c098ab0001e2e6cd  ertis-opentwins-app.zip
83f10ef4db06ab552331f5a548b8370b9fa936ed0abd857d7d3dbc674ff9241a  ertis-unity-panel.zip
```

### sha256 — patched

```
e9cba38f436ed2188dab27717db83c84f1bd92c007ed323526f257bc4609c715  ertis-opentwins-app.zip
a9ed72a03557b389a1f364d3fcac4cd3c6ba079e2df6812d79516f1ff1c50c13  ertis-unity-panel.zip
```

## Regenerating

```sh
python3 patch-branding.py            # rebuild both zips from upstream/
python3 patch-branding.py --check    # verify the shipped zips match a fresh run
```

The script is the single source of truth for what gets rebranded — the tables
below describe what it does, but the code is authoritative. Every replacement
goes through a helper that requires **exactly one** match and aborts otherwise,
so an upstream refresh that reflows any of these strings fails loudly instead of
silently shipping a half-rebranded plugin.

It reads `openegiz_logo_centered.svg` from the repo root and rebuilds the
archives entry by entry, preserving names, order, timestamps and modes, so the
layout unzipped by the init container is identical to upstream's.

## What is patched

Only display-level strings and image assets. **Plugin ids, versions,
dependencies, routes and `includes` are untouched** — the compiled bundles
reference the ids (`ertis-opentwins-app`, `ertis-unity-panel`) and Grafana
resolves plugin assets under `public/plugins/<id>/`, so renaming an id would
break the plugin.

### `ertis-opentwins-app.zip` — 7 of 27 entries changed

| File | Change |
| --- | --- |
| `plugin.json` | `name`: `"OpenTwins"` → `"OpenEgiz"` |
| `img/logo.svg` | OpenEgiz logo (referenced by `info.logos.small` and `.large`) |
| `6824e6a2fada2cf50285.svg` | OpenEgiz logo — webpack-hashed copy of the same asset, rendered as the in-app header logo by `396.js` |
| `README.md` | Rendered by Grafana on the plugin details page: H1, intro sentence, and the "OpenTwins middleware" config note |
| `202.js` | Config-page alert: `"The OpenTwins plugin is active…"` → `"The OpenEgiz plugin is active…"` |
| `396.js` | Header `<h1>OpenTwins</h1>` → `<h1>OpenEgiz</h1>`, and the header logo's `alt="OpenTwins Logo"` → `"OpenEgiz Logo"` |
| `module.js` | SRI digests for chunks 202 and 396 recomputed (see below) |

### `ertis-unity-panel.zip` — 1 of 13 entries changed

| File | Change |
| --- | --- |
| `README.md` | The one OpenTwins mention reworded to name OpenEgiz while keeping the upstream link and the historical fact |

Its `plugin.json` is **not** modified — it contains no OpenTwins branding
(`name` is `"Unity"`, description is `"Unity WebGL render in Grafana panel"`).
Its `img/logo.svg` is deliberately left as the upstream **Unity engine mark**:
that icon is what makes the panel findable in Grafana's panel picker, and
replacing it with the OpenEgiz wordmark would only make the panel harder to
identify.

### Attribution

`info.author` (`ERTIS`), `info.links`, the bundled `LICENSE`, and every link
pointing at an upstream repo or the OpenTwins documentation site are left
intact. The plugins are ERTIS work under Apache-2.0; stripping attribution while
putting our name on them is both bad practice and a licence-compliance problem.
Link *text* naming the upstream project is kept too — relabelling
`[OpenTwins](github.com/ertis-research/opentwins)` as "OpenEgiz" would simply
make the link wrong.

### The logo asset

`openegiz_logo_centered.svg` at the repo root is a 1600×1600 canvas whose artwork
only occupies 1242×296 in the middle — roughly 85% empty space, which would
render as a tiny smudge in a Grafana plugin icon slot. The vendored copy is the
same artwork with the `viewBox` tightened to the measured ink bounds:

```
width="1600" height="1600" viewBox="0 0 1600 1600"
→ width="1282" height="336"  viewBox="160 632 1282 336"
```

Nothing else in the SVG changes. No raster conversion is needed — both plugins
reference `.svg` logos only.

## Subresource Integrity

`module.js` pins a sha256 digest for each lazy-loaded chunk:

```js
sriHashes = { 126: "sha256-…", 202: "sha256-…", 396: "sha256-…" }
```

Editing `202.js` or `396.js` without updating the matching digest makes Grafana
refuse to load the chunk, and the plugin renders a blank page. `patch-branding.py`
recomputes the digest of each chunk after patching and rewrites the entry.
`module.js` carries no digest of itself, so rewriting it in place is safe.

The digest is `"sha256-" + base64(sha256(chunk_bytes))`. This was verified
against the untouched upstream archive: recomputing all three digests from the
pristine chunks reproduces upstream's pinned values byte for byte, which is what
makes the recompute trustworthy.

Resulting digests after patching:

```
chunk 126: sha256-YkO0yBajsd/XcMq4iQ0/+wZasE9zuNivcuC0y4YQZ7o=   (unchanged)
chunk 202: sha256-pYrrTmfakB0nuzJzqDtk1uVJuuDhRUaYDFzoenkDVD4=   (was tRtY9d7b…)
chunk 396: sha256-/5RahZpwopAvCvd/69e79PkDgcxyfitfXZd+BpXWlp0=   (was OiLhvZ4j…)
```

## What is deliberately NOT renamed

These look like branding but are load-bearing:

| String | Where | Why |
| --- | --- | --- |
| `ertis-opentwins-app`, `ertis-unity-panel` | `plugin.json` `id`, `module.js` public path, `396.js` plugin-proxy base | Grafana serves assets from `public/plugins/<id>/` and routes `api/plugin-proxy/<id>/` |
| `webpackChunkertis_opentwins_app` | all chunks | webpack runtime global; renaming in one chunk breaks loading |
| `opentwins.agents/name`, `opentwins.agents/twins` | `396.js` | Kubernetes label keys the plugin writes onto Deployments/CronJobs and reads back; renaming breaks twin-to-agent linking at runtime |

## Known limitation

The source maps (`*.js.map`) still contain the pre-rebrand sources and are now
a few columns out of sync with the patched chunks, since `OpenTwins` (9 chars)
became `OpenEgiz` (8). Source maps are not SRI-checked and are only reachable
through browser devtools, so this has no user-facing effect.

If the upstream app plugin is rebuilt, the webpack content hash in
`6824e6a2fada2cf50285.svg` will change — re-derive that filename from the new
archive listing rather than assuming it.
