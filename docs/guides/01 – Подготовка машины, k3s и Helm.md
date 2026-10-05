# 01. Подготовка машины, k3s и Helm

В этом гайде мы берём чистую машину и доводим её до состояния «есть рабочий Kubernetes и Helm». Платформу пока не ставим — этим занимается гайд [02](02%20–%20Установка%20платформы%20на%20ARM64.md).

Всё проверено на gx10-11: Ubuntu 24.04.4, aarch64, 20 CPU / 121 GB RAM. Установка занимает пару минут и не требует ни одного воркэраунда — все грабли ниже касаются не установки, а того, что будет **после** неё.

## Что должно быть до старта

Проверяем машину одной командой:

```bash
uname -m                    # ожидаем aarch64
df -h / | tail -1           # места должно быть десятки гигабайт
command -v k3s || echo "k3s не установлен"
```

На чистой gx10-11 это дало:

```text
aarch64
/dev/nvme0n1p2  916G  46G  824G  6%  /
k3s не установлен
```

Ещё нужен исходящий HTTPS: установщик k3s качает бинарь с `get.k3s.io`, Helm — с `raw.githubusercontent.com`.

## Шаг 0. sudo без пароля (нужно только для скриптов)

Если вы ставите всё руками, сидя в интерактивной SSH-сессии — этот шаг можно пропустить, `sudo` просто спросит пароль.

Он нужен, когда команды идут по SSH неинтерактивно (`ssh -o BatchMode=yes gx10-11 '...'`): такому вызову негде ввести пароль, и `sudo` молча падает. На gx10-11 это решено drop-in файлом в `/etc/sudoers.d/` с `NOPASSWD` для рабочего пользователя.

```bash
# редактировать sudoers ТОЛЬКО через visudo — он проверяет синтаксис
# и не даст сохранить файл, которым можно отрезать себе sudo насовсем
sudo visudo -f /etc/sudoers.d/90-openegiz-nopasswd
```

Содержимое (подставьте своего пользователя):

```text
gx10-11 ALL=(ALL) NOPASSWD:ALL
```

Понятно, что на машине в общей сети так делать не стоит. Это учебный стенд в LAN — компромисс осознанный.

## Шаг 1. Ставим k3s

k3s — это Kubernetes одним бинарём: контрол-плейн, kubelet, containerd и Traefik в комплекте. Для одной машины это ровно то, что нужно.

```bash
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
```

Что делает флаг `--write-kubeconfig-mode 644`: без него `/etc/rancher/k3s/k3s.yaml` создаётся с правами `600` от root, и любой `kubectl` без `sudo` падает с permission denied. С ним конфиг читается обычным пользователем.

Установщик сам определяет архитектуру и тянет `k3s-arm64` — никаких флагов для ARM не нужно. Ставится в `/usr/local/bin/k3s`, заводит systemd-юнит `k3s.service` (enabled + started) и симлинки `kubectl` и `crictl`.

Установленные версии (проверено):

| Компонент | Версия |
|---|---|
| k3s | `v1.36.3+k3s1` |
| Kubernetes (server и kubectl) | `v1.36.3+k3s1` |
| containerd (внутри k3s) | `2.3.2-k3s2` |
| Traefik (встроенный чарт k3s) | `traefik-40.1.4+up40.1.0`, app `v3.7.1` |

### Грабля первая: `ctr` указывает не туда

В выводе установщика есть такая строка, и это не ошибка:

```text
[INFO]  Skipping /usr/local/bin/ctr symlink to k3s, command exists in PATH at /usr/bin/ctr
```

На машине уже стоял Docker, а с ним — свой `ctr`. k3s увидел его в PATH и **не создал свой симлинк**. То есть `ctr` в терминале говорит с containerd Docker'а, а не с containerd кластера.

Практический вывод: когда будем импортировать локально собранный образ в кластер (гайд [02](02%20–%20Установка%20платформы%20на%20ARM64.md)), команда должна быть строго такой:

```bash
sudo k3s ctr images import -
```

Простой `ctr images import` положит образ не туда, и под потом свалится в `ImagePullBackOff` — при том, что «образ же импортирован».

## Шаг 2. Ждём готовности кластера

Нода становится `Ready` почти сразу, но kube-system сходится дольше. Ждём, пока все поды перейдут в `Running`/`Completed`:

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
watch -n 2 'kubectl get nodes; kubectl get pods -A'
```

На gx10-11 нода отрапортовала `Ready` через ~2 секунды, полная сходимость kube-system заняла **54 секунды**.

Итоговое состояние:

```text
$ kubectl get nodes -o wide
NAME        STATUS   ROLES           VERSION        INTERNAL-IP     CONTAINER-RUNTIME
gx10-7897   Ready    control-plane   v1.36.3+k3s1   <host-ip>   containerd://2.3.2-k3s2

$ kubectl get pods -A
kube-system   coredns-...                     1/1   Running
kube-system   helm-install-traefik-crd-...    0/1   Completed
kube-system   helm-install-traefik-...        0/1   Completed   RESTARTS 2
kube-system   local-path-provisioner-...      1/1   Running
kube-system   metrics-server-...              1/1   Running
kube-system   svclb-traefik-...               2/2   Running
kube-system   traefik-...                     1/1   Running
```

**`RESTARTS 2` у `helm-install-traefik` — это нормально.** Джоба установки Traefik стартует раньше, чем джоба его CRD успевает доделать работу, падает и перезапускается контроллером. Само чинится. Тревожиться стоит только если джоба вместо `Completed` застряла в `CrashLoopBackOff`.

## Шаг 3. Ставим Helm

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

Скрипт сам определяет arm64, тянет `helm-v3.21.3-linux-arm64.tar.gz`, проверяет контрольную сумму и кладёт бинарь в `/usr/local/bin/helm`. Пароль не спрашивает — sudo вызывается внутри.

## Шаг 4. KUBECONFIG на постоянку

Чтобы `kubectl` и `helm` работали без ручного экспорта:

```bash
grep -q "KUBECONFIG=/etc/rancher/k3s/k3s.yaml" ~/.bashrc || \
  printf '\nexport KUBECONFIG=/etc/rancher/k3s/k3s.yaml\n' >> ~/.bashrc
```

Проверяем в новой сессии:

```bash
ssh gx10-11 'bash -ic "kubectl get nodes && helm ls -A --short"'
```

### Грабля вторая: в неинтерактивной сессии это не сработает

Стандартный `~/.bashrc` в Ubuntu в самом начале имеет ранний выход для неинтерактивных шеллов. То есть:

```bash
ssh gx10-11 'kubectl get nodes'          # ❌ не подхватит KUBECONFIG, упадёт
ssh gx10-11 'bash -ic "kubectl get nodes"'   # ✅ форсим интерактивный режим
```

Для скриптов надёжнее вообще не полагаться на `.bashrc` и экспортировать явно:

```bash
ssh gx10-11 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; kubectl get nodes'
```

Именно так написаны все команды в [install-log.md](../install-log.md), и по этой же причине.

## Что мы не трогали

Docker, ядро, `update-alternatives`, никаких ребутов. k3s ставится рядом с Docker и не конфликтует с ним — единственное пересечение это тот самый `ctr` из грабли №1.

## Готово, если

```bash
kubectl get nodes          # одна нода, Ready
kubectl get pods -A        # всё Running / Completed
helm version               # v3.x
```

Дальше — гайд [02 – Установка платформы на ARM64](02%20–%20Установка%20платформы%20на%20ARM64.md).
