# ARM64 (aarch64) compatibility audit — OpenEgiz Helm chart

**Date:** 2026-08-07
**Chart:** `OpenEgiz` 1.0.0 (fork of `ertis-research/opentwins`)
**Target host:** Ubuntu 24.04, aarch64, k3s (containerd)
**Method:** `helm template openegiz .` with stock `values.yaml` → every rendered `image:` extracted → each reference resolved against the registry manifest API (`registry-1.docker.io` / `quay.io`) with an anonymous pull token, accepting `manifest.list.v2+json` and `oci.image.index.v1+json`. Where the registry returned a single (non-index) manifest, the config blob was fetched and its `os`/`architecture` read directly. Docker Hub's `/v2/repositories/.../tags/...` endpoint was used as a cross-check for the two amd64-only images.

21 unique image references, 20 of them pulled during a normal `helm install` (one is `helm test`-only).

---

## Results

| Component | Image:tag | Enabled by default | Architectures | ARM64 OK? | Notes / Fix |
|---|---|---|---|---|---|
| Ditto — policies | `docker.io/eclipse/ditto-policies:3.3.7` | yes | linux/amd64, linux/arm64 | **YES** | Tag comes from ditto subchart `appVersion` |
| Ditto — things | `docker.io/eclipse/ditto-things:3.3.7` | yes | linux/amd64, linux/arm64 | **YES** | |
| Ditto — things-search | `docker.io/eclipse/ditto-things-search:3.3.7` | yes | linux/amd64, linux/arm64 | **YES** | |
| Ditto — connectivity | `docker.io/eclipse/ditto-connectivity:3.3.7` | yes | linux/amd64, linux/arm64 | **YES** | |
| Ditto — gateway | `docker.io/eclipse/ditto-gateway:3.3.7` | yes | linux/amd64, linux/arm64 | **YES** | |
| Ditto — nginx front | `docker.io/nginx:1.25` | yes | 386, amd64, arm/v5, arm/v7, **arm64/v8**, mips64le, ppc64le, s390x | **YES** | `ditto.nginx.service.type=NodePort:30525` |
| Ditto — nginx init (`wait-for-gateway`) | `rancher/curlimages-curl:7.73.0` | yes | amd64, arm/v7, **arm64**, s390x | **YES** | |
| Ditto — fixer (`cleanupStaleConnections`) | `alpine:latest` | yes | 386, amd64, arm/v6, arm/v7, **arm64/v8**, ppc64le, riscv64, s390x | **YES** | OpenEgiz-specific `templates/fixers/ditto-fixer.yaml`; floating `latest` tag |
| Ditto Extended API | `ertis/ditto-extended-api:latest` | yes | **linux/amd64 only** | **NO — BLOCKER** | All 4 published tags (`latest`, `1.0.2`, `1.0.1`, `1.0.0`) are amd64-only. See Blockers. |
| MongoDB (bitnami chart) | `docker.io/bitnamilegacy/mongodb:6.0.10-debian-11-r8` | yes | **linux/amd64 only** | **NO — BLOCKER** | Pinned in root `values.yaml` (overrides subchart default `bitnami/mongodb`). All 2350 tags of `bitnamilegacy/mongodb` scanned — **zero** have arm64. See Blockers. |
| MongoDB — `volumePermissions` init | `docker.io/bitnamilegacy/os-shell:11-debian-11-r72` | yes | amd64, **arm64** | **YES** | Pinned in root `values.yaml`; `volumePermissions.enabled: true` |
| Grafana | `docker.io/grafana/grafana:12.3.0` | yes | amd64, arm/v7, **arm64** | **YES** | Tag empty in values → chart `appVersion` 12.3.0 (chart 10.1.5) |
| Grafana — `initChownData` | `docker.io/library/busybox:1.31.1` | yes | 386, amd64, arm/v5, arm/v6, arm/v7, **arm64/v8**, mips64le, ppc64le, s390x | **YES** | Old (2019) but multi-arch |
| Grafana — `install-opentwins-plugins` init | `busybox` (→ `busybox:latest`) | yes | 386, amd64, arm/v5, arm/v6, arm/v7, **arm64/v8**, ppc64le, riscv64, s390x | **YES** | Defined in root `values.yaml` `grafana.extraInitContainers`; untagged → floating `latest` |
| Grafana — sidecars (datasources + plugins) | `quay.io/kiwigrid/k8s-sidecar:1.30.10` | yes | amd64, arm/v7, **arm64**, ppc64le, s390x | **YES** | Both `sidecar.datasources` and `sidecar.plugins` enabled |
| Mosquitto (+ its `setup-config` init) | `eclipse-mosquitto:2.0.14` | yes | 386, amd64, arm/v6, **arm64/v8**, ppc64le, s390x | **YES** | The chart's `busybox` init only renders with `configuration.ssl.enabled` (off) |
| Telegraf | `docker.io/library/telegraf:1.37-alpine` | yes | amd64, **arm64/v8** | **YES** | |
| InfluxDB 2 | `influxdb:2.7.4-alpine` | yes | amd64, **arm64/v8** | **YES** | |
| Unity WebGL server | `nginx:alpine` | yes | 386, amd64, arm/v6, arm/v7, **arm64/v8**, ppc64le, riscv64, s390x | **YES** | `unityWebglServer.enabled: true`, NodePort 30530 |
| Post-install jobs (ditto-default, mosquitto source/target connection) | `curlimages/curl:8.2.1` | yes | 386, amd64, **arm64**, ppc64le, s390x | **YES** | 3 Helm hook Jobs |
| Grafana test pod | `docker.io/bats/bats:v1.4.1` | test-only | 386, amd64, arm/v6, arm/v7, **arm64**, ppc64le, s390x | **YES** | Only pulled on `helm test` |
| Mosquitto test pod | `busybox` | test-only | see above | **YES** | Only pulled on `helm test` |

