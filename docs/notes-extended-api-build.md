# Build log — Ditto Extended API (arm64)

**Date:** 2026-08-07
**Host:** gx10-11 — Ubuntu 24.04, aarch64, kernel 6.17.0-1026-nvidia, Docker 29.2.1
**Build type:** native arm64 (no QEMU emulation)

## Source

| | |
|---|---|
| Repo | `https://github.com/ertis-research/extended-api-for-eclipse-ditto.git` |
| Commit | `b49663dea326854a2323423eaeab7e7f54d325a7` |
| Short SHA | `b49663d` |
| Commit date / subject | 2026-05-04 — `chore: add .env.example file` |
| Checkout path | `~/openegiz-build/extended-api` on gx10-11 |

**Licensing:** the upstream repo ships no LICENSE file. The image is therefore
kept strictly local — it was **not** pushed to Docker Hub or any other registry,
and must not be. Distribution happens only via the local `docker save` tarball
and the k3s containerd import.

## Result

| | |
|---|---|
| Tags | `openegiz/ditto-extended-api:arm64-b49663d`, `openegiz/ditto-extended-api:latest` |
| Image ID | `sha256:71491d769751babed1fb7c7214f014d8c1bca325c879dc401cd219c1421526e8` |
| Architecture | `arm64/linux` |
| Uncompressed size | 528 MB (527 580 095 bytes) |
| Exported tarball | `~/openegiz-build/ditto-extended-api-arm64.tar.gz` — 142 MB (148 775 388 bytes) |
| k3s content digest | `sha256:89fc4bd3c98f6ac6758fddc85ebb488ad267877bf170adf888948649aaeb7cc5` |

The image is fat (528 MB) because `node:20-slim` + full dev dependencies are
kept: the app is started with `ts-node -r dotenv/config src/app.ts`, i.e. it is
never compiled to JS, so `typescript`, `ts-node` and `dotenv` must all be
present at runtime. Slimming would require changing the upstream start script —
out of scope here.

## Commands

```bash
# clone at pinned commit
mkdir -p ~/openegiz-build && cd ~/openegiz-build
git clone https://github.com/ertis-research/extended-api-for-eclipse-ditto.git extended-api
cd extended-api && git checkout b49663dea326854a2323423eaeab7e7f54d325a7

# Dockerfile (Dockerfile.sample + the lockfile fix described below)
cp Dockerfile.sample Dockerfile
# ...apply the two-line edit...

# build
docker build -t openegiz/ditto-extended-api:arm64-b49663d \
             -t openegiz/ditto-extended-api:latest .

# export
cd ~/openegiz-build
docker save openegiz/ditto-extended-api:latest openegiz/ditto-extended-api:arm64-b49663d \
  | gzip > ditto-extended-api-arm64.tar.gz

# import into k3s
gunzip -c ditto-extended-api-arm64.tar.gz | sudo k3s ctr images import -
```

Reproducible equivalents live in `rebuild/extended-api/` (`Dockerfile` +
`build.sh`). `build.sh` runs the whole sequence end to end on gx10-11.

## Failures and fixes

**No build failures.** `yarn install` resolved and linked cleanly on aarch64 on
the first attempt — no node-gyp compilation, no network problems, no missing
prebuilt binaries. The dependency set is pure JS.

One real problem was found and fixed anyway:

- **Problem:** upstream `Dockerfile.sample` has `COPY package*.json ./`, which
  does not include `yarn.lock`. The build logs confirmed it —
  `info No lockfile found` — meaning yarn re-resolved every semver range from
  scratch. `package.json` uses `^` ranges throughout, so two builds a week apart
  can produce different dependency trees from the same commit. That defeats the
  point of pinning the commit.
- **Fix** (two lines, inside the build dir only):
  ```diff
  -COPY package*.json ./
  -RUN yarn install
  +COPY package*.json yarn.lock ./
  +RUN yarn install --frozen-lockfile
  ```
- **Verification:** rebuilt with the fix. `yarn install` completed in 12.7 s
  (vs 40.7 s for the resolve-from-scratch run) and printed no "No lockfile"
  notice. The recorded image ID above is from this second, pinned build.

