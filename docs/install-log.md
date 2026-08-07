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
- [x] Close security hole before school: unauthenticated MongoDB on NodePort 30717 → switch `plainMongodb.service.type` to ClusterIP — done 2026-08-07, see "Security pass" below (плюс ротация всех дефолтных учёток)
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

---

## 2026-08-07 — Course tools: pm4py + JaamSim

The two remaining course tools installed on `gx10-11` as plain user-space installs, deliberately **outside** k3s. Nothing in the cluster, Docker, or `update-alternatives` was touched; no reboot. Full re-setup instructions: [notes-course-tools.md](notes-course-tools.md) (mirrored on the host at `~/course/README.md`).

Host: Ubuntu 24.04, aarch64, Python 3.12.3, OpenJDK 1.8.0_492, 20 CPU / 121 GB RAM.

### 1. pm4py — process mining

```bash
sudo apt-get install -y graphviz          # `dot` binary for process-map rendering
mkdir -p ~/course && python3 -m venv ~/course/venv
~/course/venv/bin/pip install --upgrade pip setuptools wheel
~/course/venv/bin/pip install pm4py pandas matplotlib jupyterlab paho-mqtt influxdb-client
```

`python3-venv` was already present, so no extra apt install was needed there. Every package resolved to a prebuilt **aarch64 wheel** — no source builds, whole install took 68 s. That was the main risk going in (pm4py pulls `cvxopt` and `scipy`, both of which would be miserable to compile on ARM) and it did not materialise.

Versions: **pm4py 2.7.23.3**, pandas 3.0.5, numpy 2.5.1, scipy 1.18.0, cvxopt 1.3.3, networkx 3.6.1, matplotlib 3.11.1, jupyterlab 4.6.2, paho-mqtt 2.1.0, influxdb-client 1.50.0, graphviz-python 0.21, system graphviz 2.42.2-9ubuntu0.1 (`dot` reports 2.43.0).

`paho-mqtt` + `influxdb-client` are the loop-facing pieces: MQTT for live event ingestion, InfluxDB for pulling the historical event log the miner runs against.

Pinned sets written to `~/course/requirements.txt` (6 top-level lines) and `~/course/requirements-frozen.txt` (112 pinned lines from `pip freeze`).

**Functional check** — `~/course/pm4py_check.py` builds a 19-row synthetic event log (4 cases, 7 activities, columns `case:concept:name` / `concept:name` / `time:timestamp`) via `pm4py.format_dataframe`, then runs the inductive miner, token-based replay, DFG discovery, and a graphviz PNG export:

```
rows=19 cases=4 activities=7
PETRI NET: places=7 transitions=8 arcs=16
initial_marking=['source:1'] final_marking=['sink:1']
visible transitions: ['Backorder','Cancel','Check Stock','Invoice','Pack','Receive Order','Ship']
fitness (token-based replay): {'perc_fit_traces': 100.0, 'average_trace_fitness': 1.0, 'log_fitness': 1.0}
DFG edges=7 start={'Receive Order': 4} end={'Invoice': 3, 'Cancel': 1}
rendered PNG bytes: 44783
PM4PY FUNCTIONAL CHECK OK
```

All 7 activities came back as labelled transitions and the DFG edge count (7) matches the 7 distinct directly-follows pairs in the input by hand, so this is a real discovery result, not an import smoke test. The PNG export additionally proves the graphviz path works headless. Fitness 1.0 is expected and is *not* evidence of a good model — the inductive miner guarantees perfect replay of its own input log.

Two cosmetic surprises worth knowing before a lab: pm4py prints a large AGPL licensing banner to stderr on import, and token-based replay writes a tqdm progress bar. Both will show up in student notebooks.

### 2. JaamSim — discrete-event simulation

**JaamSim 2026-05** (tag `v2026-05`, published 2026-07-06 — the current latest stable):

```bash
mkdir -p ~/course/jaamsim && cd ~/course/jaamsim
curl -sSL -O https://github.com/jaamsim/jaamsim/releases/download/v2026-05/JaamSim2026-05.jar
# sha256 be8229bbe0a545e1e4a10338aa66dfd3c9e23d933c6f65bc3baa904d6f8fceb9, 19533050 bytes
```

**Java decision: the stock OpenJDK 8 already on the host runs the newest JaamSim, so nothing was installed.** The manifest reads `Created-By: 25+36-LTS (Eclipse Adoptium)` and carries `Enable-Native-Access`, which looks like a Java 24+ requirement — but that only records the JDK that *built* the jar. Checking the actual class file header (`od -An -tu1 -N8` on `JaamSimModel.class`) gives major version **52 = Java 8 target**. Confirmed empirically by running it. So `openjdk-17-jre-headless` was **not** installed and `update-alternatives` was **not** touched: newest JaamSim, zero system change.

**Failure 1 — `-h` and the batch flags.** `java -jar JaamSim2026-05.jar -h` printed nothing at all and exited 0; there is no usage text. Recovered the real flag list by extracting `com/jaamsim/ui/GUIFrame.class` from the jar and running `strings` on it: `-batch`, `-script`, `-zbuffer`, `-headless`, `-quiet`, `-safe_graphics`, `-optional_graphics`.

**Failure 2 — `-batch` is not headless.** Both `-b` and `-batch` still construct the Swing GUI and die:

```
Exception in thread "main" java.awt.HeadlessException:
No X11 DISPLAY variable was set, but this program performed an operation which requires it.
	at com.jaamsim.ui.GUIFrame.createInstance(GUIFrame.java:482)
```

Only **`-headless`** skips the GUI. Nastiest part: these failures **exit with status 0**, so a CI/script wrapper cannot rely on the exit code — it has to assert that the `.rep`/`.dat` files were actually created.

**Failure 3 — silent bad output names.** The first `CourseLine.cfg` used `[WaitQueue].TimeAverage` in `RunOutputList`. That output does not exist, and rather than erroring JaamSim wrote the *literal expression text* into the data column for every row. Fixed to `[WaitQueue].QueueLengthAverage`. Lesson for the lab handout: always eyeball the `.dat` header row against its values.

**Working headless run:**

```bash
cd ~/course/jaamsim/models
java -jar ~/course/jaamsim/JaamSim2026-05.jar CourseLine.cfg -headless
```

`models/CourseLine.cfg` is a minimal `EntityGenerator → Queue → Server → Statistics → EntitySink` line with no graphics blocks at all, `PrintReport TRUE`, and 3 replications. Output, produced next to the cfg with no display present:

- `CourseLine.rep` (17 208 B) — full per-replication report: state times, utilisation, queue-length distribution and cumulative fractions, statistics-collector summary
- `CourseLine.dat` (419 B) — one row per replication for the `RunOutputList` entries plus a mean ± std row

```
Scenario Replication [PartStats].SampleAverage/1[min]  [WaitQueue].QueueLengthAverage  [Machine].Utilisation
1        1           2.346238757658468                1.5293214293516755              0.7913585537183333
1        2           2.4753701582103385               1.6793641707416689              0.8029958646016666
1        3           2.594805740438258                1.8251774990700023              0.8140866982783332
1                    2.4721382187690213  0.3088…      1.6779543663877823  0.3675…     0.8028137055327778  0.0282…
```

