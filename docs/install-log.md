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
- [x] Deploy chart (with arm64 fixes) — done, 14/14 Running, see "First deploy on k3s" below
- [x] Rebrand-lite part 1: Grafana plugins vendored + rebranded — see "Rebrand-lite: Grafana plugins" below
- [ ] Rebrand-lite part 2: Grafana login/nav logo + app title, config renames (topics/org/tenant opentwins→openegiz)
- [ ] Logo: mark-only (square) variant for the 24px nav slot — current wordmark is unreadable that small
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

---

## 2026-08-07 — First deploy on k3s

First end-to-end install of the OpenEgiz Helm chart onto the k3s cluster built earlier today.
**Result: 14/14 pods Running, `helm status` = `deployed`, all smoke checks green.**
One real blocker was hit and fixed (a JVM/cgroup interaction that killed every Ditto service);
it is written up in full below because it will bite anyone reinstalling on this class of machine.

Release name `opentwins`, namespace `opentwins`. The name is load-bearing — several values
reference resources derived from it (e.g. the configmap `opentwins-telegraf-real-config`), so
renaming is a separate rebrand task, not something to do casually.

### 1. Transfer the chart to the host

```bash
ssh gx10-11 'mkdir -p ~/openegiz-deploy/chart'
rsync -a --delete --exclude .git \
  "/Users/aleka/Projects/fall 2026/openegiz/" gx10-11:~/openegiz-deploy/chart/
```
114 MB transferred. The `mkdir` is needed first — rsync will not create a missing grandparent
directory and fails with `mkdir ... failed: No such file or directory (2)`.

Subcharts are vendored under `charts/`, so **`helm dependency build` was never run** and no
upstream repo was contacted. Render check passed straight away:

```bash
ssh gx10-11 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
  cd ~/openegiz-deploy/chart && helm template opentwins . -n opentwins > /tmp/rendered.yaml'
# exit 0, 4847 lines, no stderr
```

### 2. First install attempt — FAILED

```bash
ssh gx10-11 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
  cd ~/openegiz-deploy/chart && helm install opentwins . -n opentwins --create-namespace --timeout 20m'
```

```
Error: INSTALLATION FAILED: failed post-install: 1 error occurred:
	* timed out waiting for the condition
real	20m1.112s
```

Everything except Ditto came up fine. All five Ditto JVM services crash-looped:

```
opentwins-ditto-connectivity-86cbf96cdc-qtnd8   0/1  CrashLoopBackOff  6
opentwins-ditto-gateway-649459c9bf-t945g        0/1  CrashLoopBackOff  6
opentwins-ditto-policies-5b4d65f477-xr5hn       0/1  CrashLoopBackOff  6
opentwins-ditto-things-6d478759b9-7knrg         0/1  CrashLoopBackOff  6
opentwins-ditto-thingssearch-ff45768d4-stz5c    0/1  CrashLoopBackOff  6
opentwins-ditto-nginx-7dd6dc6dd7-zsjm9          0/1  Init:0/1          0
```

`ditto-nginx` sat in `Init:0/1` because its init container waits for the gateway. The helm
failure itself came from the `post-install-ditto-default` hook, which polls Ditto for readiness
and gives up:

```
INFO: Waiting for Ditto... (Attempt 30/30)
FATAL: Timeout waiting for Ditto to become UP. Exiting.
```

So the hook was a **symptom**, not the cause. The cause was in the Ditto pods.

### 3. Diagnosing the Ditto crash loop

The container logs ended abruptly with no Java exception — the last line every time was:

```
"message":"SBR will be automatically enabled after <PT1H>","logger_name":"org.eclipse.ditto.base.service.cluster.DittoSplitBrainResolver"
```

Clean logs that just stop mean the process was killed rather than that it failed. `kubectl describe`
confirmed it:

```
    Last State:     Terminated
      Reason:       OOMKilled
      Exit Code:    137
      Started:      Fri, 07 Aug 2026 13:27:44 +0500
      Finished:     Fri, 07 Aug 2026 13:27:45 +0500
    Limits:
      memory:  1Gi
```

