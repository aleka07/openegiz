# MongoDB on arm64: replacing the bitnami sub chart

Date: 2026-08-07
Target: single-node k3s, aarch64.

## Problem

The chart vendors bitnami `mongodb` 13.18.5 (`charts/mongodb/`) and pins
`bitnamilegacy/mongodb:6.0.10-debian-11-r8`, which has no arm64 build. Swapping only
the image inside the bitnami chart does not work either: its templates shell out to
`/opt/bitnami/scripts/*`, which only exists in bitnami images.

## Consumers of MongoDB found before changing anything

Everything resolves to the same host name, `<release>-mongodb` (`opentwins-mongodb`),
port `27017`:

| Consumer | Location | How it references MongoDB |
|---|---|---|
| Ditto connection secret | `templates/secrets/mongodb-connection.yaml:2,16-19` | `include "opentwins.mongodb.fullname"` substituted into the `#{PLACEHOLDER_MONGODB_HOSTNAME}#` placeholder |
| Name helper | `templates/_helpers.tpl:124-131` | `<release>-<mongodb.nameOverride>` |
| Ditto URI templates | `charts/ditto/values.yaml:166,170,174,178` | `mongodb://#{PLACEHOLDER_MONGODB_HOSTNAME}#:27017/ditto` |
| Ditto secret wiring | `values.yaml:121` | `ditto.dbconfig.uriSecret: ditto-mongodb-connection-secret` |
| Extended API | `templates/extended-api/deploy.yaml:31-32` | `MONGO_URI_POLICIES = mongodb://<opentwins.mongodb.fullname>/ditto` (no explicit port, defaults to 27017) |
| Hono device registry | `values.yaml:353-356` | `host: '{{ .Release.Name }}-mongodb'`, `port: 27017`, `dbName: hono`. Inert today, `hono.enabled: false` (`values.yaml:313`) |
| NodePort exposure | `values.yaml:396-398` (before the change) | bitnami service `type: NodePort`, `nodePorts.mongodb: 30717` |
| Chart dependency | `requirements.yaml:9-15` | `condition: mongodb.enabled` |

Not consumers: Grafana (no Mongo datasource, it reads InfluxDB), `examples/`,
`post-install/` scripts, `scripts/`. Hono's own vendored MongoDB
(`charts/hono/Chart.yaml:12`, `condition: mongodb.createInstance`) stays off,
`charts/hono/values.yaml:1425` defaults `createInstance: false`.

The bitnami service name was confirmed to be `<release>-mongodb`:
`charts/mongodb/templates/standalone/svc.yaml` names it via
`mongodb.service.nameOverride` → `mongodb.fullname` → `common.names.fullname`, which
with `nameOverride: mongodb` yields exactly that. A baseline `helm template` before the
change confirmed `Service/opentwins-mongodb`.

## What changed

1. `templates/mongodb-plain.yaml` (new) — a Service plus a 1-replica StatefulSet running
   the official `mongo:6.0` image (multi-arch, arm64 present), no auth, `--bind_ip_all`,
   `mongosh`-based readiness/liveness probes, `/data/db` backed by a
   `volumeClaimTemplates` PVC on the `local-path` storage class. Gated on
   `plainMongodb.enabled`.
2. `values.yaml:392` — `mongodb.enabled: true` → `false`. The rest of the `mongodb:`
   block is intentionally left alone, in particular `nameOverride: mongodb`, because the
   `opentwins.mongodb.fullname` helper reads it.
3. `values.yaml:421-433` — new `plainMongodb:` block (`enabled`, `image`,
   `imagePullPolicy`, `service.{type,port,nodePort}`, `persistence.{storageClass,size}`,
   `resources`), NodePort `30717` preserved from the bitnami config.
4. `templates/secrets/mongodb-connection.yaml:1` — gate widened from
   `and .Values.ditto.enabled .Values.mongodb.enabled` to
   `and .Values.ditto.enabled (or .Values.mongodb.enabled (.Values.plainMongodb).enabled)`,
   so the secret still renders with the bitnami chart disabled.

No other file touched. `docs/install-log.md` untouched.

## How URI compatibility is preserved

The new Service is named with the same `include "opentwins.mongodb.fullname" .` helper
that the secret and the extended API already use, and listens on port 27017. Nothing
downstream had to change: the rendered secret still carries
`mongodb://opentwins-mongodb:27017/ditto` for all four Ditto URIs, and the extended API
still gets `mongodb://opentwins-mongodb/ditto`. Hono's literal
`{{ .Release.Name }}-mongodb` resolves to the same name.

## Validation

`helm` v3.17.2 is installed locally, so validation ran on this Mac (no need for gx10-11).

- `helm lint .` — 0 failed (only the usual "icon is recommended" info).
- `helm template opentwins .` — renders without errors.
- Rendered diff versus baseline, resources removed / added:
  - removed: `ServiceAccount/opentwins-mongodb`, `ConfigMap/opentwins-mongodb-common-scripts`,
    `PersistentVolumeClaim/opentwins-mongodb`, `Deployment/opentwins-mongodb` — all four
    from `charts/mongodb/` (bitnami). No bitnami MongoDB resource renders anymore.
  - added: `StatefulSet/opentwins-mongodb`.
  - `Service/opentwins-mongodb` is present in both, unchanged in name — that is the
    compatibility guarantee, verified rather than assumed.
- Decoded secret after the change: all four URIs are
  `mongodb://opentwins-mongodb:27017/ditto`, host matches the Service name.
- Service renders as `NodePort`, port 27017, nodePort 30717, targetPort `mongodb`.
- StatefulSet renders with `image: mongo:6.0`, `args: ["--bind_ip_all"]`,
  `serviceName: opentwins-mongodb`, PVC template on `local-path`, 8Gi.

Not validated: an actual deploy on the cluster. Rendering is not running.

## Open risks

- **Pre-existing security issue, confirmed.** MongoDB runs with authentication disabled
  (the bitnami config had `auth.enabled: false`, the replacement matches it) and is
  published on NodePort 30717. That means an unauthenticated MongoDB reachable on the
  node IP from anywhere that can route to it. This is not introduced here, it is carried
  over verbatim, but it should be closed: either drop the Service to `ClusterIP`
  (`plainMongodb.service.type: ClusterIP` — nothing in the chart needs the NodePort,
  it is only convenient for external tooling) or enable auth and wire credentials into
  the URIs.
- **Data does not migrate.** The bitnami chart used a standalone PVC named
  `opentwins-mongodb`; the StatefulSet creates `data-opentwins-mongodb-0`. On an existing
  installation the old volume is orphaned rather than reused. Fine for a fresh install,
  needs a manual copy otherwise.
- **Do not enable both.** With `mongodb.enabled: true` and `plainMongodb.enabled: true`
  simultaneously, two Services would claim the name `opentwins-mongodb` and the install
  fails. There is no guard in the templates for this.
- `mongo:6.0` is the community image; it does not run as a fixed non-root UID the way the
  bitnami one did, and `volumePermissions` no longer applies. On k3s `local-path` this is
  not an issue, but on other storage backends the `/data/db` ownership may need a
  `securityContext`.