Correctness check, not just "a file appeared": arrivals are exponential with mean 1 min and service is uniform on [0.70, 0.90] min, so ρ = λ·E[S] = **0.80** analytically. Measured **0.8028 ± 0.0282** across replications, and ~9.9–10.2k parts through the sink per 10 000-min run. The simulator is genuinely simulating.

Useful extras shipped inside the jar: `unzip -l …jar 'resources/examples/*'` gives ~20 ready-made teaching models (Factory Example with its 10 progressive variants, Job Shop, Cafe), and `resources/documents/JaamSim User Manual.pdf` is the full manual.

### 3. GUI note for the course

The verification above covers **headless batch only** — model execution, reports, replications, parameter sweeps. It does **not** cover the JaamSim model editor, which is Swing + OpenGL. Two options for students who need to build or edit models:

1. `ssh -X gx10-11` with an X server on the student's own machine (XQuartz on macOS, VcXsrv/X410 on Windows). *Nothing was installed on the Mac and this path was not tested.* The 3D view is OpenGL, so expect software-rendering slowness over X11; `-safe_graphics` mitigates.
2. Run the same jar locally on the laptop (cross-platform, JRE only). Recommended for authoring; keep gx10-11 for headless batch runs.

JupyterLab for the pm4py labs should be bound to loopback and reached over a tunnel, never exposed: `jupyter lab --no-browser --ip=127.0.0.1 --port=8888` + `ssh -L 8888:127.0.0.1:8888 gx10-11`.

### 4. Resulting layout

```
~/course/
├── README.md                 # re-setup instructions (mirrored to docs/notes-course-tools.md)
├── requirements.txt          # 6 top-level deps
├── requirements-frozen.txt   # 112 pinned lines
├── pm4py_check.py            # functional smoke test
├── venv/
└── jaamsim/
    ├── JaamSim2026-05.jar
    └── models/CourseLine.cfg (+ .rep, .dat from the verification run)
```

Note: the SSH session to `gx10-11` dropped (100% packet loss to 192.168.0.135) shortly after the final `ls` confirmed this layout. Unrelated to the work — no reboot or service change was made from this session; both installs are pure user-space files under `~/course`.

---

## 2026-08-07 — Real power-loss recovery test + hardening

The whole GX10 fleet lost power mid-day — an unplanned but perfect resilience test.

### What recovered by itself (zero manual intervention) ✅
- k3s + docker: systemd `enabled`, both `active` after boot; node Ready.
- **All 14 pods returned to Running on their own.** Restart counts: most =1 (the boot), grafana =3 / telegraf =4 — benign startup races (deps not yet listening), self-healed.
- Data survived: Ditto twin `test:winterschool-1` (temp 46.1) intact in MongoDB; InfluxDB series intact; Grafana DB + plugins intact. Mongo (WiredTiger journal), InfluxDB (WAL) and k3s kine (SQLite) are crash-safe by design; dmesg shows zero ext4 errors.
- Locally built `openegiz/ditto-extended-api` image survived in k3s containerd store (it lives on disk under /var/lib/rancher).
- NTP re-synced (matters for the time-series data).

### Quirk observed
After the outage the host kept LAN IP 192.168.0.135 but was reachable only via VPN (10.66.66.24) from the workstation — LAN path issue outside the machine (office network also power-cycled?). Both ssh aliases exist; scripts should prefer trying both.

### Hardening applied: Grafana plugin init no longer needs internet at boot
Pre-existing single point of failure (made worse by any network being down after a power cut): the plugin init container `wget`s both zips on **every** pod start and used `set -e` — no network ⇒ Grafana never starts. New script (values.yaml): fresh download when reachable; else fall back to the copy already unpacked on the PVC (WARN); fail only if neither exists. Deployed as release revision 4, converged in 20 s.

Fallback verified for real, not just by reading the code: ran the script in busybox with `--network none` and a fake cached plugin dir → `WARN … keeping cached copy` + continue for the cached one, hard ERROR for the uncached one. In production both plugins are cached on the PVC after the first successful start, so a fully offline boot proceeds.

### Conclusion
The stack is safe against sudden power-offs: everything auto-starts, storage layers are journaled, and the one runtime internet dependency now degrades gracefully. Remaining external factor: BIOS "restore on AC power" (machine did come back by itself this time) and the office LAN, neither controllable from the OS.

---

## 2026-08-07 — Hermes подключён к стеку: MCP-серверы Ditto/InfluxDB + скиллы JaamSim/pm4py

Агент перестал быть просто чат-ботом на локальной модели: он теперь читает и пишет
цифровой двойник, читает историю телеметрии, запускает симуляции и process mining.
Подробности, архитектура и полные транскрипты тестов — в `docs/notes-hermes-integration.md`.
Исходники — в `integrations/hermes/` (единственный источник правды, на хост едет
через rsync + `install.sh`).

### Что добавилось на хосте

| Что | Куда | Как зарегистрировано |
|---|---|---|
| MCP-сервер `openegiz-ditto` (5 тулов) | `~/course/mcp/mcp_ditto.py` | `mcp_servers` в `~/.hermes/config.yaml` |
| MCP-сервер `openegiz-influx` (3 тула) | `~/course/mcp/mcp_influx.py` | там же |
| Скилл `jaamsim` + `run_jaamsim.sh` | `~/.hermes/skills/openegiz/jaamsim/` | автообнаружение по `SKILL.md` |
| Скилл `pm4py-mining` + `influx_to_dataframe.py` | `~/.hermes/skills/openegiz/pm4py-mining/` | автообнаружение |
| Креденшлы | `~/.config/openegiz-mcp.env`, chmod 600 | читается самими MCP-серверами |

`~/course/venv` переиспользован (не заводили второй venv), добавился только
`fastmcp` 3.4.6 — на aarch64 встал без бубна. Токен InfluxDB `install.sh` сам
достаёт из секрета `opentwins-influxdb2-auth` **на хосте**; в репе и в
`config.yaml` его нет, там только путь к env-файлу.

### Правки конфига Hermes

`~/.hermes/config.yaml` тронут ровно одной добавленной секцией `mcp_servers`
(17 строк, `diff` чистый — `model`/`terminal`/`agent`/`platform_toolsets` не тронуты).
Бэкапы снимаются автоматически перед каждой правкой:
`~/.hermes/config.yaml.bak.20260807_163415`, `…_163443`.

Регистрация — штатным `hermes mcp add`, не ручной правкой YAML.
**Грабли:** без TTY `mcp add` после probe'а спрашивает «Enable all N tools?»,
читает EOF и отменяет весь add, молча оставляя конфиг пустым. Лечится
`printf 'y\n' |` перед командой — это уже зашито в `install.sh`.

**Вторые грабли:** `hermes` живёт в `~/.local/bin/hermes`, а `~/.local/bin`
попадает в PATH только из интерактивного `.bashrc`. В неинтерактивном ssh
команды надо звать полным путём.

### Проверено сквозь агента (не руками)

Все 4 обязательных сценария прошли, плюс 3 бонусных. Модель —
`morosystems/ThinkingCap-Qwen3.6-27B-NVFP4` на vLLM, 15–20 с на задачу целиком.

