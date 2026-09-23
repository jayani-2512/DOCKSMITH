import glob
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import time
import uuid

from image.layer_system import (
    CACHE_DIR,
    LAYERS_DIR,
    add_layer,
    compute_manifest_digest,
    create_layer,
    create_manifest,
    extract_layer_tar,
    get_layer_size,
    init_storage,
    load_manifest,
    save_manifest,
    store_layer,
)
from runtime.isolation import run_isolated

CACHE_FILE = os.path.join(CACHE_DIR, "index.json")
VALID_INSTRUCTIONS = {"FROM", "COPY", "RUN", "WORKDIR", "ENV", "CMD"}


def _parse_image_ref(value):
    if ":" in value:
        name, tag = value.split(":", 1)
    else:
        name, tag = value, "latest"
    if not name.strip() or not tag.strip():
        raise ValueError(f"Invalid image reference: {value}")
    return name.strip(), tag.strip()


def parse_docksmithfile(path):
    instructions = []
    with open(path) as f:
        for line_no, raw in enumerate(f, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue

            parts = stripped.split(" ", 1)
            cmd = parts[0].upper()
            value = parts[1] if len(parts) > 1 else ""

            if cmd not in VALID_INSTRUCTIONS:
                raise ValueError(
                    f"Unknown instruction '{cmd}' at line {line_no}: {raw.rstrip()}"
                )

            instructions.append(
                {
                    "cmd": cmd,
                    "value": value,
                    "raw": stripped,
                    "line_no": line_no,
                }
            )

    return instructions


def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE) as f:
        return json.load(f)


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def _snapshot_files(root):
    snap = {}
    for current_root, _, files in os.walk(root):
        for filename in files:
            full = os.path.join(current_root, filename)
            rel = os.path.relpath(full, root).replace("\\", "/")
            snap[rel] = _sha256_file(full)
    return snap


def _delta_file_paths(root, before_snap, after_snap):
    changed_abs = []
    deleted_rel = []
    for rel in sorted(after_snap.keys()):
        if rel not in before_snap or before_snap[rel] != after_snap[rel]:
            changed_abs.append(os.path.join(root, rel))
    for rel in sorted(before_snap.keys()):
        if rel not in after_snap:
            deleted_rel.append(rel)
    return changed_abs, deleted_rel


def _resolve_copy_sources(context, src_expr):
    pattern = os.path.join(context, src_expr)
    matches = glob.glob(pattern, recursive=True)
    if matches:
        return sorted(matches)

    direct = os.path.join(context, src_expr)
    if os.path.exists(direct):
        return [direct]

    raise FileNotFoundError(f"COPY source not found: {src_expr}")


def _compute_copy_sources_hash(context, src_expr):
    sources = _resolve_copy_sources(context, src_expr)
    file_records = []

    for source in sources:
        if os.path.isdir(source):
            for current_root, _, files in os.walk(source):
                for filename in files:
                    full = os.path.join(current_root, filename)
                    rel = os.path.relpath(full, context).replace("\\", "/")
                    file_records.append((rel, _sha256_file(full)))
        else:
            rel = os.path.relpath(source, context).replace("\\", "/")
            file_records.append((rel, _sha256_file(source)))

    file_records.sort(key=lambda x: x[0])
    serialized = "\n".join([f"{path}:{digest}" for path, digest in file_records]).encode()
    return _sha256_bytes(serialized)


def _serialize_env(env_map):
    if not env_map:
        return ""
    parts = [f"{k}={env_map[k]}" for k in sorted(env_map.keys())]
    return "\n".join(parts)


def _compute_cache_key(
    prev_layer_digest,
    instruction_raw,
    workdir,
    env_map,
    copy_sources_hash="",
):
    payload = [
        prev_layer_digest or "",
        instruction_raw,
        workdir or "",
        _serialize_env(env_map),
        copy_sources_hash,
    ]
    return _sha256_bytes("\n---\n".join(payload).encode())


def _ensure_workdir(rootfs, workdir):
    target = os.path.join(rootfs, workdir.lstrip("/")) if workdir else rootfs
    os.makedirs(target, exist_ok=True)


def _extract_manifest_layers(manifest, rootfs):
    for layer in manifest.get("layers", []):
        digest = layer["digest"].replace("sha256:", "")
        tar_path = os.path.join(LAYERS_DIR, f"sha256_{digest}.tar")
        if not os.path.exists(tar_path):
            raise FileNotFoundError(f"Missing base layer file: {tar_path}")
        extract_layer_tar(tar_path, rootfs)