**Killed one second after start.** All five services, identically.

#### First hypothesis (wrong): the heap just doesn't fit in 1 GiB

The chart sets `resources.memoryMi: 1024` as both request and limit, and passes
`-XX:MaxRAMPercentage=60 -XX:InitialRAMPercentage=60` plus `-XX:MaxMetaspaceSize=256m`.
That is ~614 MiB heap + 256 MiB metaspace = ~870 MiB before overhead, which looked tight
enough to explain it. I raised the limit to 2 GiB on all five deployments:

```bash
for c in things thingssearch policies connectivity gateway; do
  kubectl set resources deploy/opentwins-ditto-$c -n opentwins --limits=memory=2Gi --requests=memory=2Gi
done
```

**Still OOMKilled at 2 GiB.** A limit that doubles with no effect means the JVM is not sizing
itself from the limit at all, so the arithmetic above was never the real story.

#### Actual root cause: the JVM ignores the cgroup v2 memory limit on this host

Probed the real image directly (manifest at `/tmp/jvmprobe.yaml` on the host, container capped
at 2 GiB):

```
=== cgroup ===
2147483648            <- /sys/fs/cgroup/memory.max, correct, 2 GiB
=== cgroup mount ===
... /sys/fs/cgroup ro,... - cgroup2 cgroup rw,nsdelegate,memory_recursiveprot
=== java version ===
openjdk version "17.0.8.1" 2023-08-24 (Temurin-17.0.8.1+1)
=== ergonomics ===
   size_t InitialHeapSize  = 78383153152     {ergonomic}
   size_t MaxHeapSize      = 78383153152     {ergonomic}
 uint64_t MaxRAM           = 130596184064    {ergonomic}
     bool UseContainerSupport = true         {command line}
```

The kernel exposes the limit correctly (`memory.max` = 2147483648, `/proc/self/cgroup` = `0::/`,
cgroup v2, and k3s containerd runs `SystemdCgroup = true`). But the JDK reports
**`MaxRAM = 130596184064`** — the full 121 GiB of *host* RAM — despite `UseContainerSupport=true`.
It then applies `MaxRAMPercentage=60` to that and decides on a **73 GiB heap**, and because
`InitialRAMPercentage=60` commits the heap up front, the JVM tries to allocate 73 GiB
immediately and the kernel kills the container about a second in.

This is why raising the k8s limit changed nothing: the JVM never looked at the limit.

JDK 17.0.8.1 (aarch64, the JDK baked into `eclipse/ditto:3.3.7`) is the version that matters here
— container-limit detection is failing on this kernel (6.17.0-1026-nvidia). I did not chase the
exact JDK bug ID; the behaviour is reproducible and the workaround is solid.

#### Fix: give the JVM an explicit `-XX:MaxRAM`

`-XX:MaxRAM` sets the base the `*RAMPercentage` flags compute against, so the chart's existing
percentage tuning starts behaving as intended. Verified with the same probe before touching the
chart:

```
 uint64_t MaxRAM      = 2147483648    {command line}
   size_t MaxHeapSize = 1289748480    {ergonomic}     <- 1.23 GiB, i.e. 60% of 2 GiB
```

`MaxHeapSize` went from 78383153152 to 1289748480. That is the fix.

### 4. Chart edits (local repo is the source of truth)

Both edits are in **`values.yaml`** only, under the `ditto:` block. No subchart files were
touched, so `charts/ditto/` stays a clean vendored copy. Each edit carries a comment in the file
explaining the reasoning.

1. **`ditto.global.jvmOptions`** — restated the upstream default with `-XX:MaxRAM=2147483648`
   added. It is a scalar, so overriding it means repeating the whole string; everything else is
   verbatim from `charts/ditto/values.yaml`. This one setting covers all five JVM services,
   because the subchart templates interpolate `global.jvmOptions` into `JAVA_TOOL_OPTIONS` for
   each of them.

2. **`resources.memoryMi: 2048`** on `things`, `thingsSearch`, `policies`, `connectivity`,
   `gateway` (upstream default is 1024). Paired with the `MaxRAM` value above.