| # | Промпт | Что вызвала | Результат |
|---|---|---|---|
| A | «current temperature of test:winterschool-1» | `ditto/get_feature` | 46.1 — сверено с curl |
| B | «telemetry over the last 24 hours» | `influx/get_recent_telemetry(minutes=1440)` | 6 замеров, 0.0 → 50.5 |
| C | «publish 50.5, then confirm the twin updated» | `ditto/publish_telemetry` → `ditto/get_thing` | двойник стал 50.5, сверено с curl |
| D | «run CourseLine and report server utilization» | `skill_view(jaamsim)` → `terminal(run_jaamsim.sh)` | **0.8028** — настоящее число из `.dat` |
| + | «which twins exist / which sent telemetry» | оба MCP-сервера в одном ходе | верно |
| + | pm4py discovery | `skill_view` → `write_file` → `terminal` | 10 places / 13 transitions / fitness 1.0 |
| + | `set_feature_property` со вложенным путём | REST-запись `status/mode` | HTTP 201, потом удалено |

Тест B со второй попытки: первый прогон дал верные значения, но неверную подпись
(«9 data points» при 5 замерах). Причина — **формат вывода моего тула**, а не
галлюцинация: тул не различал записи `*_value` и `*_timestamp`. После правки
заголовка вывода счёт стал верным. Практический вывод на будущее: тулы должны
отдавать уже посчитанные агрегаты и не оставлять модели арифметику.

Выбор тулов моделью — 6 из 6 верных, включая нетривиальные разграничения
«текущее значение (Ditto) против истории (Influx)» и «опубликовать по MQTT
против записать REST'ом». Скиллы подтягиваются сами по description, без
`--skills`. JaamSim-обёртка отработала как задумано: exit code 0 помечен как
недостоверный, свежесть `.dat`/`.rep` проверена по mtime.

### Состояние стенда после прогонов

`test:winterschool-1` теперь `temperature.value = 50.5` (было 46.1) — след теста C,
оставлен намеренно. Временное свойство `status/mode` удалено.

### Что осталось (не блокирует)

Тулы не отфильтрованы — студентам сейчас доступны и запись в двойник, и
произвольный Flux; для read-only профиля нужен `tools.include`.
`terminal.backend` всё ещё `local` (шелл агента прямо на хосте k3s).
Токен InfluxDB админский, стоит завести read-only на bucket `default`.
Multi-user не решён.

---

## 2026-08-07 — Security pass перед школой: закрыт MongoDB, ротация всех дефолтных учёток

Ревизия 6 чарта. Задача: убрать из стенда всё, что опубликовано в открытом репозитории
или известно наизусть любому, кто читал апстрим OpenTwins.

### 1. MongoDB убрана из сети ✅

`plainMongodb.service.type: NodePort → ClusterIP` (заодно то же самое для отключённого
bitnami-сабчарта, чтобы дыра не вернулась, если его когда-нибудь включат).
Порт 30717 больше не слушается: `nc -z 127.0.0.1 30717` — отказ, `curl` — таймаут.
Сервис `opentwins-mongodb` теперь `ClusterIP 10.43.49.185:27017`.

Ditto это не задело: и Ditto, и extended API, и hono-реестр ходят в Mongo по
внутрикластерному DNS-имени, а имя сервиса не менялось (оно собирается хелпером
`opentwins.mongodb.fullname`). Все 8 подов Ditto живы, коннекторы `open`.
Для разовой инспекции с хоста:
`kubectl port-forward -n opentwins svc/opentwins-mongodb 27017:27017`.

### 2. Ротация учётных данных ✅

Заменены (значения — только на хосте, см. ниже):

| Система | Что было | Что сделано |
|---|---|---|
| Grafana | `admin:admin` | новый пароль в `values` + `grafana cli admin reset-admin-password` в поде (пароль лежит в собственной БД Grafana на PVC, одного секрета мало) |
| Ditto `ditto` | `ditto:ditto` | новый пароль, htpasswd пересобран чартом, nginx перезапущен по checksum-аннотации |
| Ditto `devops` | `devops:foobar` | новый пароль в `basicAuthUsers` **и** в `gateway.config.authentication.devops.*` (devops + status) |
| InfluxDB admin | `password` | смена живого пароля через `POST /api/v2/users/<id>/password` (сабчарт применяет `adminUser` только при первом bootstrap — правка values на живой инстанс не влияет) |
| InfluxDB operator token | токен из `values.yaml`, опубликованный в открытом репозитории | создан новый operator-токен, старый **удалён** из InfluxDB (проверено: 401) |

Проверено: `ditto:ditto` → 401, `devops:foobar` → 401, `admin:admin` в Grafana → 401;
новые учётки → 200. Datasource Grafana: `datasource is working. 3 buckets found`.

**Побочные эффекты, обработанные в том же проходе:**
- Grafana-плагин берёт креды из тех же values через `templates/config-maps/cm-enable-grafana-plugin.yaml` — обновился сам; проверено сквозняком: `GET :30528/api/twins/` → 200 и отдаёт `test:winterschool-1`.
- extended API получает креды из values через `templates/extended-api/deploy.yaml` — под пересоздан, отвечает на 30528.
- `ditto-fixer` держит `devops:пароль` прямо в args деплоймента — шаблон перерисовался, под пересоздан.
- post-install-джобы — это `helm.sh/hook: post-install`, на upgrade не запускаются; существующие коннекторы Ditto→Mosquitto кредов не содержат (Mosquitto без аутентификации, `authorizationContext: nginx:ditto` — это subject, а не пароль). Трогать не потребовалось.
- Telegraf читает токен из configmap, но у деплоймента нет checksum-аннотации → рестарт вручную (`kubectl rollout restart deploy/opentwins-telegraf`), иначе он продолжал бы ходить со старым токеном.
- `~/.config/openegiz-mcp.env` (Hermes) — обновлены `DITTO_PASSWORD` и `INFLUX_TOKEN`.
- `integrations/hermes/install.sh` переписан: пароль Ditto берётся из secrets-оверрайда, токен InfluxDB — read-only (создаётся в поде, если его нет), а после `mcp add` заново накладывается фильтр тулов (иначе повторный запуск установщика молча снимал бы его).

**Mosquitto оставлен без аутентификации намеренно** — курс строится на том, что студент
публикует MQTT с ноутбука в LAN одной командой, без раздачи паролей.

### Где теперь лежат секреты

В git-репозитории паролей нет. `values.yaml` содержит только заведомо невалидные
плейсхолдеры `REPLACE_ME_SEE_SECRETS_VALUES_FILE`, чтобы `helm upgrade` без оверрайда
падал громко, а не восстанавливал апстримные дефолты по-тихому.

| Файл (только на хосте) | Что внутри | Права |
|---|---|---|
| `~/openegiz-deploy/secrets.values.yaml` | helm-оверрайд: пароли Ditto/Grafana/InfluxDB + operator-токен | 600 |
| `~/course/CREDENTIALS.md` | человекочитаемая таблица «система / логин / пароль / где используется» | 600 |
| `~/.config/openegiz-mcp.env` | рантайм Hermes: пароль Ditto + read-only токен | 600 |