**Score: 19 of 21 images are arm64-ready. 2 are hard blockers.**

---

## Blockers

### 1. `ertis/ditto-extended-api:latest` — no arm64 build

Verified via Docker Hub tag listing:

| tag | last updated | architectures |
|---|---|---|
| `latest` | 2024-06-13 | amd64 |
| `1.0.2` | 2024-06-13 | amd64 |
| `1.0.1` | 2024-02-27 | amd64 |
| `1.0.0` | 2024-02-06 | amd64 |

On k3s/aarch64 the pull fails with `no match for platform in manifest: not found`.

**Recommended fix — rebuild locally on the ARM host.** The source is public: `github.com/ertis-research/extended-api-for-eclipse-ditto` (TypeScript/Node, last push 2026-05-04). It ships `Dockerfile.sample` + `env.sample`; the Node base images are multi-arch, so a native build on the aarch64 host needs no cross-compilation or QEMU.

```
git clone https://github.com/ertis-research/extended-api-for-eclipse-ditto
cd extended-api-for-eclipse-ditto
cp Dockerfile.sample Dockerfile          # review it first, adjust env if needed
docker build -t openegiz/ditto-extended-api:1.0.2-arm64 .
docker save openegiz/ditto-extended-api:1.0.2-arm64 | sudo k3s ctr images import -
```

then in your own values file:

```yaml
extendedAPI:
  image:
    repository: openegiz/ditto-extended-api
    tag: 1.0.2-arm64
```