> **Two traps worth remembering.**
>
> *The keys are inconsistently cased.* Four services use lowercase (`things`, `policies`,
> `connectivity`, `gateway`) but thingssearch is **`thingsSearch`**. My first edit used
> `thingssearch:` and Helm silently ignored it — no warning, no error, values that match no
> subchart key are just dropped. Caught it by diffing rendered memory limits per deployment.
> Always verify with `helm template | grep`, never assume an override landed.
>
> *`MaxRAM` and `memoryMi` are coupled.* `MaxRAM` is a hardcoded byte count that must match the
> container limit. Change one without the other and the JVM sizes its heap against a limit the
> container does not have — which is exactly the failure mode above. Both are commented in
> `values.yaml` to say so.

### 5. Clean-slate reinstall

The failed release could not be upgraded in place (revision 1 never reached `deployed`), so it was
torn down completely. Helm leaves two categories of resource behind, and both had to go:

```bash
helm uninstall opentwins -n opentwins
#   -> "These resources were kept due to the resource policy: [PersistentVolumeClaim] opentwins-influxdb2"
kubectl delete pvc --all -n opentwins        # incl. the influxdb2 PVC helm deliberately keeps
kubectl delete job --all -n opentwins        # post-install hook job survives uninstall
kubectl delete pod --all -n opentwins --force --grace-period=0
```

Deleting the PVCs was a deliberate part of the clean slate: InfluxDB had already run its
one-time admin/bucket/token bootstrap against that volume, and reinstalling on top of an
initialised volume is a known source of confusing second-run failures. Nothing of value was lost
— Ditto never started, so MongoDB held no twin data.

Then re-synced the corrected chart and reinstalled:

```bash
rsync -a --delete --exclude .git "/Users/aleka/Projects/fall 2026/openegiz/" gx10-11:~/openegiz-deploy/chart/
ssh gx10-11 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
  cd ~/openegiz-deploy/chart && helm install opentwins . -n opentwins --create-namespace --timeout 20m'
```

```
NAME: opentwins
STATUS: deployed
REVISION: 1
real	0m57.161s
```

### 6. Convergence timeline

| t | state |
|---|---|
| 0 s | `helm install` starts |
| ~25 s | all 5 Ditto JVM services `Running` but `0/1`; nginx still `Init:0/1` |
| ~50 s | **all 5 Ditto services `1/1 Ready`**, nginx `1/1`, Akka cluster formed |
| 57 s | post-install hook passes, helm returns `deployed`, hook job auto-deleted |
| 50–350 s | monitored for stability — **zero restarts** across all Ditto pods |

Ditto converged in **under a minute**, not the 5–15 minutes expected. Worth flagging as a
pleasant surprise rather than a reason for suspicion: health checks below confirm it is genuinely
up. The 20-CPU / 121 GiB host is doing a lot of the work here.

### 7. Final state

