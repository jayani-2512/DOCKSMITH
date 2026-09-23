#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="${DOCKSMITH_HOME:-$HOME/.docksmith}"
IMAGES_DIR="$BASE_DIR/images"
LAYERS_DIR="$BASE_DIR/layers"
CACHE_DIR="$BASE_DIR/cache"

mkdir -p "$IMAGES_DIR" "$LAYERS_DIR" "$CACHE_DIR"

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

mkdir -p "$tmp_root/bin"
cp /bin/sh "$tmp_root/bin/"
cp /bin/cat "$tmp_root/bin/"

copy_libs_for_bin() {
  local bin="$1"
  ldd "$bin" | awk '/=> \// { print $3; next } $1 ~ /^\// { print $1 }' | while read -r lib; do
    [ -f "$lib" ] || continue
    mkdir -p "$tmp_root$(dirname "$lib")"
    cp "$lib" "$tmp_root$lib"
  done
}

copy_libs_for_bin /bin/sh
copy_libs_for_bin /bin/cat

tar_path="$(mktemp /tmp/docksmith-base-XXXXXX.tar)"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 -cf "$tar_path" -C "$tmp_root" .
layer_digest="$(sha256sum "$tar_path" | awk '{print $1}')"
layer_file="$LAYERS_DIR/sha256_${layer_digest}.tar"
mv "$tar_path" "$layer_file"
layer_size="$(stat -c%s "$layer_file")"

manifest_path="$IMAGES_DIR/base-shell_latest.json"
cat > "$manifest_path" << EOF
{
  "name": "base-shell",
  "tag": "latest",
  "digest": "",
  "created": "2026-01-01T00:00:00",
  "config": {
    "Env": [],
    "Cmd": ["/bin/sh", "-lc", "echo base-ready"],
    "WorkingDir": "/"
  },
  "layers": [
    {
      "digest": "sha256:$layer_digest",
      "size": $layer_size,
      "createdBy": "import base-shell"
    }
  ]
}
EOF

python3 - << 'PY'
import hashlib, json, os
base = os.path.expanduser(os.environ.get("DOCKSMITH_HOME", "~/.docksmith"))
path = os.path.join(base, "images", "base-shell_latest.json")
with open(path) as f:
    m = json.load(f)
m["digest"] = ""
raw = json.dumps(m, sort_keys=True).encode()
m["digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
with open(path, "w") as f:
    json.dump(m, f, indent=2, sort_keys=True)
PY

echo "Base image imported: base-shell:latest"
echo "Manifest: $manifest_path"
echo "Layer: $layer_file"