Деплой теперь всегда с оверрайдом:
```
helm upgrade opentwins ~/openegiz-deploy/chart -n opentwins \
  -f ~/openegiz-deploy/secrets.values.yaml
```
`make upgrade` подставляет его сам и отказывается работать, если файла нет
(цель `check-secrets`). Скрипты ротации сложены в `~/openegiz-deploy/scripts/`.

### 3. Read-only токен InfluxDB для Hermes ✅

`influx auth create --read-bucket <default>` → токен с правом чтения одного бакета,
прописан в `~/.config/openegiz-mcp.env` вместо админского.
Проверено: `POST /api/v2/query` → 200 с данными, `POST /api/v2/write` → **403**.
`flux_query` с `to()` тоже не проходит (падает на поиске организации — read-only токен
её не видит). Админский токен у агента больше не лежит нигде.

### 4. Фильтр тулов Hermes ✅

В `~/.hermes/config.yaml` (бэкап `config.yaml.bak.20260807_171100`):

```yaml
mcp_servers:
  openegiz-ditto:
    tools:
      exclude:
        - set_feature_property
```

Схема подтверждена по исходникам (`~/.hermes/hermes-agent/tools/mcp_tool.py`,
`_register_server_tools`): `tools.include` — белый список, имеет приоритет;
`tools.exclude` — чёрный; элементы — точные имена тулов или fnmatch-глобы.

`hermes mcp list` показывает `-1 excluded` у `openegiz-ditto`.
Живой прогон `hermes -z "Set the temperature property ... directly ... Do not use telemetry"`:
агент перечислил доступные тулы, не нашёл записи в двойник, отказался и предложил
`publish_telemetry`. Значение двойника не изменилось.
`publish_telemetry` оставлен: он идёт по настоящему пути MQTT → Ditto → Telegraf → InfluxDB
и это демонстрация курса. `flux_query` оставлен — он теперь read-only по токену.

Оговорка: `hermes mcp test openegiz-ditto` по-прежнему показывает 5 тулов — это список,
который отдаёт сам MCP-сервер. Фильтр применяется при регистрации тулов в агенте, а не
на сервере, поэтому смотреть надо на `hermes mcp list` и на поведение агента.

### Сквозная проверка после всех изменений

- 14/14 подов Running.
- Grafana: вход по новому паролю (401 на старом), datasource жив.
- Twins-страница: extended API `GET :30528/api/twins/` → 200, отдаёт `test:winterschool-1`.
- Полный путь записи: `publish_telemetry(63.25)` → MQTT → Ditto (`get_feature` = 63.25)
  → Telegraf (новый токен) → InfluxDB (`get_recent_telemetry` показывает запись 12:14:07).
- Hermes: `hermes -z "What is the current temperature of thing test:winterschool-1?"` →
  корректный ответ через всю цепочку с новыми кредами.

### Остаточные риски (осознанно оставлены)

1. **Mosquitto без аутентификации** на 30511/31039 — требование курса, LAN-стенд.
2. **extended API без аутентификации** на NodePort 30528 — плагин Grafana дёргает его
   из браузера студента, а в самом сервисе аутентификации нет вообще. Кто угодно в LAN
   может читать и писать двойники через этот порт, минуя пароли Ditto. Не чинилось:
   любое решение (ingress с auth, сеть-политика, убрать NodePort) ломает Twins-страницу.
3. **Терминал Hermes — `backend: local`**, то есть шелл агента исполняется прямо на хосте
   k3s. Фильтр тулов закрывает запись в двойник через MCP, но не терминал как таковой.
4. Пароли одинаковые для всех — один общий стенд, персональных учёток нет.
5. `connections.ditto.source.hono.password` в `values.yaml` остался дефолтным — hono
   отключён (`hono.enabled: false`), в кластере этих кредов нет.

---

## 2026-08-07 — Фаза 1 сквозного сценария: виртуальная пекарня (телеметрия + журнал процесса)

Первый прикладной сценарий поверх стенда. До этого через платформу ходил один тестовый
двойник с одним числом; теперь по ней идёт производственная линия из четырёх станций,
которая одновременно генерирует **телеметрию** и **журнал событий процесса**.

Ключевое архитектурное решение: это **два разных потока с разными путями**.

```
                       ┌─ telemetry/<thingId> ─▶ Ditto ─▶ opentwins/# ─┐
simulator.py ──MQTT──▶ │  (Ditto Protocol)      (twin)                 ├─▶ Telegraf ─▶ InfluxDB
    :30511             └─ bakery/events ─────────────────────────────  ┘
                          (плоский JSON)
```

Событие процесса («партия batch-0007 пошла в печь») — утверждение о **партии**, а не о
состоянии **устройства**. У партии нет двойника, и модифицировать в Ditto нечего.
Поэтому журнал идёт мимо Ditto прямо в Telegraf, в собственный measurement.

### Что добавлено

| Файл | Что |
|---|---|
| `data-generator/bakery/simulator.py` | симулятор линии (единственная зависимость — paho-mqtt) |
| `data-generator/bakery/twins.json` + `create_twins.sh` | пять двойников через Ditto API |
| `data-generator/bakery/install.sh` | rsync на хост в `~/course/bakery/` + создание двойников |
| `data-generator/bakery/check_log.py` | проверка журнала через pm4py прямо из InfluxDB |
| `data-generator/bakery/README.md` | топология, режимы, куда что попадает |
| `templates/config-maps/cm-telegraf.yaml` | **второй** `mqtt_consumer` на `bakery/events` |
| `templates/config-maps/cm-bakery-dashboard.yaml` | дашборд Grafana «Bakery Line» |
| `values.yaml` | блок `bakery:`, включён sidecar `grafana.sidecar.dashboards` |

Линия: `mixer-1` (cap 1, ~8 мин) → `proofer-1` (cap 3, ~40 мин) → `oven-1` (cap 1, ~25 мин)
→ `packer-1` (cap 1, ~5 мин), запуск партии каждые ~12 симулированных минут.
Такт печи (25 мин/шт) вдвое хуже темпа запуска — очередь перед печью растёт всю смену.
Расстойка длиннее по времени, но при вместимости 3 её такт 13 мин/шт, и узким местом она
не является: «самая долгая операция» ≠ «бутылочное горлышко», и это отдельный тезис курса.

### Изменение Telegraf и почему именно такое

Существующий `mqtt_consumer` (`opentwins/#`, `json_v2`) **не тронут**. Рядом добавлен
второй вход:

```toml
[[inputs.mqtt_consumer]]
  qos = 1
  servers = ["tcp://opentwins-mosquitto:1883"]
  topics = ["bakery/events"]
  name_override = "batch_events"
  topic_tag = ""
  data_format = "json"
  tag_keys = ["case_id", "activity", "station", "mode"]
  json_string_fields = ["ts", "run_id"]
```

Обоснование:
- `data_format = "json"`, а не `json_v2`. Событие — плоский объект, и `tag_keys` +
  `json_string_fields` выражают ровно то, что нужно журналу (case/activity/resource в теги,
  метка времени в поле). `json_v2` здесь дал бы только церемонию.
- `name_override` — иначе оба входа писали бы в `mqtt_consumer` и смешали телеметрию с
  журналом.
- `topic_tag = ""` — тег `topic` для одного фиксированного топика бесполезен.
- `mode` вынесен в теги дополнительно к требуемым трём: он позволяет одним фильтром
  отделить датасеты разных прогонов.