```
$ kubectl get pods -n opentwins
NAME                                            READY   STATUS    RESTARTS        AGE
opentwins-ditto-connectivity-6657f8cc8-rksrp    1/1     Running   0               8m37s
opentwins-ditto-extended-api-779f9b9bcf-24f9c   1/1     Running   0               8m36s
opentwins-ditto-fixer-5df89755ff-sqdc5          1/1     Running   0               8m37s
opentwins-ditto-gateway-779c8fb776-fl7pr        1/1     Running   0               8m36s
opentwins-ditto-nginx-6c8fd5d4db-g6h2k          1/1     Running   0               8m36s
opentwins-ditto-policies-d78f7f79d-cbdfx        1/1     Running   0               8m37s
opentwins-ditto-things-6cbbd58b94-xkcd6         1/1     Running   0               8m37s
opentwins-ditto-thingssearch-5fcc86bdbc-z2sgm   1/1     Running   0               8m37s
opentwins-grafana-55f4d66c6b-tg45n              3/3     Running   0               8m36s
opentwins-influxdb2-0                           1/1     Running   0               8m36s
opentwins-mongodb-0                             1/1     Running   0               8m36s
opentwins-mosquitto-b9b6bb8c6-qbj9m             1/1     Running   0               8m37s
opentwins-telegraf-667f549ffb-vb9tf             1/1     Running   2 (8m34s ago)   8m37s
opentwins-unity-webgl-server-557d5c6749-5tzqx   1/1     Running   0               8m37s

$ kubectl get svc -n opentwins
NAME                           TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)                         AGE
opentwins-ditto-extended-api   NodePort    10.43.141.165   <none>        8080:30528/TCP                  8m37s
opentwins-ditto-gateway        ClusterIP   10.43.58.164    <none>        8080/TCP                        8m37s
opentwins-ditto-nginx          NodePort    10.43.68.111    <none>        8080:30525/TCP                  8m37s
opentwins-grafana              NodePort    10.43.20.91     <none>        80:30718/TCP                    8m37s
opentwins-influxdb2            NodePort    10.43.129.173   <none>        80:30716/TCP                    8m37s
opentwins-mongodb              NodePort    10.43.49.185    <none>        27017:30717/TCP                 8m37s
opentwins-mosquitto            NodePort    10.43.83.200    <none>        1883:30511/TCP,9001:31039/TCP   8m37s
opentwins-unity-webgl-server   NodePort    10.43.246.197   <none>        80:30530/TCP                    8m37s
```

**Access map** (host is `192.168.0.135` on LAN, `10.66.66.24` over VPN):

| Service | NodePort | Credentials |
|---|---|---|
| Ditto API (nginx) | 30525 | `ditto:ditto`, devops `devops:foobar` |
| Ditto extended API | 30528 | none |
| Grafana | 30718 | `admin:admin` |
| InfluxDB 2 | 30716 | `admin` / `password`, org `opentwins`, bucket `default` |
| MongoDB | 30717 | auth disabled |
| Mosquitto MQTT | 30511 (+31039 ws) | auth disabled |
| Unity WebGL server | 30530 | none |

All credentials are the chart defaults and are fine for a LAN workshop box, but **none of this
should be exposed beyond the LAN as-is** — every service is unauthenticated or uses a published
default password, and the InfluxDB admin token is committed in `values.yaml`.

### 8. Smoke checks — all green

```bash
# Ditto REST API
$ curl -s -u ditto:ditto http://localhost:30525/api/2/things
[]                                             # HTTP 200, empty array as expected

# Ditto aggregate health
$ curl -s -u devops:foobar http://localhost:30525/status/health
top: UP
  expected-roles UP    search UP    gateway UP
  things UP            connectivity UP    policies UP

# Grafana
$ curl -sI http://localhost:30718/login
HTTP/1.1 200 OK

# both ertis plugins downloaded by the init container (needs outbound internet)
$ kubectl exec -n opentwins deploy/opentwins-grafana -c grafana -- ls -1 /var/lib/grafana/plugins
ertis-opentwins-app
ertis-unity-panel
grafana-exploretraces-app  grafana-lokiexplore-app
grafana-metricsdrilldown-app  grafana-pyroscope-app

# Grafana datasource auto-provisioned by the sidecar
$ curl -s -u admin:admin http://localhost:30718/api/datasources
  opentwins   influxdb   http://opentwins-influxdb2:80

# extended API — responds; 404 on an unrouted path is the expected behaviour
$ curl -s -o /dev/null -w '%{http_code}' http://localhost:30528/     -> 404

# InfluxDB
$ curl -s http://localhost:30716/health
{"name":"influxdb","message":"ready for queries and writes","status":"pass","version":"v2.7.4"}

# MongoDB
$ kubectl exec -n opentwins opentwins-mongodb-0 -- mongosh --quiet --eval 'db.adminCommand({ping:1})'
{"ok":1}
databases: admin, config, ditto, local        # 'ditto' created => Ditto is really writing
```

**Ditto connections created by the post-install hook** (verified in MongoDB and via the devops
piggyback API):

