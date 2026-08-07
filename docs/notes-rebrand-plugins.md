# Rebrand-lite part 1 — Grafana plugins vendored and rebranded

**Date:** 2026-08-07

Two goals, both done:

1. Kill the runtime dependency on `ertis-research` GitHub releases — Grafana was
   re-downloading both plugins from GitHub on *every* pod start.
2. Rebrand the user-visible name, logo and text of those plugins to OpenEgiz,
   without touching plugin ids (the compiled bundles reference them).

Done in two passes: a conservative first pass (`plugin.json` + logos only), then
a second pass after orchestrator sign-off that added the in-zip READMEs, the
SRI-aware compiled-JS patch, and reverted the Unity panel logo. This document
describes the final state.

## 1. What the init container used to do

`values.yaml` → `grafana.extraInitContainers[0]` (`install-opentwins-plugins`,
`busybox`) ran, on every pod start:

```sh
wget ... https://github.com/ertis-research/opentwins-in-grafana/releases/download/latest/ertis-opentwins-app.zip
wget ... https://github.com/ertis-research/grafana-panel-unity/releases/download/latest/ertis-unity-panel.zip
```

Two problems beyond the obvious availability coupling:

- The first URL **redirects** — `opentwins-in-grafana` was renamed to
  `grafana-app-opentwins`. It works today only because GitHub keeps the redirect
  alive. That breaks the day someone creates a new repo under the old name.
- Both releases use a **rolling `latest` tag**. Upstream can replace the artifact
  at any time and the cluster would silently pick up a different build.

Both plugins are frontend-only (no backend binaries), which is why they can be
dropped into `/grafana-storage/plugins` as plain unzipped directories and loaded
unsigned via `allow_loading_unsigned_plugins`.

## 2. Downloads and provenance

Downloaded 2026-08-07.

| Plugin | Size | sha256 |
| --- | --- | --- |
| `ertis-opentwins-app.zip` | 477 059 B | `67e249a50fc772a85f25674db61b2afe41f57dfbe6ce74d6c098ab0001e2e6cd` |
| `ertis-unity-panel.zip` | 129 659 B | `83f10ef4db06ab552331f5a548b8370b9fa936ed0abd857d7d3dbc674ff9241a` |

Release metadata: app = tag `latest`, published 2026-04-15, target `main`,
plugin version 2.0.2. Unity = tag `latest`, published 2025-01-09, target `main`,
plugin version 1.0.0.

Originals archived unmodified at `vendor/grafana-plugins/upstream/`.

## 3. Inspection

**One `plugin.json` per archive — no nested plugins.** The app zip has 27 entries,
the unity zip 13.

| | app | unity |
| --- | --- | --- |
| `id` | `ertis-opentwins-app` | `ertis-unity-panel` |
| `name` (before) | `OpenTwins` | `Unity` |
| `description` | `Grafana app plugin for digital twins` | `Unity WebGL render in Grafana panel` |
| `info.logos.small` / `.large` | `img/logo.svg` (both) | `img/logo.svg` (both) |

Notes:

- Neither `description` mentions OpenTwins, so neither was rewritten.
- The unity panel carries no OpenTwins branding at all — its `name` is `Unity`
  and its logo is the Unity engine mark.
- `allow_loading_unsigned_plugins` also lists `ertis-opentwins`, which does not
  exist in either archive. Harmless leftover from an older panel plugin.
- The app archive contains `6824e6a2fada2cf50285.svg` at its root, byte-identical
  to `img/logo.svg`. It is the webpack-emitted copy that `396.js` renders as the
  in-app header logo. Not referenced from `plugin.json`, but very much visible.
- The two READMEs use **different line endings** — the app one is CRLF, the unity
  one LF. Patch anchors have to stay inside a single line to be agnostic to that.
  The first attempt failed loudly on exactly this, which is the guard working.

## 4. `OpenTwins` occurrences in compiled JS — before

17 case-insensitive matches across the app bundle, **only 3 user-visible**:

| File | matches | user-visible | what they are |
| --- | --- | --- | --- |
| `module.js` | 5 | 0 | build banner, webpack unique-name, `public/plugins/ertis-opentwins-app/` public path, `webpackChunkertis_opentwins_app` ×2 |
| `126.js` | 2 | 0 | `webpackChunkertis_opentwins_app` ×2 |
| `202.js` | 3 | **1** | 2× webpack chunk global; 1× alert text |
| `396.js` | 7 | **2** | 2× webpack chunk global, `const Y="ertis-opentwins-app"` (plugin-proxy base path), `opentwins.agents/name` + `opentwins.agents/twins` k8s labels; 2× UI text |
| `ertis-unity-panel/module.js` | 0 | 0 | — |

The three user-visible strings, all now patched:

1. `396.js` — `React.createElement("h1", {className: appName}, "OpenTwins")`
   → the app header title, shown on **every page** of the plugin.
2. `396.js` — `alt: "OpenTwins Logo"` on the header `<img>`.
3. `202.js` — `"The OpenTwins plugin is active and ready to use."` on the plugin
   config page, enabled branch of an `<Alert>`.

**Result: zero occurrences of `OpenTwins` remain in any compiled chunk.**

Everything else was left alone deliberately — `opentwins.agents/name` and
`opentwins.agents/twins` are Kubernetes label keys the plugin writes onto
Deployments/CronJobs and reads back, and the id strings drive Grafana's asset
paths and `api/plugin-proxy/` routing. All five were asserted present after
patching.

Source maps (`*.js.map`) still hold ~133 occurrences and are now a few columns
out of sync with the patched chunks (`OpenTwins` is 9 chars, `OpenEgiz` is 8).
Not SRI-checked, only reachable through browser devtools; left alone.

## 5. The SRI problem, and how it was solved

`module.js` pins a Subresource Integrity digest for each lazy-loaded chunk:

```js
sriHashes = {
  126: "sha256-YkO0yBajsd/XcMq4iQ0/+wZasE9zuNivcuC0y4YQZ7o=",
  202: "sha256-tRtY9d7b9COi/xbMlBa9og+MXdtfC1KaIq9BzH5ILlI=",
  396: "sha256-OiLhvZ4ju7NR24eDWMdgPGjmnxpdWNfVuZ9OqsOg34w=",
}
```

Both remaining UI strings live in `202.js` and `396.js`. Editing either byte
makes the digest mismatch and Grafana refuses to load the chunk — the plugin
renders a blank page.

The digest format is `"sha256-" + base64(sha256(chunk_bytes))`. **Verified before
touching anything** by recomputing all three digests from the pristine upstream
chunks: all three reproduce upstream's pinned values exactly. That is what makes
the recompute trustworthy rather than a guess.

`module.js` carries no digest of itself, so rewriting it in place is safe.

Result after patching:

```
chunk 126: sha256-YkO0yBajsd/XcMq4iQ0/+wZasE9zuNivcuC0y4YQZ7o=   (unchanged)
chunk 202: sha256-pYrrTmfakB0nuzJzqDtk1uVJuuDhRUaYDFzoenkDVD4=   (was tRtY9d7b…)
chunk 396: sha256-/5RahZpwopAvCvd/69e79PkDgcxyfitfXZd+BpXWlp0=   (was OiLhvZ4j…)
```

The patcher re-reads `module.js` after writing and asserts every pinned digest
matches its chunk, so a botched rewrite cannot ship.

## 6. What was patched

All of it is done by `vendor/grafana-plugins/patch-branding.py`, which rebuilds
both zips from `upstream/`. Every replacement goes through a helper that requires
**exactly one** match and aborts otherwise — an upstream refresh that reflows any
of these strings fails loudly instead of silently shipping a half-rebranded plugin.

App plugin — 7 of 27 entries:

| File | Change |
| --- | --- |
| `plugin.json` | `"name": "OpenTwins"` → `"OpenEgiz"` |
| `img/logo.svg` | → OpenEgiz logo |
| `6824e6a2fada2cf50285.svg` | → OpenEgiz logo (in-app header) |
| `README.md` | H1, intro sentence, "OpenTwins middleware" config note |
| `202.js` | config-page alert sentence |
| `396.js` | header `<h1>` and header logo `alt` |
| `module.js` | SRI digests for 202 and 396 |

Unity panel — 1 of 13 entries: `README.md` only.

Untouched everywhere: ids, versions, `dependencies`, `routes`, `includes`,
`LICENSE`, `info.author`, `info.links`, and **the Unity panel's logo** (see §8).

### Attribution

`info.author` (`ERTIS`), the upstream repo/license links, and the bundled
`LICENSE` are intact. The plugins are ERTIS work under Apache-2.0; stripping
attribution while putting our name on them is both bad practice and a
licence-compliance problem.

Link *text* naming the upstream project was kept as well. Relabelling
`[OpenTwins](github.com/ertis-research/opentwins)` as "OpenEgiz" would just make
the link wrong. So the app README now reads:

> The **OpenEgiz App Plugin** serves as the central frontend interface for the
> OpenEgiz platform, built on [OpenTwins](https://github.com/ertis-research/opentwins).

and the "OpenTwins Official Documentation" link keeps its label, because that is
genuinely what it points at. The unity README's single mention became:

> originally designed as an extension to [OpenTwins](…), the digital twin platform
> behind OpenEgiz, it has no dependency on it

which names OpenEgiz for the reader without falsifying the history.

### The logo

Both plugins reference `.svg` logos only, so no raster conversion was needed —
`rsvg-convert` was used solely to render previews and measure the artwork, not to
produce a shipped asset.

`openegiz_logo_centered.svg` is a 1600×1600 canvas whose ink only spans
(180, 652)–(1422, 948), i.e. 1242×296 — about 85% of the file is empty margin.
Dropped straight into a Grafana icon slot that renders as a barely-visible smudge.
The shipped copy is the same artwork with the `viewBox` tightened to the measured
bounds plus 20 units of padding:

```
width="1600" height="1600" viewBox="0 0 1600 1600"
→ width="1282" height="336"  viewBox="160 632 1282 336"
```

Verified by re-rendering: nothing clipped. No other change to the SVG.

## 7. Repack and verification

`patch-branding.py` rebuilds each archive entry by entry in pure Python,
preserving entry names, order, timestamps and modes, and keeping the directory
entries — so the init container's `unzip -o` yields exactly the same paths as
upstream.

Per-entry sha256 comparison against `upstream/`:

```
ertis-opentwins-app.zip   27 -> 27 entries, same names: True, 15 unchanged
  CHANGED: 202.js  396.js  6824e6a2fada2cf50285.svg  README.md
           img/logo.svg  module.js  plugin.json
ertis-unity-panel.zip     13 -> 13 entries, same names: True,  9 unchanged
  CHANGED: README.md
```

Exactly the intended entries, nothing else.

The compiled-JS edits were checked at byte level by locating the outermost
differing region between upstream and patched:

```
202.js    8556 ->  8555 chars   differing span 5 -> 4
          'Twins' -> 'Egiz'
396.js  190988 -> 190986 chars  differing span 92 -> 90
          'Twins Logo",className:n.logoImage})),…{className:n.appName},"OpenTwins'
       -> 'Egiz Logo",className:n.logoImage})),…{className:n.appName},"OpenEgiz'
module.js 238336 -> 238336 chars  differing span 101 -> 101
          only the two base64 digests
```

No collateral damage anywhere in the bundles.

Shipped sha256:

```
e9cba38f436ed2188dab27717db83c84f1bd92c007ed323526f257bc4609c715  ertis-opentwins-app.zip
a9ed72a03557b389a1f364d3fcac4cd3c6ba079e2df6812d79516f1ff1c50c13  ertis-unity-panel.zip
```

## 8. Why the Unity panel keeps its logo

First pass replaced it with the OpenEgiz wordmark; second pass reverted it, and
`img/logo.svg` is now byte-identical to upstream again.

The panel has no OpenTwins branding to remove — `name` is `"Unity"`, the
description is about Unity WebGL, and the icon is the Unity engine mark. That
icon is a *functional identifier*: it is how you find the panel in Grafana's
panel picker among a few dozen others. Swapping it for a 4.2:1 OpenEgiz wordmark
made the panel harder to identify and rebranded nothing.

## 9. `values.yaml` change

Only the two URLs changed; the rest of the init script is byte-identical.

```diff
-wget ... https://github.com/ertis-research/opentwins-in-grafana/releases/download/latest/ertis-opentwins-app.zip
+wget ... https://raw.githubusercontent.com/aleka07/openegiz/main/vendor/grafana-plugins/ertis-opentwins-app.zip
-wget ... https://github.com/ertis-research/grafana-panel-unity/releases/download/latest/ertis-unity-panel.zip
+wget ... https://raw.githubusercontent.com/aleka07/openegiz/main/vendor/grafana-plugins/ertis-unity-panel.zip
```

Also added `vendor/` to `.helmignore` — the zips are fetched over HTTP at pod
start and have no reason to be embedded in the packaged chart tarball.

**These URLs 404 until the orchestrator commits and pushes `vendor/` to `main`
on a public `aleka07/openegiz`.** Expected; noted so nobody debugs it as a
regression.

## 10. Validation

- SRI method verified against pristine upstream chunks — all 3 digests reproduce.
- Post-patch SRI self-check — all 3 chunks OK.
- Per-entry sha256 diff vs `upstream/` — only the intended entries differ.
- Byte-level diff of `202.js` / `396.js` / `module.js` — only the intended spans.
- Structural strings asserted present after patching: `opentwins.agents/name`,
  `opentwins.agents/twins`, `const Y="ertis-opentwins-app"`,
  `webpackChunkertis_opentwins_app`, `l.p="public/plugins/ertis-opentwins-app/"`.
- Zero `OpenTwins` left in any compiled chunk.
- `unzip -t` clean on both shipped zips.
- `python3 patch-branding.py --check` — both shipped archives match a fresh run
  (the patch is idempotent and reproducible).
- `helm template opentwins .` → exit 0, 4847 lines, no warnings; rendered init
  container shows both `raw.githubusercontent.com` URLs;
  `grep -c ertis-research` over the full render → **0**.

## 11. Remaining items

1. **Push `vendor/` to public `main`** before the next Grafana pod restart, or
   the init container fails and Grafana starts with no plugins.
2. **The rebrand is now cosmetically complete but structurally shallow.** Plugin
   ids, asset paths, proxy routes and k8s label keys still say `opentwins`, and
   they have to — see the table in the vendor README. A user who opens devtools
   or `kubectl get deploy --show-labels` still sees OpenTwins. Only a source-level
   fork of `ertis-research/grafana-app-opentwins` (Node ≥22, `create-plugin`
   build) could change that, and it would mean owning the plugin's maintenance.
   Not recommended before the winter school.
3. **Logo legibility at icon sizes.** The OpenEgiz logo is a ~4.2:1 wordmark.
   Even tightly cropped it is unreadable in the 24 px nav slot that
   `logos.small` feeds. A mark-only variant (the loop glyph without the
   "openegiz" text) for `logos.small`, keeping the full wordmark for
   `logos.large`, would be the proper use of those two fields. Needs a design
   decision, not a code one.
4. **The logo SVG uses `<text>` with `font-family: Inter`,** not outlined paths.
   Grafana ships Inter as its UI font so it renders correctly there, but the file
   is not self-contained. Converting the text to paths would make it robust
   anywhere.
5. **On the next upstream refresh:** drop the new zips into `upstream/`, re-run
   `patch-branding.py`, and expect it to abort if any anchored string moved. The
   webpack content hash in `6824e6a2fada2cf50285.svg` will also change — re-derive
   that filename from the new archive listing rather than assuming it.