Флаг: `.Values.bakery.eventLog.enabled` (по умолчанию `true`).

**Известная особенность подтвердилась:** у configmap Telegraf нет checksum-аннотации,
поэтому `helm upgrade` под не перезапускает. После апгрейда нужен
`kubectl rollout restart deploy/opentwins-telegraf -n opentwins`. В логе после рестарта:
`I! Loaded inputs: mqtt_consumer (2x)` и два `Connected [tcp://opentwins-mosquitto:1883]`.

### Дашборд

Провижининг тем же способом, что и datasource: configmap с меткой sidecar'а. Пришлось
**включить** `grafana.sidecar.dashboards` — он был выключен, поэтому третьего sidecar'а в
поде не было (`helm upgrade` пересоздал под, стало 4/4). Папка — `OpenEgiz`
(`sidecar.dashboards.provider.folder`).

UID datasource (`P4528D75AB74BE2EA`) вынесен в `values.yaml` как
`bakery.dashboard.datasourceUid`. Grafana выводит UID провижинированного datasource
детерминированно из его имени, поэтому значение стабильно для datasource с именем
`opentwins`; при переименовании — взять новый из `GET /api/datasources`.

11 панелей: 4 stat (запущено / завершено / WIP / температура печи сейчас), таймсерии по
всем четырём станциям, счётчики линии, bar chart по операциям журнала и таблица самого
журнала событий.

### Развёртывание

```bash
rsync -az --delete --exclude .git ./ vpn-gx10-11:openegiz-deploy/chart/
ssh vpn-gx10-11 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; \
  helm upgrade opentwins ~/openegiz-deploy/chart -n opentwins \
    -f ~/openegiz-deploy/secrets.values.yaml --wait --timeout=15m'
ssh vpn-gx10-11 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; \
  kubectl rollout restart deploy/opentwins-telegraf -n opentwins'
bash data-generator/bakery/install.sh
```

Revision 7. `--delete` в rsync снёс `build/` в копии чарта на хосте (он в `.helmignore`,
на пакет не влияет, но `scripts/upload-build.sh` его читает) — восстановлен отдельным
rsync. На будущее: либо не давать `--delete`, либо синхронизировать `build/` вместе.

### Проверка по хопам

**1. Двойники.** `create_twins.sh` → 5×HTTP 201. `GET :30528/api/twins/` (источник
Twins-страницы плагина) отдаёт все пять:

```
bakery:line      | ['batches_started', 'batches_completed', 'wip']
bakery:mixer-1   | ['motor_load', 'dough_temp']
bakery:oven-1    | ['temp']
bakery:packer-1  | ['throughput']
bakery:proofer-1 | ['temp', 'humidity']
```

**2. Прогон.** 20 партий, `--speedup 200 --telemetry-interval 1.0 --seed 42`:

```
Simulated 09:24:27 of production in 170.4s real time.
Batches started=20 completed=20
Events recorded=160 dropped=0 (normal mode)
MQTT messages: telemetry=855 events=160
  mixer-1    processed=20   still queued=0 in service=0
  proofer-1  processed=20   still queued=0 in service=0
  oven-1     processed=20   still queued=0 in service=0
  packer-1   processed=20   still queued=0 in service=0
```

Очередь перед печью по ходу смены: 0 → 9. Перед остальными станциями — 0–2.

**3. Двойники обновились.** `bakery:line` после прогона: `batches_started=20`,
`batches_completed=20`, `wip=0`. `bakery:oven-1.temp` = 183.07 (остывает после последней
выпечки; при пустой печи уставка 175 °C).

**4. InfluxDB — телеметрия.** 179 точек на каждое поле `*_properties_value` по каждому из
пяти двойников (171 из прогона + 8 от smoke-теста и создания things).
Температура печи: min 0 (это PUT при создании двойника), max **232.74**, mean 218.9 —
уставка выпечки 231 °C достигается, то есть кривая действительно следует за процессом.

**5. InfluxDB — журнал.** По 20 записей на каждую из 8 операций, ровно 8 событий на
партию для всех 20 партий:

```
,,0,8,batch-0001
...
,,0,8,batch-0020
```

**6. Grafana.** Дашборд зарегистрирован: `uid=openegiz-bakery-line`, папка `OpenEgiz`
(`folderUid=dfugp9027vsaoa`). Панели проверены не «наличием», а реальным запросом через
`POST /api/ds/query`: температура печи — 179 точек `[Time, Value]`, таблица журнала —
176 строк `[_time, _value, activity, case_id, station]`, bar chart — 8 столбцов,
счётчик завершённых партий — 223 точки.

**7. pm4py на реальных данных из InfluxDB** (`check_log.py`, режим normal):

```
mode=normal  events=160  cases=20
events per case: min=8 max=8 mean=8.00
complete cases (8 activities): 20/20

DFG: 7 edges, 1 start activities, 1 end activities
  start: {'MixingStarted': 20}
  end:   {'PackingDone': 20}

Edges by mean duration:
     106.5 min  ProofingDone -> BakingStarted     ◀ ожидание перед печью
      39.1 min  ProofingStarted -> ProofingDone
      25.7 min  BakingStarted -> BakingDone
       8.1 min  MixingStarted -> MixingDone
       5.1 min  MixingDone -> ProofingStarted
       5.0 min  PackingStarted -> PackingDone
       0.0 min  BakingDone -> PackingStarted

Max observed queue length per station:
  oven-1     max queue=  9  mean=4.17
  proofer-1  max queue=  2  mean=0.55
  mixer-1 / packer-1: 0
```

Идеальный DFG из 7 рёбер, одно начало, один конец. Ожидание перед печью (106.5 мин) в
**четыре раза** больше самой выпечки (25.7 мин) — узкое место находится без подсказок.
Побочно всплыло вторичное ожидание `MixingDone → ProofingStarted` (5.1 мин): расстойка
периодически забита на все три места.

**8. Грязный прогон.** 10 партий, `--mode dirty --seed 99 --case-start 101`: симулятор
отчитался `recorded=68 dropped=12`, InfluxDB подтверждает 68 против 80 ожидаемых, по
партиям 5–8 событий вместо 8, полных партий 1 из 10. pm4py на этих данных выдаёт
спагетти: 11 рёбер вместо 7 и **три** стартовых активности вместо одной
(`MixingStarted: 7, MixingDone: 2, ProofingStarted: 1`) — ровно тот эффект, ради которого
режим и сделан.

Режим `sparse` проверен на `--dry-run`: теряются ровно `ProofingDone` и `PackingDone`
(2 события на партию), симуляция линии при этом не меняется.

### Данные, оставленные в InfluxDB для фазы 2

| Датасет | case_id | mode | Событий | Комментарий |
|---|---|---|---|---|
| основной | `batch-0001` .. `batch-0020` | `normal` | 160 | 20 полных партий, 8 событий на партию |
| грязный | `batch-0101` .. `batch-0110` | `dirty` | 68 | 12 событий потеряно |
| мусор от smoke-теста | `smoke-0001`, `smoke-0002` | `normal` | 16 | **отфильтровать по префиксу `batch-`** |

Телеметрия по двойникам `bakery:*` за то же окно тоже осталась.

