# OpenEgiz — Installation & Setup Log

Chronological log of every setup step for the Winter School environment.
Rule: record everything — failures with their error messages and fixes, successes with the exact commands. This file is the raw material for the course's "Session 0" (reproducible installation guide).

Target machine: **gx10-11** (ASUS Ascent GX10, aarch64 / Grace Blackwell, Ubuntu 24.04.4, 121 GB unified RAM, ~820 GB NVMe free). Access: `ssh gx10-11` (LAN, 192.168.0.135) or `ssh vpn-gx10-11` (10.66.66.24). Note: actual hostname reports as `gx10-7897`.

---

## 2026-08-07 — Day 0: repo transfer & recon

### Repo transfer ✅
- Cloned legacy `openegiz/openegiz` (main only; branches `codex/rebrand-openegiz`, `micola` left behind).
- Stripped git history, re-committed as a single initial commit → pushed to **https://github.com/aleka07/openegiz** (public, MIT preserved).
- Content: Helm chart (fork of ertis-research/opentwins) + data-generator + WebGL build, ~113 MB. No files >100 MB, push clean.

### Machine recon ✅
```
ARCH: aarch64          ← ARM64! Key constraint for all container images
SUDO: needs password   ← blocker, resolved via NOPASSWD sudoers drop-in (owner ran it)
NET:  outbound HTTPS OK (get.k3s.io reachable)
DOCKER: installed (29.2.1) but user gx10-11 not in docker group initially
K3S:  not installed; port 6443 free
```
All 18 GX10 machines were probed first — all idle (fresh reboot); gx10-11 chosen.

### Finding: ertis/ditto-extended-api is amd64-only ❌→plan
Docker Hub check: tags `latest`, `1.0.2`, `1.0.1`, `1.0.0` — **all amd64 only**. On aarch64 this pod would fail with exec format error. Likely a root cause of past "crooked" installs on GX10.
**Fix planned:** one-time rebuild from ertis-research sources for arm64 on gx10-11 itself, push to `ghcr.io/aleka07/ditto-extended-api` (multi-arch not needed for the course; arm64 is enough, but build multi-arch if cheap).

### Finding: Grafana plugins fetched at pod start (runtime dependency) ⚠️
`values.yaml` init container wget's `ertis-opentwins-app.zip` and `ertis-unity-panel.zip` from ertis-research GitHub releases **on every pod start**. If those releases disappear, installs break.
**Fix planned (rebrand-lite):** vendor the zips into aleka07/openegiz releases; patch visible plugin name/logo to OpenEgiz (plugins load unsigned, so zip-level patch of plugin.json + img/ is enough; internal plugin id stays `ertis-opentwins-app` — compiled JS references it).

### Full arm64 image audit
Delegated to executor agent → report: [arm64-audit.md](arm64-audit.md).

### Pending next
- [x] k3s + Helm install on gx10-11 — done, see below
- [x] arm64 fixes (extended-api rebuild, mongodb replacement) — done, see below
- [ ] Deploy chart (with arm64 fixes; pure "as-is" cannot work on this hardware)
- [ ] Rebrand-lite (see plan above)
- [ ] Close security hole before school: unauthenticated MongoDB on NodePort 30717 → switch `plainMongodb.service.type` to ClusterIP
- [ ] pm4py venv, JaamSim (Java 8 present; decide X11 vs headless)
- [ ] Hermes agent layer — last, after the stack is stable

---

## 2026-08-07 — ARM64 fixes (prerequisites for deploy)

Two of 21 images had no arm64 build (full audit: [arm64-audit.md](arm64-audit.md)). Pure "deploy as-is" is impossible on this hardware — both fixes below are ARM necessities, not rebranding.