def _copy_into_rootfs(context, src_expr, dest_expr, rootfs):
    sources = _resolve_copy_sources(context, src_expr)

    dest_rel = dest_expr.lstrip("/")
    dest_abs = os.path.join(rootfs, dest_rel)

    multiple = len(sources) > 1
    dest_is_dir_hint = dest_expr.endswith("/") or multiple

    if dest_is_dir_hint:
        os.makedirs(dest_abs, exist_ok=True)

    for src in sources:
        if os.path.isdir(src):
            folder_name = os.path.basename(src.rstrip(os.sep))
            target_base = dest_abs
            if not dest_is_dir_hint:
                os.makedirs(target_base, exist_ok=True)
            for item in os.listdir(src):
                source_item = os.path.join(src, item)
                dest_item = os.path.join(target_base, item)
                if os.path.isdir(source_item):
                    shutil.copytree(source_item, dest_item, dirs_exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest_item), exist_ok=True)
                    shutil.copy2(source_item, dest_item)
        else:
            if dest_is_dir_hint:
                os.makedirs(dest_abs, exist_ok=True)
                final_dest = os.path.join(dest_abs, os.path.basename(src))
            else:
                os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
                final_dest = dest_abs
            shutil.copy2(src, final_dest)


def _run_command_in_rootfs(command, rootfs, workdir, env_map):
    shell_path = os.path.join(rootfs, "bin", "sh")
    if not os.path.exists(shell_path):
        raise FileNotFoundError(
            "RUN requires /bin/sh inside the assembled rootfs. "
            "Import a base image that includes /bin/sh (and required shared libraries)."
        )

    cmd = ["/bin/sh", "-lc", command]
    merged_env = os.environ.copy()
    for key in sorted(env_map.keys()):
        merged_env[key] = env_map[key]
    return run_isolated(
        rootfs=rootfs,
        cmd=cmd,
        env=merged_env,
        workdir=workdir or "/",
        fail_if_not_chroot=True,
    )


def _assert_runnable_shell(rootfs):
    shell_path = os.path.join(rootfs, "bin", "sh")
    if not os.path.exists(shell_path):
        raise FileNotFoundError(
            "Build requires runnable /bin/sh in the image rootfs. "
            "Import a base image that includes /bin/sh and its shared libraries."
        )

    rc = run_isolated(
        rootfs=rootfs,
        cmd=["/bin/sh", "-lc", "true"],
        env=os.environ.copy(),
        workdir="/",
        fail_if_not_chroot=True,
    )
    if rc == 125:
        raise PermissionError(
            "Build RUN requires chroot isolation. Re-run build as root (e.g. sudo) in WSL/Linux."
        )
    if rc != 0:
        raise RuntimeError(
            "Base image /bin/sh is not runnable in chroot (likely missing required shared libraries). "
            "Re-import the base image with /bin/sh dependencies."
        )


def _load_existing_created(name, tag):
    try:
        existing = load_manifest(name, tag)
        return existing.get("created")
    except FileNotFoundError:
        return None