`smoke-*` не удалены: удаление данных из InfluxDB заблокировано политикой окружения.
Вреда нет — `check_log.py` фильтрует по `--case-prefix batch-` по умолчанию, но в
notebook'е фазы 2 этот фильтр нужно поставить явно, иначе в лог попадут две лишние
партии из другого прогона.

Симулятор на хосте **не запущен** — он запускается вручную под демонстрацию.

### Про два времени (важно для фазы 2)

Точка в InfluxDB получает время **приёма** (реальное), поле `ts` — время **процесса**
(симулированное). При `--speedup 200` смена в 9 часов прожимается в 170 секунд, поэтому:

- process mining обязан брать `ts`, иначе все длительности окажутся в 200 раз меньше;
- в Grafana смена выглядит как 3 минуты по оси времени — это не баг;
- при сортировке событий одной партии `ts` до секунды совпадает у пар вроде
  `MixingDone`/`ProofingStarted` (они одновременны по построению) — сортировать нужно с
  тай-брейком по полю `seq`.

### Отказы и починки

1. **Лаг температуры печи был задан «на такт», а не по времени.** При `--speedup 200`
   печь просто не успевала прогреться между отсчётами (в первом прогоне максимум был
   159 °C при уставке 231). Заменено на апериодическое звено с постоянной времени в
   *симулированных* минутах (`approach()`), теперь `--speedup` на физику не влияет.
   Проверено: диапазон стал 157–245 °C.
2. **`pivot()` в Flux не смог свести строковое поле `ts` и числовые в одну колонку**
   (`schema collision: column "_value" is both of type string and float`). `check_log.py`
   тянет их двумя запросами и джойнит по `_time`. Заодно всплыло, что в этой версии Flux
   аргумент называется `valueColumn`, а не `valueColumns`.
3. **`--range -1h` ломал argparse** (минус читается как начало ключа) — в документации и
   примерах только `--range=-1h`.
4. Удаление smoke-данных из InfluxDB заблокировано политикой — см. выше, обошлись
   префиксом case_id.

---

## 2026-08-07 — Фаза 2 сквозного сценария: process mining, JaamSim what-if, runbook, overlay для агента

Фаза 1 оставила симулятор пекарни, двойники `bakery:*` и журнал событий в InfluxDB.
Фаза 2 замыкает петлю: журнал → диагноз → модель → решение, и то же самое через агента.

Артефакты: `data-generator/bakery/{mining.ipynb,mining.py}`,
`data-generator/bakery/jaamsim/{BakeryLine*.cfg,compare_runs.py}`,
`docs/runbook-bakery-scenario.md`, обновлённые скиллы в `integrations/hermes/skills/`.
На хост всё разложено в `~/course/bakery/` и `~/.hermes/skills/openegiz/`.

### Process mining: что реально намайнилось

`mining.py` тянет `batch_events` из InfluxDB (два Flux-запроса с джойном по `_time` —
обход коллизии string/float в `pivot()`, унаследован из `check_log.py`), строит DFG и
сеть Петри, раскладывает время по станциям и печатает таблицу параметров для JaamSim.

Эталонный датасет `batch-0001..0020`, 160 событий, 20 полных партий:

| Станция | Работа, мин | Ожидание, мин | Итого | Доля срока |
|---|---|---|---|---|
| mixer-1 | 8.1 | не измеряется | 8.1 | 4.3 % |
| proofer-1 | 39.1 | 5.1 | 44.2 | 23.3 % |
| **oven-1** | **25.7** | **106.5** | **132.2** | **69.8 %** |
| packer-1 | 5.0 | 0.0 | 5.0 | 2.6 % |

DFG: 7 рёбер, одно стартовое действие, одно конечное, каждый переход по 20 раз.
Сеть Петри (inductive): 9 мест, 8 переходов, 16 дуг, `log_fitness = 1.0000`.
Очередь перед печью: максимум 9, в среднем 4.17.

**Вместимость станций восстановлена из журнала, а не введена руками.** Считается
максимум пересекающихся интервалов `Started..Done` на станцию: получилось 1 / 3 / 1 / 1 —
в точности то, что лежит в атрибутах двойников. Это оказалось лучшим объяснением
разницы между «самой долгой операцией» (расстойка, 39 мин) и «узким местом» (печь):
расстойка вмещает 3 партии, её такт 13 мин/шт, печь вмещает одну при 25 мин/шт.

Параметры для JaamSim (`Scale` = медиана, `NormalMean` = 0, σ = √ln(1+cv²)):

```
station     cap     mean   median     std     cv
mixer-1       1     8.08     7.85    0.91  0.113
proofer-1     3    39.11    38.99    4.65  0.119
oven-1        1    25.67    24.93    3.95  0.154
packer-1      1     4.98     4.96    0.55  0.111
arrivals      -    12.80    12.53    1.71  0.134
```

### Грязный датасет: цена неполного журнала

Тот же код на `batch-0101..0110` (`mode=dirty`, 15 % событий не записалось):

| Показатель | Чистый | Грязный | Ошибка |
|---|---|---|---|
| рёбер в карте | 7 | 11 | +57 % |
| стартовых действий | 1 | 3 | +200 % |
| выпечка, мин | 25.67 | 22.93 | −11 % |
| ожидание печи, мин | 106.49 | 44.54 | **−58 %** |
| срок изготовления, мин | 189.41 | 126.61 | −33 % |
| интервал запуска, мин | 12.80 | 16.39 | **+28 %** |

Появились физически невозможные переходы (`BakingStarted -> PackingDone` — «поставили
в печь и сразу упаковали», 1 раз). Существенно то, что смещение **меняет решение**:
«ждём печь 44 минуты, запускаем раз в 16 минут» — это картина линии, которая почти
справляется, и вторая печь по таким данным не нужна. Ни один этап анализа при этом
не выполнен неправильно.

### JaamSim: модель и что она дала

Разбор объектов JaamSim делался по jar'у (`unzip -l` + `strings` по class-файлам) —
это оказалось быстрее, чем PDF-мануал внутри jar:

- `Server` **не имеет** keyword'а `Capacity` (обрабатывает по одной сущности).
  Станция на 3 партии собрана на `EntityProcessor`, у которого `Capacity` есть.
  Все четыре станции сделаны одинаково — `EntityProcessor` + `Queue`.
- `LogNormalDistribution`: `Scale`, `NormalMean`, `NormalStandardDeviation`
  (последние два — параметры **нормального** распределения под логарифмом, о чём
  прямо сказано в description внутри class-файла). Симулятор фазы 1 рисует
  `lognormvariate(log(mean), 0.12)`, то есть медиана = mean — отсюда решение
  ставить `NormalMean = 0` и `Scale` = намайненная медиана.
- `Queue` отдаёт `AverageQueueTime`, `QueueLengthAverage`, `QueueLengthMaximum`;
  `EntityProcessor` — `UnitsInUseAverage`. `EntityGenerator` в этой сборке
  **не имеет** `MaxNumber`, поэтому «прогнать ровно 20 партий» пришлось делать
  через `RunDuration`.

