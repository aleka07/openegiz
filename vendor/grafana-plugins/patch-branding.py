#!/usr/bin/env python3
"""Rebrand the vendored Grafana plugins from OpenTwins to OpenEgiz.

Reads the pristine upstream archives from ``upstream/`` and writes patched
archives next to them. Re-run this after refreshing ``upstream/`` from the
ertis-research releases.

    python3 patch-branding.py                 # patch in place (vendor/grafana-plugins)
    python3 patch-branding.py --check         # verify shipped zips match a fresh run

Only display-level strings and image assets are touched. Plugin ids, versions,
dependencies, routes, includes, webpack chunk globals, the plugin-proxy base
path and the ``opentwins.agents/*`` Kubernetes label keys are left alone: the
compiled bundles and the running platform depend on them.

Editing a lazy-loaded chunk requires updating the Subresource Integrity digest
that ``module.js`` pins for it, otherwise Grafana refuses to load the chunk and
the plugin renders blank. That recompute is handled here.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
LOGO_SRC = REPO_ROOT / "openegiz_logo_centered.svg"

APP_ZIP = "ertis-opentwins-app.zip"
UNITY_ZIP = "ertis-unity-panel.zip"

# openegiz_logo_centered.svg is a 1600x1600 canvas whose ink only spans
# (180,652)-(1422,948) -- ~85% empty margin, which renders as an invisible smudge
# in a Grafana icon slot. Tighten the viewBox to the measured bounds plus 20u of
# padding. Same artwork, nothing else changed.
LOGO_VIEWBOX_FROM = b'<svg width="1600" height="1600" viewBox="0 0 1600 1600"'
LOGO_VIEWBOX_TO = b'<svg width="1282" height="336" viewBox="160 632 1282 336"'


class PatchError(RuntimeError):
    pass


def sub_once(blob: bytes, old: bytes, new: bytes, where: str) -> bytes:
    """Replace exactly one occurrence, or fail loudly.

    An upstream refresh that reflows these strings must not silently no-op.
    """
    n = blob.count(old)
    if n != 1:
        raise PatchError(
            f"{where}: expected exactly 1 occurrence of {old!r}, found {n}. "
            "Upstream probably changed; re-derive the anchor."
        )
    return blob.replace(old, new, 1)


def build_logo() -> bytes:
    if not LOGO_SRC.exists():
        raise PatchError(f"logo not found: {LOGO_SRC}")
    svg = LOGO_SRC.read_bytes()
    return sub_once(svg, LOGO_VIEWBOX_FROM, LOGO_VIEWBOX_TO, LOGO_SRC.name)


# --------------------------------------------------------------------------
# per-archive patches
# --------------------------------------------------------------------------

def patch_app(entries: dict[str, bytes], logo: bytes) -> None:
    P = "ertis-opentwins-app/"

    # -- plugin.json: display name only. id/version/deps/routes/includes stay put,
    #    as do info.author (ERTIS) and info.links -- the plugin is Apache-2.0 ERTIS
    #    work and the attribution has to survive the rebrand.
    entries[P + "plugin.json"] = sub_once(
        entries[P + "plugin.json"],
        b'"name": "OpenTwins",',
        b'"name": "OpenEgiz",',
        "app plugin.json",
    )

    # -- logos. info.logos.small and .large both point at img/logo.svg.
    #    6824e6a2fada2cf50285.svg is the webpack-emitted copy of the same asset
    #    that 396.js renders as the in-app header logo; it is not referenced from
    #    plugin.json but it is the most visible logo in the whole plugin.
    entries[P + "img/logo.svg"] = logo
    entries[P + "6824e6a2fada2cf50285.svg"] = logo

    # -- README.md. Grafana renders this on the plugin details page.
    #    Upstream repo links and the "OpenTwins Official Documentation" link keep
    #    their text: they genuinely point at the upstream project, and relabelling
    #    them "OpenEgiz" would just make them wrong.
    readme = entries[P + "README.md"]
    # NB: this README uses CRLF line endings, the unity one uses LF -- keep
    # anchors inside a single line so both stay agnostic to that.
    readme = sub_once(
        readme,
        b"# OpenTwins App Plugin",
        b"# OpenEgiz App Plugin",
        "app README heading",
    )
    readme = sub_once(
        readme,
        b"The **OpenTwins App Plugin** serves as the central frontend interface "
        b"for the [OpenTwins](https://github.com/ertis-research/opentwins) platform.",
        b"The **OpenEgiz App Plugin** serves as the central frontend interface "
        b"for the OpenEgiz platform, built on "
        b"[OpenTwins](https://github.com/ertis-research/opentwins).",
        "app README intro",
    )
    readme = sub_once(
        readme,
        b"The base URL of the OpenTwins middleware",
        b"The base URL of the OpenEgiz middleware",
        "app README config section",
    )
    entries[P + "README.md"] = readme

    # -- compiled chunks: the 3 user-visible strings, nothing else.
    entries[P + "202.js"] = sub_once(
        entries[P + "202.js"],
        b"The OpenTwins plugin is active and ready to use.",
        b"The OpenEgiz plugin is active and ready to use.",
        "202.js config-page alert",
    )
    js396 = entries[P + "396.js"]
    js396 = sub_once(js396, b'alt:"OpenTwins Logo"', b'alt:"OpenEgiz Logo"',
                     "396.js header logo alt")
    js396 = sub_once(js396, b'n.appName},"OpenTwins")', b'n.appName},"OpenEgiz")',
                     "396.js header <h1>")
    entries[P + "396.js"] = js396

    # -- and now the reason this script exists.
    entries[P + "module.js"] = rewrite_sri(
        entries[P + "module.js"],
        {cid: entries[f"{P}{cid}.js"] for cid in (126, 202, 396)},
    )


def patch_unity(entries: dict[str, bytes], logo: bytes) -> None:
    # The Unity panel carries no OpenTwins branding: plugin.json name is "Unity",
    # description is "Unity WebGL render in Grafana panel", and its logo is the
    # Unity engine mark -- which is what makes the panel findable in Grafana's
    # panel picker, so it is deliberately NOT replaced with the OpenEgiz wordmark.
    del logo

    P = "ertis-unity-panel/"
    # Its single OpenTwins mention is a historical note pointing at the upstream
    # platform. Keep the link and the fact, name OpenEgiz as the thing being read.
    entries[P + "README.md"] = sub_once(
        entries[P + "README.md"],
        b"originally designed as an extension to "
        b"[OpenTwins](https://github.com/ertis-research/opentwins), "
        b"our digital twin platform,",
        b"originally designed as an extension to "
        b"[OpenTwins](https://github.com/ertis-research/opentwins), "
        b"the digital twin platform behind OpenEgiz,",
        "unity README",
    )


# --------------------------------------------------------------------------
# Subresource Integrity
# --------------------------------------------------------------------------

def sri(blob: bytes) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(blob).digest()).decode()


def rewrite_sri(module_js: bytes, chunks: dict[int, bytes]) -> bytes:
    """Point module.js's sriHashes at the (possibly patched) chunk bytes.

    module.js carries no digest of itself, so rewriting it in place is safe.
    """
    m = re.search(rb"sriHashes=\{(.*?)\}", module_js, re.S)
    if not m:
        raise PatchError("sriHashes block not found in module.js")

    out = module_js
    for cid, blob in sorted(chunks.items()):
        want = sri(blob).encode()
        pat = re.compile(rb"(\b%d:\")sha256-[A-Za-z0-9+/=]+(\")" % cid)
        if len(pat.findall(m.group(1))) != 1:
            raise PatchError(f"sriHashes: no unique entry for chunk {cid}")
        out, n = pat.subn(rb"\g<1>" + want + rb"\g<2>", out, count=1)
        if n != 1:
            raise PatchError(f"sriHashes: failed to rewrite chunk {cid}")
    return out


def verify_sri(entries: dict[str, bytes], prefix: str) -> list[str]:
    """Re-read module.js and confirm every pinned digest matches its chunk."""
    m = re.search(rb"sriHashes=\{(.*?)\}", entries[prefix + "module.js"], re.S)
    if not m:
        raise PatchError("sriHashes block not found")
    report = []
    for cid, digest in re.findall(rb"(\d+):\"(sha256-[A-Za-z0-9+/=]+)\"", m.group(1)):
        cid = int(cid)
        actual = sri(entries[f"{prefix}{cid}.js"])
        ok = actual == digest.decode()
        report.append(f"chunk {cid}: {'OK  ' if ok else 'FAIL'} {actual}")
        if not ok:
            raise PatchError(f"SRI mismatch for chunk {cid}")
    return report


# --------------------------------------------------------------------------
# zip plumbing
# --------------------------------------------------------------------------

def read_zip(path: Path) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        data = {i.filename: (b"" if i.is_dir() else z.read(i.filename)) for i in infos}
    return infos, data


def write_zip(path: Path, infos: list[zipfile.ZipInfo], data: dict[str, bytes]) -> None:
    """Rebuild the archive preserving entry order, names, timestamps and modes.

    Directory entries are kept so the layout unzipped by the init container is
    identical to upstream's.
    """
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i in infos:
            out = zipfile.ZipInfo(i.filename, date_time=i.date_time)
            out.external_attr = i.external_attr
            out.internal_attr = i.internal_attr
            out.create_system = i.create_system
            out.compress_type = zipfile.ZIP_STORED if i.is_dir() else zipfile.ZIP_DEFLATED
            z.writestr(out, data[i.filename])


PLUGINS = [
    (APP_ZIP, "ertis-opentwins-app/", patch_app),
    (UNITY_ZIP, "ertis-unity-panel/", patch_unity),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", type=Path, default=HERE / "upstream",
                    help="directory holding the pristine upstream zips")
    ap.add_argument("--out", type=Path, default=HERE,
                    help="directory to write the patched zips into")
    ap.add_argument("--check", action="store_true",
                    help="do not write; verify the existing zips match a fresh run")
    args = ap.parse_args()

    logo = build_logo()
    failures = 0

    for name, prefix, patch in PLUGINS:
        src = args.upstream / name
        if not src.exists():
            print(f"!! missing upstream archive: {src}", file=sys.stderr)
            return 2

        infos, data = read_zip(src)
        before = dict(data)
        patch(data, logo)

        changed = sorted(k for k in data if data[k] != before[k])
        print(f"\n=== {name}")
        print(f"  entries: {len(infos)}   changed: {len(changed)}")
        for k in changed:
            print(f"    ~ {k}")

        if prefix == "ertis-opentwins-app/":
            for line in verify_sri(data, prefix):
                print(f"    {line}")

        dst = args.out / name
        if args.check:
            tmp = dst.with_suffix(".zip.check")
            write_zip(tmp, infos, data)
            _, shipped = read_zip(dst)
            tmp.unlink()
            drift = sorted(k for k in data if shipped.get(k) != data[k])
            if drift or set(shipped) != set(data):
                failures += 1
                print(f"  !! DRIFT vs shipped zip: {drift or 'entry set differs'}")
            else:
                print("  shipped archive matches a fresh patch run")
        else:
            write_zip(dst, infos, data)
            print(f"  wrote {dst}")

    if failures:
        print(f"\n{failures} archive(s) drifted", file=sys.stderr)
        return 1
    print("\ndone")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