### Fix 1: ditto-extended-api rebuilt natively for arm64 ✅
Upstream `ertis/ditto-extended-api` is amd64-only (all tags). Rebuilt from source `ertis-research/extended-api-for-eclipse-ditto` @ `b49663d` natively on gx10-11 → `openegiz/ditto-extended-api:arm64-b49663d`, smoke-tested, imported into k3s containerd. **Not pushed to any registry** — upstream has no license file, so the image stays local; reproducibility via [rebuild/extended-api/](../rebuild/extended-api/) (pinned Dockerfile + build.sh). Details & found upstream bug (Dockerfile.sample doesn't copy yarn.lock → non-reproducible builds; fixed with `--frozen-lockfile`): [notes-extended-api-build.md](notes-extended-api-build.md).

Chart pointed at the local image: `values.yaml` (`extendedAPI.image` → `openegiz/ditto-extended-api:arm64-b49663d`, `pullPolicy: IfNotPresent`) and `templates/extended-api/deploy.yaml` (hardcoded `imagePullPolicy: Always` made configurable — `Always` + local-only image = guaranteed ImagePullBackOff; also removed a duplicate `imagePullPolicy` key upstream left in the pod spec).

### Fix 2: bitnami MongoDB → plain StatefulSet on official mongo:6.0 ✅
`bitnamilegacy/mongodb:6.0.10` has no arm64 in any of its 2350 tags; swapping the image inside the bitnami chart is impossible (templates call `/opt/bitnami/scripts/*`). Replaced with a minimal StatefulSet + Service on official `mongo:6.0` (arm64 OK) gated by `plainMongodb.enabled`; bitnami subchart disabled. Service reuses the exact same name (`opentwins.mongodb.fullname` helper) → Ditto connection secret, extended API and hono wiring untouched. Validated via `helm lint` + `helm template` diff against baseline. Details: [notes-mongodb-arm64.md](notes-mongodb-arm64.md).

⚠️ Inherited security issue (pre-existing upstream, behavior preserved for now): unauthenticated MongoDB exposed on NodePort 30717. To be closed before the school starts.

---

## 2026-08-07 — k3s + Helm install

All commands run on gx10-11 over non-interactive SSH (`ssh -o BatchMode=yes gx10-11 '...'`).

### Versions installed
| Component | Version |
|---|---|
| k3s | `v1.36.3+k3s1` (build `5aed4d7b`, go1.26.5) |
| Kubernetes (server & kubectl client) | `v1.36.3+k3s1` |
| containerd (bundled by k3s) | `2.3.2-k3s2` |
| Helm | `v3.21.3` (`1ad6e68924fdf6fb0c7dcef8e9e1dfc0f36eaed6`, go1.26.5) |
| Traefik (k3s built-in chart) | `traefik-40.1.4+up40.1.0`, app `v3.7.1` |

### 0. Pre-flight
```bash
sudo -n true && uname -m && df -h / | tail -1
command -v k3s || echo "not installed"
```
Result: passwordless sudo works (the NOPASSWD drop-in from Day 0 is in place), `aarch64`,
`/dev/nvme0n1p2 916G 46G 824G 6% /`. k3s / kubectl / helm all absent — clean slate.

### 1. k3s install
```bash
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
```
Picked channel `stable` → `v1.36.3+k3s1`, downloaded `k3s-arm64` (arch auto-detected correctly),
installed to `/usr/local/bin/k3s`, created symlinks `kubectl` and `crictl`, systemd unit `k3s.service`
enabled + started. `--write-kubeconfig-mode 644` makes `/etc/rancher/k3s/k3s.yaml` readable without sudo.

One notable line from the installer output (not an error, worth knowing):
```
[INFO]  Skipping /usr/local/bin/ctr symlink to k3s, command exists in PATH at /usr/bin/ctr
```
i.e. `ctr` on PATH stays Docker's, **not** k3s's containerd. To talk to the k3s containerd use
`sudo k3s ctr ...` — plain `ctr` will point at the wrong socket. Docker itself was left untouched.

### 2. Readiness poll
Polled on the remote (local foreground `sleep` is restricted in this harness), 10 s interval:
```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
START=$(date +%s)
for i in $(seq 1 60); do
  NODE=$(kubectl get nodes --no-headers | awk '{print $2}')
  PENDING=$(kubectl get pods -A --no-headers | awk '$4!="Running" && $4!="Completed"' | wc -l)
  TOTAL=$(kubectl get pods -A --no-headers | wc -l)
  echo "[$(($(date +%s)-START))s] node=$NODE pods_total=$TOTAL not_ready=$PENDING"
  [ "$NODE" = Ready ] && [ "$TOTAL" -gt 0 ] && [ "$PENDING" -eq 0 ] && break
  sleep 10
done
```
Trace:
```
[2s]  node=Ready pods_total=3 not_ready=3
[12s] node=Ready pods_total=5 not_ready=5
[23s] node=Ready pods_total=5 not_ready=3
[33s] node=Ready pods_total=5 not_ready=2
[43s] node=Ready pods_total=7 not_ready=1
[54s] node=Ready pods_total=7 not_ready=0
ALL_READY after 54s
```
**Node reported `Ready` within ~2 s of the first poll; full kube-system convergence took 54 s.**

### 3. Helm install
```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```
Auto-detected arm64 → `helm-v3.21.3-linux-arm64.tar.gz`, checksum verified, installed to
`/usr/local/bin/helm` (used sudo internally, no prompt).

### 4. Persistent kubeconfig for the user
```bash
grep -q "KUBECONFIG=/etc/rancher/k3s/k3s.yaml" ~/.bashrc || \
  printf '\nexport KUBECONFIG=/etc/rancher/k3s/k3s.yaml\n' >> ~/.bashrc
```
Appended (was not present). Verified through an interactive shell:
`ssh gx10-11 'bash -ic "kubectl get nodes && helm ls -A --short"'` → works without any manual export.

⚠️ Caveat for future scripted runs: Ubuntu's default `~/.bashrc` returns early for non-interactive
shells, so a plain `ssh gx10-11 'kubectl ...'` will **not** pick this up. In scripts either keep
exporting `KUBECONFIG=/etc/rancher/k3s/k3s.yaml` explicitly, or use `ssh ... 'bash -ic "..."'`.

### 5. Final state
```
$ kubectl get nodes -o wide
NAME        STATUS   ROLES           AGE   VERSION        INTERNAL-IP     EXTERNAL-IP   OS-IMAGE             KERNEL-VERSION               CONTAINER-RUNTIME
gx10-7897   Ready    control-plane   82s   v1.36.3+k3s1   192.168.0.135   <none>        Ubuntu 24.04.4 LTS   6.17.0-1026-nvidia (arm64)   containerd://2.3.2-k3s2

$ kubectl get pods -A
NAMESPACE     NAME                                      READY   STATUS      RESTARTS      AGE
kube-system   coredns-54996dc9b4-vcv84                  1/1     Running     0             76s
kube-system   helm-install-traefik-crd-lhzs9            0/1     Completed   0             70s
kube-system   helm-install-traefik-qg4t7                0/1     Completed   2 (51s ago)   70s
kube-system   local-path-provisioner-58d557dc48-59hx9   1/1     Running     0             76s
kube-system   metrics-server-6dc596dfb8-xz9tz           1/1     Running     0             74s
kube-system   svclb-traefik-46aef70e-dht25              2/2     Running     0             38s
kube-system   traefik-59b7647586-cc2df                  1/1     Running     0             38s

$ helm ls -A
NAME         NAMESPACE    REVISION  STATUS    CHART                        APP VERSION
traefik      kube-system  1         deployed  traefik-40.1.4+up40.1.0      v3.7.1
traefik-crd  kube-system  1         deployed  traefik-crd-40.1.4+up40.1.0  v3.7.1
```

### Failures / anomalies
**No blocking failures. Nothing was retried, nothing needed a workaround.** Two things logged for honesty:

1. `helm-install-traefik-qg4t7` shows **`RESTARTS 2`** before reaching `Completed`. This is k3s's normal
   bootstrap race — the traefik install job starts before the traefik CRDs job has finished, fails,
   and is retried by the Job controller. Self-healing; final state `Completed` and both releases
   `deployed`. If a future install shows this job stuck in `CrashLoopBackOff` instead, that's the
   point where it stops being benign.
2. `ctr` symlink skipped in favour of Docker's (see §1). Not a failure, but a footgun for anyone
   later trying to `ctr images import` a locally built arm64 image into the cluster — must be
   `sudo k3s ctr images import`.

Scope note: only k3s and Helm were installed. Docker, kernel, and everything else untouched;
machine not rebooted; nothing committed to git.