Set `imagePullPolicy: IfNotPresent` (the deployment template doesn't expose it — either patch `templates/extended-api/deploy.yaml` or push to a registry the cluster can reach). A local registry or a multi-arch build pushed to your own Docker Hub namespace is the cleaner long-term option, since `k3s ctr images import` has to be repeated on every node.

**Fallback:** `extendedAPI.enabled: false`. The platform still runs, but the Grafana OpenTwins app plugin loses the extended REST endpoints it calls (aggregated thing/type queries), so parts of the UI will break. Not recommended as a permanent state.

### 2. `bitnamilegacy/mongodb:6.0.10-debian-11-r8` — no arm64 build, in any tag

Cross-checked two ways (registry manifest → single amd64 manifest; Hub API → `[('linux','amd64')]`). Full scan of the repository: **2350 tags, 0 with arm64.** The `bitnami/mongodb` repo is no better — of 442 tags, only `latest` has arm64 (that's the post-August-2025 "Bitnami Secure Images" policy, where the free tier keeps only `latest`), and that `latest` is MongoDB 8.x, which the vendored chart 13.18.5 was never written for.

Options, best first:

**(a) Replace the bitnami MongoDB dependency with a plain StatefulSet on `mongo:6.0.10`** (official image, `linux/amd64 + linux/arm64/v8` — verified). Ditto only needs a reachable MongoDB URI, and the chart already feeds it through `ditto-mongodb-connection-secret` (`templates/secrets/mongodb-connection.yaml`) with auth disabled. This drops ~2000 lines of bitnami chart you don't use and removes the frozen-image problem for good. Requires: `mongodb.enabled: false`, a new `templates/mongodb/` StatefulSet + headless Service named to match `opentwins.mongodb.fullname`, and keeping the NodePort 30717 mapping if you rely on it.

**(b) Rebuild the bitnami image for arm64** from `github.com/bitnami/containers` (`bitnami/mongodb/6.0/debian-11`). Keeps the chart untouched, but you inherit maintenance of a build that upstream has abandoned, and the 6.0/debian-11 branch may no longer build cleanly.

**(c) Swap in a different arm64-capable MongoDB chart** — e.g. the `mongodb/mongodb-community-server:6.0-ubi8` image (verified `linux/amd64 + linux/arm64/v8`) via the MongoDB Community Operator. Most work, most future-proof.

**Not viable:** pointing `mongodb.image.repository` at `mongo` or `mongodb/mongodb-community-server` while keeping the bitnami chart. The bitnami templates call `/opt/bitnami/scripts/mongodb/entrypoint.sh`, `/bitnami/scripts/ping-mongodb.sh`, `/bitnami/scripts/readiness-probe.sh` and run as uid 1001 against `/bitnami/mongodb` — none of that exists in non-bitnami images.

---

## Warnings

- **`bitnamilegacy/*` is a frozen archive.** After Bitnami's August 2025 change, the old versioned tags were moved to the `bitnamilegacy` namespace and receive no further updates — no CVE patches, ever. Both `bitnamilegacy/mongodb` and `bitnamilegacy/os-shell` are pinned in the root `values.yaml`. Even after the arm64 problem is solved, treat these as technical debt.
- **MongoDB runs with `auth.enabled: false` and a NodePort (30717).** Unauthenticated Mongo exposed on a node port. Fine on an isolated lab host, not fine anywhere reachable.
- **Floating tags.** `ertis/ditto-extended-api:latest`, `alpine:latest`, `nginx:alpine`, and the untagged `busybox` in `grafana.extraInitContainers` all resolve to whatever is current at pull time. Reproducibility on the ARM host suffers; pin them once the build works.
- **`grafana/grafana:12.3.0` against chart 10.1.5** — arm64 is fine, but note the image tag is inherited from the subchart's `appVersion`, so bumping the subchart silently changes the Grafana major version.
- **`busybox:1.31.1` (grafana initChownData)** is from 2019. arm64 present, so not a blocker, but it is ancient.
- **InfluxDB 2.7.4-alpine and telegraf 1.37-alpine publish arm64 as `arm64/v8` / `arm64` only** — no 32-bit arm fallback. Irrelevant here (target is aarch64), noted for completeness.
- **`alpine:latest` in `ditto-fixer` runs a shell loop against the Ditto devops API with hardcoded credentials** (`devops:foobar` from `values.yaml`). Arch-clean, but review it separately.

---

## Grafana plugin artifacts (init container, `values.yaml` lines 296–305)

Both `wget` URLs in the `install-opentwins-plugins` init container were verified live on 2026-08-07:

| Artifact | URL | HTTP | Size | Arch-dependent? |
|---|---|---|---|---|
| `ertis-opentwins-app.zip` | `github.com/ertis-research/opentwins-in-grafana/releases/download/latest/…` | 301 → 302 → **200** | 477 059 B | **No** |
| `ertis-unity-panel.zip` | `github.com/ertis-research/grafana-panel-unity/releases/download/latest/…` | 302 → **200** | 129 659 B | **No** |

The first URL now redirects: `ertis-research/opentwins-in-grafana` → `ertis-research/grafana-app-opentwins`. GitHub still serves it, so nothing breaks today, but the repo was renamed and the values file should eventually point at the new name.

Contents were listed and discarded. Both archives contain only `module.js` + webpack chunks, source maps, `plugin.json`, images and docs — **no `gpx_*` Go backend binaries**, which is what would have made a Grafana plugin architecture-specific. These are pure frontend plugins: they execute in the browser, not in the Grafana container. The Unity panel is the same story — it loads the WebGL build (`build/WebGL Build.wasm` etc., served by the `nginx:alpine` pod) into the user's browser, so the WASM/JS runs client-side and the server architecture is irrelevant.

Note the init container itself runs `busybox` (arm64 fine) and uses busybox's built-in `unzip` — no extra dependency.

---

## Disabled by default (not audited in depth)

`requirements.yaml` has no `tags:` gating in `values.yaml`, so the `condition:` flags decide. These render nothing:

| Component | Flag | Images it would pull |
|---|---|---|
| Eclipse Hono | `hono.enabled: false` | `eclipse/hono-adapter-{amqp,coap,http,lora,mqtt}`, `eclipse/hono-service-auth`, `eclipse/hono-service-device-registry-{mongodb,jdbc}`, `eclipse/hono-service-command-router-infinispan` (all @ 2.6.0), plus `bitnamilegacy/{mongodb,kafka,jmx-exporter,kubectl,os-shell}`, `quay.io/interconnectedcloud/qdrouterd:1.17.1`, `quay.io/artemiscloud/activemq-artemis-broker:1.0.32`, `infinispan/server-native:13.0` |
| Kafka / Strimzi operator | `kafka.enabled: false`, `strimzi-kafka-operator.enabled: false` | marked "DO NOT USE, IN DEVELOPMENT" in values |
| Kafka-ML | `kafkaml.enabled: false` | `ertis/kafka-ml-*:master` (backend, frontend, executors, tensorflow/pytorch training+inference) — same publisher as the amd64-only extended API, so assume amd64-only until proven otherwise |
| Example twin (raspberry) | `example.enabled: false` | `curlimages/curl:8.2.1` (already arm64-clean) |
| Ditto SwaggerUI / Ditto UI | `ditto.swaggerui.enabled: false`, `ditto.dittoui.enabled: false` | `swaggerapi/swagger-ui:v4.19.1`, `eclipse/ditto-ui:3.3.7` |
| Ditto's own bundled MongoDB | `ditto.mongodb.enabled: false` | bitnami mongodb (same blocker as above) |
| MongoDB metrics exporter | subchart default off | `bitnami/mongodb-exporter` |

**If Hono is ever enabled on this host, re-run this audit** — it pulls four more `bitnamilegacy/*` images (including `bitnamilegacy/mongodb` again) and three quay.io/other images that were not checked here.

---

## Reproducing this audit

```bash
helm template openegiz . | grep -E '^\s+(- )?image:' | sed 's/^[[:space:]]*//' | sort -u
```

then, per image:

```bash
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:${REPO}:pull" | jq -r .token)
curl -s -H "Authorization: Bearer $TOKEN" \
     -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
     -H "Accept: application/vnd.oci.image.index.v1+json" \
     "https://registry-1.docker.io/v2/${REPO}/manifests/${TAG}" | jq '.manifests[].platform'
```

If the response has no `.manifests` array it is a single-platform image — fetch `.config.digest` from the blob endpoint and read `.architecture` there. That is exactly how the two blockers were confirmed.