```
$ ... db.connection_journal.distinct("pid")
connection:mosquitto-source-connection | connection:mosquitto-target-connection

$ retrieveConnectionStatus, both connections:
{"liveStatus": "open", "recoveryStatus": "succeeded", "connectionStatus": "open", "status": 200}
```

Only the two mosquitto connections exist, which is correct — the hono source connection is
configured in `values.yaml` but `hono.enabled: false`, so it is skipped.

### 9. Anomalies not worth fixing

**`opentwins-telegraf` shows `RESTARTS 2`.** Benign startup race — telegraf came up before
mosquitto was accepting TCP:

```
E! [telegraf] Error running agent: starting input inputs.mqtt_consumer:
   network Error : dial tcp 10.43.83.200:1883: connect: connection refused
```

It self-healed on the third start and has been stable since; current logs show it connected to
`outputs.influxdb_v2` and polling normally. The chart ships no init container or retry for this,
so a couple of restarts on a cold install are expected. **It only stops being benign if the count
keeps climbing** — a steady `RESTARTS` value with a healthy log is fine.

### 10. Memory headroom (for future tuning)

Steady-state usage against the new 2048 MiB limit:

```
opentwins-ditto-connectivity   751Mi        opentwins-ditto-things        537Mi
opentwins-ditto-thingssearch   684Mi        opentwins-ditto-gateway       456Mi
opentwins-ditto-policies       486Mi
node total: 5676Mi / 121Gi (4%)
```

Everything sits well under 1 GiB on an idle cluster, so 2048 MiB is generous. It buys headroom
for actual twin load, and the node has RAM to spare, so there is no reason to trim it. If someone
does want to drop back to 1024, **`MaxRAM` must be changed to `1073741824` in the same commit** —
see the trap note in §4.

### 11. Scope notes

- No git commits or pushes; `values.yaml` is modified in the working tree for review.
- Nothing outside the `opentwins` namespace was touched. k3s, containerd, Docker and the kernel
  were not modified; the machine was not rebooted.
- No core component was disabled to make the deploy look green. Components that were already
  disabled by default (hono, kafka, kafka-ml, strimzi, the example twin) stay disabled.
- The locally built `openegiz/ditto-extended-api:arm64-b49663d` image was pulled from the k3s
  containerd image store as intended — `pullPolicy: IfNotPresent`, no registry access, no
  `ImagePullBackOff` at any point.

---

## 2026-08-07 — End-to-end telemetry write-path test

First write-path test of the stack. Everything before this was read-only health checking:
pods green, endpoints answering. This section proves that a telemetry message actually
travels the whole chain and comes out queryable in Grafana.

**Result: all hops PASS.** No fixes were needed — the pipeline works as shipped.

```
MQTT publish → Ditto source connection → twin state in Ditto → Ditto target connection
            → mosquitto opentwins/# → Telegraf → InfluxDB2 → Grafana datasource
```

### 1. The contract (read this first — course materials need it)

Two things must line up: the **MQTT topic** and the **payload envelope**.

**Topic:** `telemetry/<thingId>` — e.g. `telemetry/test:winterschool-1`.
The Ditto source connection subscribes to `telemetry/#`. The `<thingId>` in the topic is
cosmetic — Ditto routes on the `topic` field *inside* the payload, not on the MQTT topic.
Keeping them consistent is convention, not a requirement.

**Payload:** a raw **Ditto Protocol** envelope. There is **no payload mapper** on the source
connection, so anything that is not valid Ditto Protocol is dropped. Minimal working form:

```json
{
  "topic": "test/winterschool-1/things/twin/commands/modify",
  "path": "/features",
  "value": {
    "temperature": {
      "properties": {
        "value": 42.5,
        "timestamp": "2026-08-07T09:04:58Z"
      }
    }
  }
}
```

Envelope `topic` is `<namespace>/<name>/things/twin/commands/modify` — note the **`/`**
separator between namespace and name, while the thing ID uses **`:`**
(`test:winterschool-1` → `test/winterschool-1`). This is the single most common mistake.