def build_image(image_ref, context, no_cache=False):
    total_started = time.time()
    init_storage()
    if not os.path.isdir(context):
        raise FileNotFoundError(f"Build context not found: {context}")

    name, tag = _parse_image_ref(image_ref)
    docksmithfile_path = os.path.join(context, "Docksmithfile")
    if not os.path.exists(docksmithfile_path):
        raise FileNotFoundError(f"Docksmithfile not found: {docksmithfile_path}")

    instructions = parse_docksmithfile(docksmithfile_path)
    rootfs = tempfile.mkdtemp(prefix="docksmith-build-")
    cache = load_cache()
    cache_was_used = False
    cache_lookup_enabled = not no_cache
    cascade_force_miss = False

    manifest = create_manifest(name, tag)
    previous_created = _load_existing_created(name, tag)
    if previous_created:
        manifest["created"] = previous_created

    env_map = {}
    workdir = "/"
    prev_layer_digest_for_key = ""
    pending_workdir_creation = False
    first_layer_seen = False
    run_required = any(i["cmd"] == "RUN" for i in instructions)
    shell_preflight_done = False

    try:
        for index, instruction in enumerate(instructions, start=1):
            cmd = instruction["cmd"]
            value = instruction["value"]
            raw = instruction["raw"]
            line_no = instruction["line_no"]
            print(f"Step {index}/{len(instructions)} : {raw}")
            started = time.time()

            if cmd == "FROM":
                if index != 1:
                    raise ValueError(f"FROM must be the first instruction (line {line_no})")
                base_name, base_tag = _parse_image_ref(value)
                base_manifest = load_manifest(base_name, base_tag)
                _extract_manifest_layers(base_manifest, rootfs)
                manifest["layers"].extend(base_manifest.get("layers", []))
                base_cfg = base_manifest.get("config", {})
                workdir = base_cfg.get("WorkingDir", "/") or "/"
                manifest["config"]["WorkingDir"] = workdir
                for env_item in base_cfg.get("Env", []):
                    if "=" in env_item:
                        key, val = env_item.split("=", 1)
                        env_map[key] = val
                manifest["config"]["Env"] = [f"{k}={env_map[k]}" for k in sorted(env_map.keys())]
                manifest["config"]["Cmd"] = list(base_cfg.get("Cmd", []))
                prev_layer_digest_for_key = base_manifest.get("digest", "")
                print(f"Using base image {base_name}:{base_tag}")
                if run_required:
                    _assert_runnable_shell(rootfs)
                    shell_preflight_done = True
                continue

            if run_required and not shell_preflight_done:
                # Fail early before non-FROM build work if RUN exists but shell runtime is not valid.
                _assert_runnable_shell(rootfs)
                shell_preflight_done = True

            if cmd == "WORKDIR":
                workdir = value.strip() or "/"
                manifest["config"]["WorkingDir"] = workdir
                pending_workdir_creation = True
                continue

            if cmd == "ENV":
                if "=" not in value:
                    raise ValueError(f"Invalid ENV format at line {line_no}: {raw}")
                key, val = value.split("=", 1)
                env_map[key] = val
                manifest["config"]["Env"] = [f"{k}={env_map[k]}" for k in sorted(env_map.keys())]
                continue

            if cmd == "CMD":
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid CMD JSON at line {line_no}: {e}") from e
                if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
                    raise ValueError(f"CMD must be a JSON string array at line {line_no}")
                manifest["config"]["Cmd"] = parsed
                continue

            if cmd not in {"COPY", "RUN"}:
                raise ValueError(f"Unsupported instruction at line {line_no}: {raw}")

            if pending_workdir_creation:
                _ensure_workdir(rootfs, workdir)
                pending_workdir_creation = False

            copy_sources_hash = ""
            if cmd == "COPY":
                parts = value.split()
                if len(parts) != 2:
                    raise ValueError(f"Invalid COPY format at line {line_no}: {raw}")
                src_expr, _ = parts
                copy_sources_hash = _compute_copy_sources_hash(context, src_expr)

            cache_key = _compute_cache_key(
                prev_layer_digest_for_key,
                raw,
                workdir,
                env_map,
                copy_sources_hash=copy_sources_hash,
            )

            layer_digest = cache.get(cache_key) if (cache_lookup_enabled and not cascade_force_miss) else None
            can_hit = False
            if layer_digest:
                layer_tar = os.path.join(LAYERS_DIR, f"sha256_{layer_digest}.tar")
                can_hit = os.path.exists(layer_tar)

            if can_hit:
                print(f"{raw} [CACHE HIT]")
                cache_was_used = True
                layer_tar = os.path.join(LAYERS_DIR, f"sha256_{layer_digest}.tar")
                extract_layer_tar(layer_tar, rootfs)
                size = get_layer_size(layer_tar)
                add_layer(manifest, layer_digest, size, raw)
                prev_layer_digest_for_key = layer_digest
                first_layer_seen = True
                elapsed = time.time() - started
                print(f"{elapsed:.2f}s")
                continue

            print(f"{raw} [CACHE MISS]")
            cascade_force_miss = True

            before = _snapshot_files(rootfs)

            if cmd == "COPY":
                src_expr, dest_expr = value.split()
                _copy_into_rootfs(context, src_expr, dest_expr, rootfs)
            elif cmd == "RUN":
                rc = _run_command_in_rootfs(
                    command=value,
                    rootfs=rootfs,
                    workdir=workdir,
                    env_map=env_map,
                )
                if rc == 125:
                    raise PermissionError(
                        "Build RUN requires chroot isolation. Re-run build as root (e.g. sudo) in WSL/Linux."
                    )
                if rc != 0:
                    raise RuntimeError(f"RUN failed at line {line_no} with exit code {rc}: {raw}")

            after = _snapshot_files(rootfs)
            delta_abs_paths, deleted_rel_paths = _delta_file_paths(rootfs, before, after)
            temp_tar = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.tar")
            create_layer(
                delta_abs_paths,
                temp_tar,
                rootfs,
                deleted_paths=deleted_rel_paths,
            )
            layer_digest, layer_path = store_layer(temp_tar)
            size = get_layer_size(layer_path)
            add_layer(manifest, layer_digest, size, raw)

            if not no_cache:
                cache[cache_key] = layer_digest
            prev_layer_digest_for_key = layer_digest
            first_layer_seen = True
            elapsed = time.time() - started
            print(f"{elapsed:.2f}s")

        if not no_cache:
            save_cache(cache)

        if cache_was_used and not cascade_force_miss and first_layer_seen and previous_created:
            manifest["created"] = previous_created

        compute_manifest_digest(manifest)
        save_manifest(manifest)
        total_elapsed = time.time() - total_started
        print(
            f"\nSuccessfully built {manifest['digest']} {name}:{tag} ({total_elapsed:.2f}s)"
        )
    finally:
        shutil.rmtree(rootfs, ignore_errors=True)