Модель: `Launch → MixerQueue/Mixer → ProoferQueue/Proofer → OvenQueue/Oven →
PackerQueue/Packer → LeadTime (Statistics) → Shipped`. Смена 540 мин, 3 реплики,
фиксированные зёрна. Блок `PARAMETERS — EDIT HERE (from mining)` — строки 39–91.

Три сценария различаются **ровно одной содержательной строкой** (проверено `diff`).
Результат (`compare_runs.py`, реальные числа из `.dat`):

| Сценарий | Партий/смена | Срок, мин | Очередь печи | Ожидание печи, мин | Загрузка печи |
|---|---|---|---|---|---|
| Baseline | 18.7 ±3.8 | 189.8 ±22.6 | 8.4 ±2.1 | 118.6 ±29.3 | 91 % |
| Вторая печь | **35.0 ±0.0** | **92.6 ±13.8** | **0.5 ±0.6** | **6.7 ±8.3** | 86 % |
| Расстойка −25 % | 19.3 ±2.9 | 184.5 ±30.9 | 9.4 ±2.2 | 126.3 ±25.1 | 93 % |

Вторая печь: +87 % выпуска, −51 % срока, −94 % ожидания.
Расстойка −25 %: +4 % выпуска, а ожидание перед печью **выросло на 7 %** — партии
быстрее добираются до того же ограничения. Дидактически это лучший результат фазы:
таблица делает вывод очевидным без слов про теорию ограничений.

### Калибровка — что сошлось и что нет

**Ни один параметр не подгонялся.** Всё пришло из mining как есть.

| Показатель | Журнал | Модель (baseline) | |
|---|---|---|---|
| Срок изготовления | 189.4 мин | 189.8 ±22.6 | сошлось |
| Ожидание перед печью | 106.5 мин | 118.6 ±29.3 (реплика 1: 106.2) | сошлось в пределах разброса |
| Очередь перед печью, max | 9 | 18.7 | **не сошлось** |

Расхождение по очереди объясняется арифметикой, а не ошибкой модели: в журнале
20 партий (~250 мин запусков), в смене — ~43. Очередь растёт со скоростью
`1/12.5 − 1/25 = 0.04` партии/мин, значит за 250 мин ~10, за 490 (540 минус разогрев
линии) ~20. Проверено отдельным прогоном `BakeryLine_Calibration.cfg`
(`RunDuration { 250 min }`, окно журнала): очередь **max 8.3, средняя 3.07** против
9 и 4.17 в журнале. Файл оставлен в репозитории как доказательство, а не как сценарий.

Независимая проверка воспроизводимости: свежий прогон `--seed 7 --case-start 201`
(`batch-0201..0220`) дал ожидание перед печью 104.3 мин, выпечку 25.2 мин, очередь
9 / 4.17, 7 рёбер и те же восстановленные вместимости 1/3/1/1. Другой случайный
поток — тот же диагноз.

### Overlay для агента и живой тест

Изменены **два файла скиллов**, оба 1.0.0 → 1.1.0, и ничего больше
(`~/.hermes/config.yaml` не трогался, MCP-серверы не трогались):

1. `pm4py-mining/SKILL.md` — расширен `description` (добавлены «production line»,
   «bottleneck»); добавлен раздел с рецептом по `batch_events` (measurement, теги,
   три ловушки `ts`/`seq`/префикс, коллизия pivot) и указателем на
   `mining.py --summary`, плюс таблица датасетов `normal` / `dirty`.
2. `jaamsim/SKILL.md` — расширен `description`; добавлен раздел с четырьмя моделями,
   `compare_runs.py`, разбором блока параметров и ожидаемым ответом.

**Первый живой тест провалил задачу частично.** Промпт
«Проанализируй журнал производства хлебозавода, найди узкое место, прогони what-if
сценарии в JaamSim и дай рекомендацию» → агент загрузил только скилл `jaamsim`,
нашёл `BakeryLine.cfg`, взял параметры **из комментариев в нём** и прогнал
`compare_runs.py`. Ответ верный, но **process mining не запускался вообще**.
Диагноз: в `.cfg` намайненные числа продублированы в шапке, так что у модели не было
причины идти в журнал, а скилл `jaamsim` про майнинг ничего не говорил.

Починка — **одна правка**: в `jaamsim/SKILL.md` добавлен явный хэнд-офф («если в
запросе есть журнал/процесс/узкое место — сначала `mining.py --summary`, и это не
вежливость: параметры в `.cfg` — снимок прошлого прогона»).

Повторный тест тем же промптом — цепочка собралась целиком:

```
skill_view {"name": "jaamsim"}
  → «Следую инструкциям из skill'а: сначала mining, затем simulation»
terminal {"command": "~/course/venv/bin/python ~/course/bakery/mining.py --summary"}
read_file {".../BakeryLine.cfg"}  → «Параметры совпадают с mining»
terminal {"command": "python3 ~/course/bakery/jaamsim/compare_runs.py"}
→ узкое место — печь; измеренное ожидание 106.5 мин и смоделированное 118.6 мин
  приведены раздельно; рекомендация — вторая печь, ускорение расстойки отклонено
```

~2 минуты, 4 содержательных вызова. Работает **одним промптом**; в runbook он
зафиксирован дословно. Двухпромптовая последовательность тоже описана — как запасной
вариант, а не как основной.

Единственная неточность модели за оба прогона: в одной фразе средняя очередь из
симуляции (8.4) названа рядом с максимальной из журнала (9) как будто это одно и то
же. Числа верные, подпись — нет. В runbook это записано в «чего ожидать».

### Отказы и починки

1. **`Server` не умеет `Capacity`.** Расстойка на 3 партии не собиралась. Заменено на
   `EntityProcessor` (у него `Capacity` есть) — для единообразия все четыре станции.
2. **`EntityGenerator` без `MaxNumber`** в этой сборке — «ровно 20 партий» для
   калибровки сделано через `RunDuration { 250 min }`.
3. **Симулятор упал на `ModuleNotFoundError: No module named 'paho'`** — запускался
   системным python3. Нужен `~/course/venv/bin/python`. Записано в FAQ runbook'а.
4. **Агент не запускал mining** — см. выше, лечится одной строкой в `SKILL.md`.
5. **Свежий прогон в `mode=normal` смешивается с эталонным** при фильтре `batch-`.
   В тетради заведён параметр `CASE_PREFIX` со значением по умолчанию `batch-00`,
   чтобы её выводы оставались воспроизводимыми независимо от числа новых прогонов.

### Состояние стенда после фазы

- Кластер: **14/14 подов Running** в `opentwins`, `opentwins-grafana` 4/4.
- Симулятор **остановлен** (`Batches started=20 completed=20`, ничего не висит).
- `~/.hermes/config.yaml` не изменялся; MCP-серверы не изменялись; изменены только
  два `SKILL.md`.
- В InfluxDB добавился третий датасет `batch-0201..0220` (`mode=normal`, 160 событий) —
  демонстрационный прогон для runbook'а. Эталонный `batch-00xx` и грязный `batch-01xx`
  не тронуты; тетрадь по умолчанию читает `batch-00`.

---

## 2026-08-07 — Установка с нуля из репозитория: `bootstrap.sh` + `secrets.values.yaml.example`