This matches exactly what `data-generator/data_generator.py` builds
(`build_ditto_message()` / `MqttPublisher.topic`), so the generators in the repo are correct
and can be used as-is.

**The Thing must already exist in Ditto**, with a policy. A `modify` command against a
non-existent thing does not create it through this path.

### 2. Live configuration, as verified on the cluster

`GET /api/2/connections` returns `[]` even though both connections exist and work — a known
Ditto quirk (`retrieveAllConnections` does not enumerate sharded connection actors). Use the
devops piggyback API instead:

```bash
curl -s -u devops:foobar -X POST \
  "http://localhost:30525/devops/piggyback/connectivity?timeout=10s" \
  -H "Content-Type: application/json" \
  -d '{"targetActorSelection":"/system/sharding/connection","headers":{"aggregate":false},
       "piggybackCommand":{"type":"connectivity.commands:retrieveConnection",
                           "connectionId":"mosquitto-source-connection"}}'
```

Both connections are `"connectionStatus":"open"`:

| Connection | Direction | Address |
|---|---|---|
| `mosquitto-source-connection` | in | subscribes `telemetry/#`, authCtx `nginx:ditto`, **no payload mapping** |
| `mosquitto-target-connection` | out | publishes `opentwins/{{topic:channel}}/{{topic:criterion}}/{{thing:namespace}}/{{thing:name}}` |

The target connection enriches events with
`extraFields=thingId,attributes/_parents,features/idSimulationRun/properties/value`.
That `extra.thingId` is **load-bearing** — Telegraf uses it as the InfluxDB tag.

Telegraf (`cm/opentwins-telegraf-real-config`) consumes `opentwins/#` from
`tcp://opentwins-mosquitto:1883`, parses `json_v2`, and writes to InfluxDB2
org `opentwins` / bucket `default`. Field names are flattened from the event value:
`value_temperature_properties_value`. Measurement is `mqtt_consumer`.

Auth used: Ditto `ditto:ditto` (things/policies) and `devops:foobar` (connections) on
NodePort 30525; Mosquitto NodePort 30511 (no auth); InfluxDB token from
`secret/opentwins-influxdb2-auth` key `admin-token`.

### 3. Test artifacts

The default policy created by the post-install hook is `default:basic_policy` (subject
`nginx:ditto`, full READ/WRITE) — reuse it, do not invent a new one.

**Test Thing: `test:winterschool-1`. Left in place deliberately — it is useful for the course.**

```bash
curl -s -u ditto:ditto -X PUT \
  -H "Content-Type: application/json" \
  http://localhost:30525/api/2/things/test:winterschool-1 \
  -d '{"policyId":"default:basic_policy",
       "attributes":{"purpose":"e2e-write-path-test"},
       "features":{"temperature":{"properties":{"value":0}}}}'
# → HTTP 201
```

### 4. Publishing

`mosquitto_pub` / `mosquitto_sub` are already present inside the mosquitto pod
(`/usr/bin/`), so no client install is needed on the host:

```bash
kubectl exec -n opentwins deploy/opentwins-mosquitto -c mosquitto -- \
  mosquitto_pub -h localhost -p 1883 \
    -t 'telemetry/test:winterschool-1' \
    -m '{"topic":"test/winterschool-1/things/twin/commands/modify",
         "path":"/features",
         "value":{"temperature":{"properties":{"value":42.5,
                  "timestamp":"2026-08-07T09:04:58Z"}}}}'
```

From a laptop on the LAN the same works against `gx10-11:30511` — that is what the
data-generator scripts do by default.

### 5. Evidence per hop

**Hop A — MQTT → Ditto twin state: PASS.**
`GET /api/2/things/test:winterschool-1` right after the publish:

```json
{"thingId":"test:winterschool-1","policyId":"default:basic_policy",
 "attributes":{"purpose":"e2e-write-path-test"},
 "features":{"temperature":{"properties":{"value":42.5,"timestamp":"2026-08-07T09:04:58Z"}}}}
```

The feature moved from the seeded `0` to `42.5`.

