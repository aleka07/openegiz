#!/bin/bash
# OpenEgiz — Show pod endpoints

NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || echo "localhost")

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║              🚀  OpenEgiz — Pod Endpoints                  ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""

printf "${DIM}%-30s %-12s %-28s${RESET}\n" "SERVICE" "STATUS" "ENDPOINT"
echo -e "${DIM}──────────────────────────────────────────────────────────────────${RESET}"

# NodePort services
kubectl get svc --no-headers -o custom-columns='NAME:.metadata.name,TYPE:.spec.type,PORT:.spec.ports[0].nodePort' 2>/dev/null \
| while read -r name type nodeport; do
    [ "$type" != "NodePort" ] && continue
    [ "$nodeport" = "<none>" ] && continue

    # Try to find pod status by common label patterns
    pod_status=$(kubectl get pods -l "app.kubernetes.io/name=$name" -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
    [ -z "$pod_status" ] && pod_status=$(kubectl get pods -l "app=$name" -o jsonpath='{.items[0].status.phase}' 2>/dev/null)

    if [ "$pod_status" = "Running" ]; then
        status="${GREEN}● Running ${RESET}"
    elif [ -n "$pod_status" ]; then
        status="${YELLOW}○ ${pod_status} ${RESET}"
    else
        status="${DIM}○ Unknown ${RESET}"
    fi

    endpoint="http://${NODE_IP}:${nodeport}"
    printf "  %-28s " "$name"
    echo -en "$status"
    echo -e "  ${CYAN}${endpoint}${RESET}"
done

# ClusterIP services
echo ""
echo -e "${DIM}── ClusterIP (internal only) ──────────────────────────────────${RESET}"

kubectl get svc --no-headers -o custom-columns='NAME:.metadata.name,TYPE:.spec.type,IP:.spec.clusterIP,PORT:.spec.ports[0].port' 2>/dev/null \
| while read -r name type ip port; do
    [ "$type" != "ClusterIP" ] && continue
    [ "$name" = "kubernetes" ] && continue
    printf "  ${DIM}%-28s %s:%s${RESET}\n" "$name" "$ip" "$port"
done

echo ""