Мотивация: после ротации учётных данных (см. раздел «Security pass» выше) `values.yaml`
содержит только заведомо невалидные плейсхолдеры, а реальные значения лежат исключительно
на хосте. Для gx10-11 это правильно, но означало, что **из репозитория поставить платформу
на новую машину нельзя** — не из чего узнать, какие ключи вообще нужны. Плюс путь
«чистая машина → работающий стенд» был размазан по трём гайдам и Makefile'у.

### Что добавлено

**1. `secrets.values.yaml.example`** (корень репозитория) — ровно девять ключей,
структура один в один с боевым `~/openegiz-deploy/secrets.values.yaml`. Структура снята
с хоста скриптом, который печатает только пути ключей, подставляя `CHANGE_ME` вместо
значений; ни одно реальное значение файл не покидало. Перекрёстно сверено с семью
`REPLACE_ME_SEE_SECRETS_VALUES_FILE` в `values.yaml` и с `adminUser` сабчарта influxdb2.

Расхождение семь против девяти объясняется двумя ключами `user:`, которых в `values.yaml`
нет среди плейсхолдеров, но которые есть в оверрайде:

```
ditto.global.basicAuthUsers.ditto.user      = ditto     <- НЕ CHANGE_ME
ditto.global.basicAuthUsers.ditto.password  = CHANGE_ME
ditto.global.basicAuthUsers.devops.user     = devops    <- НЕ CHANGE_ME
ditto.global.basicAuthUsers.devops.password = CHANGE_ME
ditto.gateway.config.authentication.devops.devopsPassword = CHANGE_ME
ditto.gateway.config.authentication.devops.statusPassword = CHANGE_ME
grafana.adminPassword                       = CHANGE_ME
influxdb2.adminUser.password                = CHANGE_ME
influxdb2.adminUser.token                   = CHANGE_ME
```

**Имена пользователей намеренно оставлены литералами, а не `CHANGE_ME`.** Обе
post-install-джобы создают connections с захардкоженным `authorizationContext`
`"nginx:ditto"` (`post-install/ditto-mosquitto-connection/*.json`). Переименование
пользователя `ditto` молча ломает обе MQTT-connection'а — auth-субъект перестаёт
совпадать. В файле это записано отдельным предупреждением над ключом.

Отдельно отмечено, что `grafana.adminPassword` и `influxdb2.adminUser.*` применяются
**только при первом bootstrap** (дальше живут в PVC), — иначе первый же человек, который
попробует сменить пароль правкой оверрайда, потратит час.

**2. `bootstrap.sh`** (корень репозитория) — шесть идемпотентных шагов, каждый с
проверкой и сообщением об ошибке, указывающим на конкретный гайд:

| Шаг | Что делает | Как проверяет |
|---|---|---|
| 0 | preflight | `aarch64`, не root, `sudo -n true`, `docker info`, исходящий HTTPS, ≥20G на `/`, наличие `Chart.yaml` |
| 1 | k3s (`--write-kubeconfig-mode 644`) + Helm | `kubectl wait --for=condition=Ready node`, пропуск если `systemctl is-active k3s` |
| 2 | `rebuild/extended-api/build.sh` | пропуск, если `sudo k3s ctr images ls -q` уже содержит `arm64-b49663d`; после сборки повторная проверка |
| 3 | секреты | отказ без файла + готовые команды копирования; отказ, если в файле остались `CHANGE_ME`; проверка YAML; `chmod 600` |
| 4 | `helm upgrade --install` | сначала `helm template` вхолостую, затем ожидание 14/14 Running с таймаутом и дампом `describe`/`logs`/`events` по не-Running подам |
| 5 | smoke | Ditto `/api/2/things` 200, Ditto `/status/health` 200, extended API `/api/twins/` 200, Grafana `/login` 200, Grafana `/api/datasources` содержит `opentwins`, InfluxDB `/health` 200 |

Опциональные шаги по флагам, по умолчанию выключены: `--with-course-tools`
(venv + pm4py + JaamSim с проверкой sha256 по `notes-course-tools.md`) и `--with-bakery`
(`data-generator/bakery/create_twins.sh` + подсказка про `~/course/venv/bin/python
simulator.py`). Hermes скрипт **не ставит** — в конце печатает указатель на
`integrations/hermes/install.sh`.

### Найдено по дороге: `grafanaPlugin.*URL` ломает любую машину кроме gx10-11

`values.yaml` держит `grafanaPlugin.dittoURL` и `extendedURL` захардкоженными на
`192.168.0.135`. Это фронтенд-плагин, он ходит в Ditto **из браузера пользователя**, так
что cluster-internal DNS туда действительно не годится — но и чужой LAN-IP не годится
тоже. На любой другой машине страница Twins молча покажет «No twins found».

Скрипт читает InternalIP ноды и передаёт `--set grafanaPlugin.dittoURL=http://$IP:30525
--set grafanaPlugin.extendedURL=http://$IP:30528`. Проверено, что оверрайды доезжают до
рендера. Захардкоженное значение в `values.yaml` не тронуто — это дефолт для gx10-11.

### Расхождение гайда и Makefile

Makefile разводит `install` и `upgrade` на две цели. `bootstrap.sh` использует
`helm upgrade --install` — единственную форму, которая идемпотентна и потому годится для
скрипта, который можно перезапустить на полуустановленном хосте. Флаги (`--wait`,
`--timeout`, `-n opentwins --create-namespace`, `-f` с оверрайдом) и прибитое имя релиза
`opentwins` взяты из гайда 02 и Makefile'а без изменений.

Мелочь из гайда 03: там extended API проверяется как `curl :30528/` → `404` («роут `/`
не объявлен, но 404 вместо connection refused доказывает, что express слушает»). Для
smoke-теста этого мало — 404 отдаст и полумёртвый сервис. Скрипт бьёт в
`/api/twins/`, что на живом стенде даёт 200 (проверено на gx10-11 сегодня:
`root=404 twins=200`). Оба факта записаны в комментарии рядом с проверкой.

### Прочее

- `.gitignore`: добавлены `secrets.values.yaml` и `CREDENTIALS.md` — защита от случайной
  копии внутри чекаута. `secrets.values.yaml.example` под игнор не попадает (проверено
  `git check-ignore`).
- `README.md`: новый раздел «Fresh machine install». Заодно исправлен устаревший абзац
  про дефолтные пароли — он всё ещё обещал `admin/admin`, `ditto/ditto`,
  `admin/password` и NodePort у MongoDB, хотя всё это закрыто ротацией 2026-08-07.

### Чего проверить не удалось

**`bootstrap.sh` ни разу не запускался на чистой машине** — владелец сознательно
отказался от живого теста. Проверено: `bash -n`, `helm template opentwins .
-f secrets.values.yaml.example` (рендерится, 5291 строка, ни одного выжившего
`REPLACE_ME`), парсинг примера как YAML, изолированный прогон printf-таблицы и
awk-подсчёта подов на синтетическом выводе `kubectl`. `shellcheck` на рабочей машине
отсутствует — статический анализ ограничен `bash -n` и вычиткой.

Непроверяемое без чистой машины: установка k3s и Helm с нуля, ветка сборки образа в
шаге 2 (на gx10-11 образ уже есть, отработает только ветка skip), реальное сведение
14/14 на другом железе, ветка `--with-course-tools` (на gx10-11 venv уже стоит).