**Hop B — Ditto → mosquitto `opentwins/#`: PASS.**
`mosquitto_sub -t 'opentwins/#' -v` running during the publish captured, on topic
`opentwins/twin/events/test/winterschool-1`:

```json
{"topic":"test/winterschool-1/things/twin/events/modified",
 "headers":{"ditto-originator":"nginx:ditto","response-required":false,"version":2,
            "requested-acks":[],"content-type":"application/json"},
 "path":"/features",
 "value":{"temperature":{"properties":{"value":42.5,"timestamp":"2026-08-07T09:04:58Z"}}},
 "extra":{"thingId":"test:winterschool-1"},
 "revision":2,"timestamp":"2026-08-07T09:05:00.491024520Z"}
```

Note the topic expansion: `channel=twin`, `criterion=events`, `namespace=test`,
`name=winterschool-1`. And `extra.thingId` is present, as Telegraf requires.

**Hop C — Telegraf → InfluxDB2: PASS.**
Telegraf log at the moment of the publish:

```
2026-08-07T09:05:00Z D! [parsers.json_v2::mqtt_consumer] the path "extra.attributes._parents" doesn't exist
2026-08-07T09:05:00Z D! [parsers.json_v2::mqtt_consumer] the path "headers.correlation-id" doesn't exist
2026-08-07T09:05:00Z D! [parsers.json_v2::mqtt_consumer] the path "extra.features.idSimulationRun.properties.value" doesn't exist
2026-08-07T09:05:02Z D! [outputs.influxdb_v2] Wrote batch of 1 metrics in 4.652741ms
```

Those three `doesn't exist` lines are **harmless** — all three paths are declared
`optional = true` in the Telegraf config. They appear for every twin that has no parent
hierarchy and no simulation-run id, i.e. for most twins. Do not chase them.

Three more points were published (43.7, 44.9, 46.1) to confirm a real series:

```bash
TOKEN=$(kubectl get secret -n opentwins opentwins-influxdb2-auth \
          -o jsonpath='{.data.admin-token}' | base64 -d)
kubectl exec -n opentwins opentwins-influxdb2-0 -- \
  influx query --org opentwins --token "$TOKEN" --raw '
    from(bucket: "default")
      |> range(start: -1h)
      |> filter(fn: (r) => r.thingId == "test:winterschool-1"
                        and r._field == "value_temperature_properties_value")
      |> keep(columns: ["_time","_value","thingId"])'
```

```
,result,table,_time,_value,thingId
,,0,2026-08-07T09:04:43.432808186Z,0,test:winterschool-1     ← the PUT that created the thing
,,0,2026-08-07T09:05:00.508938666Z,42.5,test:winterschool-1
,,0,2026-08-07T09:05:47.349029281Z,43.7,test:winterschool-1
,,0,2026-08-07T09:05:53.541139617Z,46.1,test:winterschool-1
,,0,2026-08-07T09:05:50.439413732Z,44.9,test:winterschool-1
```

Worth noticing: the first row is the **REST PUT**, not an MQTT message. Ditto emits a twin
event for *any* state change regardless of origin, so the HTTP API is also a valid ingestion
path into InfluxDB. Useful for the course when demonstrating that the twin — not the
transport — is the source of truth.

Full tag set on the measurement: `_measurement=mqtt_consumer`, `thingId`, `topic`,
`originator=nginx:ditto`, `host=telegraf-polling-service`, and `correlationId` when present.

**Hop D — Grafana reads it: PASS.**
Queried through Grafana's own datasource proxy rather than trusting that the datasource
merely exists:

```bash
curl -s -u admin:admin -X POST http://localhost:30718/api/ds/query \
  -H 'Content-Type: application/json' \
  -d '{"queries":[{"refId":"A","datasource":{"type":"influxdb","uid":"P4528D75AB74BE2EA"},
       "query":"from(bucket: \"default\") |> range(start: -1h) |> filter(...)"}],
       "from":"now-1h","to":"now"}'
```

```json
"status":200,
"data":{"values":[[1786093483432,1786093500508,1786093547349,1786093550439,1786093553541],
                  [0,42.5,43.7,44.9,46.1]]}
```

