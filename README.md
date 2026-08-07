# OpenEgiz

<p align="center">
  <img src="openegiz_logo_centered.svg" alt="OpenEgiz logo" width="240">
</p>

An open-source digital twin platform based on OpenTwins.

## Prerequisites

- Docker
- Kubernetes
- Helm v3
- k3s (or any other Kubernetes distribution)

## Install k3s

```bash
curl -sfL https://get.k3s.io | sh - 
# Check for Ready node, takes ~30 seconds 
sudo k3s kubectl get node 
```
### Post install
```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
```

## Install Helm
https://helm.sh/docs/intro/install/

```bash
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-4
chmod 700 get_helm.sh
./get_helm.sh
```

## Quick Start

> [!NOTE]
> Hono is disabled by default in `values.yaml`. If you need it, set `hono.enabled: true`.

```bash
make install
```

> **Примечание:** При первой установке MongoDB может не успеть запуститься до ditto-extended-api. Из-за этого Grafana не сможет подключиться. Перезапустите под:

```bash
kubectl rollout restart deployment/openegiz-ditto-extended-api
```


While waiting for the installation to complete, you can monitor the pod statuses by running:
```bash
watch -n 1 kubectl get pods
```

## Upload Unity WebGL Build

1. Place your Unity WebGL build output into the `build/` folder at the project root
2. Run the upload command:

```bash
make upload-build
```

> [!NOTE]
> If you rebuild in Unity, just run `make upload-build` again to refresh the files.

## Creating Digital Twins

1. Open the Grafana dashboard (run `make endpoints` to find the URL)
2. Go to **OpenTwins** plugin in the left sidebar
3. Click **Twins**
4. Click **New twin**
5. Set the **Namespace** to `org.openegiz`
6. Set the **ID** to `oven-01`
7. Select creation strategy: **From scratch**
8. Set the **Policy ID** to `default:basic-policy`
9. Set the **Name** to `Oven 1`
10. Add 4 features with the following names:
   - `voltage_v`
   - `current_a`
   - `active_power_kw`
   - `power_factor`
11. Repeat steps 3–10 for the second twin with **ID** `oven-02` and **Name** `Oven 2`

### Run the Data Generator

After creating the twins, start sending simulated telemetry data:

```bash
source data-generator/venv/bin/activate
python3 data-generator/data_generator.py
```

## Creating 3D dashboard

1. Go to **Dashboards** in the left sidebar
2. Click **Create dashboard**
3. Click **Add visualization**
4. Select data source **opentwins**
5. In the right corner select visualization **Unity**
6. In the bottom of the screen write a query to get data from the twins
    ```flux
   from(bucket: "default")
   |> range(start: -30s)
   |> filter(fn: (r) => r["_field"] == "value_active_power_kw_properties_value" or r["_field"] == "value_current_a_properties_value" or r["_field"] == "value_power_factor_properties_value" or r["_field"] == "value_voltage_v_properties_value")
   |> last()
   |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
   |> keep(columns: ["thingId", "value_voltage_v_properties_value", "value_current_a_properties_value", "value_active_power_kw_properties_value", "value_power_factor_properties_value"])
    ```
7. Click the **Query Inspector** and in the opened panel click the **refresh** button 
8. In the right panel, configure the **Unity model** section:
   - **Mode**: `External links`
   - Paste the links from `make upload-build` output into the corresponding fields (`.data`, `.framework.js`, `.loader.js`, `.wasm`)
9. In the **Send data to Unity** section:
   - **Grafana query**: `name of your query`
   - **Mode**: `Send data to GameObjects by ID column`
   - **ID column**: `thingId`
   - **Unity function**: `SetValues`
10. Click **Apply** to save the panel
## Makefile Commands

| Command              | Description                                  |
|----------------------|----------------------------------------------|
| `make install`       | Install the Helm chart                       |
| `make upgrade`       | Upgrade the Helm chart                       |
| `make uninstall`     | Uninstall the Helm chart                     |
| `make status`        | Show pod statuses                            |
| `make endpoints`     | Show all service endpoints (IP + port)       |
| `make upload-build`  | Upload Unity WebGL build files to nginx pod  |
| `make generate-data` | Run the data generator for oven twins        |