Two non-blocking BuildKit warnings remain, both inherited from upstream:
`SecretsUsedInArgOrEnv` for `ENV DITTO_PASSWORD_API` and
`ENV DITTO_PASSWORD_DEVOPS`. They are empty placeholders in the image, so no
secret is actually baked in — but real credentials must be injected at runtime
(k8s Secret / env), never by editing these lines.

## Smoke test — PASSED

1. **Architecture:** `docker image inspect` reports `arm64/linux`. Native, not
   emulated.
2. **Node runs:** `docker run --rm --entrypoint node ... --version` →
   `v20.20.2`. No exec-format error.
3. **App launches:**
   ```
   yarn run v1.22.22
   $ ts-node -r dotenv/config src/app.ts
   Trying to connect to mongodb://IP_MONGODB:PORT_MONGODB/policies
   MongoDB URI detected. GET all policies will be enabled
   Extended API for Eclipse Ditto listening
   MongoRuntimeError: Unable to parse IP_MONGODB:PORT_MONGODB with URL
   ```
   The `MongoRuntimeError` is **expected and acceptable**: the image ships the
   literal `IP_MONGODB:PORT_MONGODB` placeholder from upstream, so the URI is
   not even syntactically valid. Crucially the error is non-fatal — the process
   printed "listening" and stayed up.
4. **HTTP serving:** `curl http://localhost:18080/` → **404**. That is the
   right answer: there is no route at `/`, and getting a 404 rather than a
   connection refusal proves express is bound and handling requests.
5. **Process stability:** after 12 s the container was still
   `running`, exit code 0. No crash-on-start.

## k3s import — DONE

k3s was already up when the build finished (`k3s ctr` reported
`v2.3.2-k3s2`, go1.26.5), so the import ran rather than being deferred.

```
$ sudo k3s ctr images ls -q | grep extended-api
docker.io/openegiz/ditto-extended-api:arm64-b49663d
docker.io/openegiz/ditto-extended-api:latest
```

Both tags resolve to content digest
`sha256:89fc4bd3c98f6ac6758fddc85ebb488ad267877bf170adf888948649aaeb7cc5`,
529.8 MB in the containerd store.

**Deployment requirement:** because the image lives only in the local
containerd store and exists in no registry, any Pod referencing it **must** set
`imagePullPolicy: IfNotPresent` (or `Never`). The default policy for a
`:latest` tag is `Always`, which would try to pull from Docker Hub and fail with
a 404 / ImagePullBackOff. Prefer referencing the immutable
`arm64-b49663d` tag over `latest`.

**Single-node caveat:** the import touched gx10-11's containerd only. If the
cluster ever gains a second node, the tarball must be imported there too, or
the Pod must be pinned to gx10-11.

## Runtime configuration reference

Env vars the app reads (from `env.sample`), all currently placeholders in the
image and needing real values at deploy time:

| Var | Purpose |
|---|---|
| `HOST` | **not** a bind address — only used to render the Swagger `servers` URL |
| `PORT` | listen port; image defaults to `8080` |
| `MONGO_URI_POLICIES` | MongoDB for the policies collection |
| `DITTO_URI_THINGS` | base URL of the Ditto gateway |
| `DITTO_USERNAME_API` / `DITTO_PASSWORD_API` | Ditto API credentials |
| `DITTO_USERNAME_DEVOPS` / `DITTO_PASSWORD_DEVOPS` | Ditto devops credentials |
| `ALL_LOGS` | verbose logging toggle |

The `HOST=localhost` default looks alarming but is harmless. Checked
`src/app.ts`: the server is started with `app.listen(app.get("port"), ...)` —
no host argument — so Node binds `0.0.0.0` and the Service will reach it.
`HOST` is read in exactly one place, line 15, to build the
`http://${HOST}:${PORT}` string advertised in the Swagger UI. Set it to the
externally reachable hostname if the Swagger "try it out" button should work;
otherwise it affects nothing.