Grafana returns the series with correct types (`time` + `float64`). The chain is complete.

### 6. Failures and fixes

None. No fix was applied, no chart or release change was made. The only non-obvious moment
was `GET /api/2/connections` returning `[]`, which briefly looked like the connections had
vanished; the piggyback API showed both open and healthy, and the write path then worked on
the first attempt.

### 7. Gotchas to carry into the course materials

- Thing ID uses `:`, envelope topic uses `/`. `test:winterschool-1` → `test/winterschool-1`.
- No payload mapper on the source connection: malformed payloads are silently dropped,
  with no Ditto error visible to the publisher (QoS 0, no reply target used). Debug by
  subscribing to `opentwins/#` and watching for the absence of an event.
- The Thing must exist beforehand, with a policy. Reuse `default:basic_policy`.
- Latency end to end is ~10 s, dominated by Telegraf's `flush_interval = "10s"`. That is
  configuration, not a problem — but it will confuse anyone refreshing Grafana immediately.
- Telegraf's `optional = true` paths log `doesn't exist` at debug level on every message.
  Expected noise (`debug = true` is on in the shipped config).

---

## 2026-08-07 — Rebrand-lite: Grafana plugins vendored + rebranded

Removed the runtime dependency on ertis-research GitHub releases and rebranded the visible plugin UI. Full details: [notes-rebrand-plugins.md](notes-rebrand-plugins.md).

- Both plugin zips now live in [vendor/grafana-plugins/](../vendor/grafana-plugins/) (patched) with pristine upstream copies + sha256 in `upstream/` for provenance; grafana's init container wgets them from this repo's raw URLs instead of ertis releases (`.helmignore` excludes vendor/ from chart packaging).
- `ertis-opentwins-app`: display name, README, in-app header `<h1>`, config-page text → OpenEgiz; logo (incl. the webpack-emitted header copy) → openegiz logo. Compiled-JS edits required recomputing SRI hashes in module.js — method verified against pristine upstream first; reproducible via `vendor/grafana-plugins/patch-branding.py` (aborts loudly if upstream drifts). Plugin id and `opentwins.agents/*` label keys deliberately untouched (functional).
- `ertis-unity-panel`: README rebranded only; Unity logo kept (that panel has no OpenTwins branding, and the Unity mark aids identification in the panel picker).
- ERTIS attribution and upstream links kept in plugin metadata/READMEs — the plugins are ERTIS's Apache-2.0 work; we rebrand the platform surface, not authorship.
- Validation: per-entry sha256 diff vs upstream (only intended entries differ), `unzip -t` clean, `patch-branding.py --check` idempotent, `helm template` renders with zero `ertis-research` references.

---

## 2026-08-07 — Rebrand deploy + grafana initChownData crashloop

Helm upgrade to pick up the vendored plugins hit a **pre-existing grafana-chart landmine**: the new pod crashlooped in `Init:Error` on `init-chown-data` with `chown: /var/lib/grafana/pdf: Permission denied` (old pod kept serving — no outage).

Root cause: `init-chown-data` runs as root but the chart drops ALL capabilities except `CHOWN`. On a **fresh** PVC there is nothing to recurse into, so first install works. At runtime Grafana creates `csv/`, `pdf/`, `png/` with mode 700 owned by uid 472 — recursing into a 700 directory you don't own requires `CAP_DAC_OVERRIDE`, which was dropped. So **every upgrade after first install** fails in Init. Ownership is already correct via `fsGroup: 472`, making the chown pass useless here → fixed with `grafana.initChownData.enabled: false` (commented in values.yaml). Upgrade then converged in 20 s.

Verification of the rebranded plugins in the live cluster:
- init container fetched both zips from `raw.githubusercontent.com/aleka07/openegiz` (vendored copies)
- `plugin.json` name = **OpenEgiz**; `396.js` header string patched; Grafana API `/api/plugins/ertis-opentwins-app/settings` → `name: OpenEgiz, enabled: true, pinned: true`
- 14/14 pods Running (release revision 3)
