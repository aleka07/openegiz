#!/bin/bash
# Upload build files to the Unity WebGL nginx pod and print access links

RELEASE_NAME="${1:-openegiz}"

POD=$(kubectl get pods -l "app.kubernetes.io/name=${RELEASE_NAME}-unity-webgl-server" -o jsonpath='{.items[0].metadata.name}')
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')

if [ -z "$POD" ]; then
    echo "Error: Could not find unity-webgl-server pod"
    exit 1
fi

echo "Uploading to pod: $POD"
echo ""

for f in ./build/*; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    echo "  Uploading: $name"
    kubectl cp "$f" "$POD:/usr/share/nginx/html/build/$name"
done

echo ""
echo "Access links:"
for f in ./build/*; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    echo "  http://${NODE_IP}:30530/build/${name}"
done
