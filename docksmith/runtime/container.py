import os
import shutil
import tempfile

from image.layer_system import LAYERS_DIR, extract_layer_tar, load_manifest
from runtime.container_manager import add_container, stop_container
from runtime.isolation import run_isolated


def extract_layer(layer_digest, rootfs):
    digest = layer_digest.replace("sha256:", "")
    tar_path = os.path.join(LAYERS_DIR, f"sha256_{digest}.tar")
    if not os.path.exists(tar_path):
        raise FileNotFoundError(f"Layer file missing: {tar_path}")
    extract_layer_tar(tar_path, rootfs)


def build_rootfs(manifest):
    rootfs = tempfile.mkdtemp(prefix="docksmith-run-")
    for layer in manifest.get("layers", []):
        extract_layer(layer["digest"], rootfs)
    return rootfs


def _parse_env_overrides(env_overrides):
    parsed = {}
    for item in env_overrides or []:
        if "=" not in item:
            raise ValueError(f"Invalid env override format: {item}. Expected KEY=VALUE")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError(f"Invalid env override key: {item}")
        parsed[key] = value
    return parsed


def _build_env(image_env_list, env_overrides):
    merged = os.environ.copy()
    for item in image_env_list:
        if "=" in item:
            key, value = item.split("=", 1)
            merged[key] = value
    for key, value in _parse_env_overrides(env_overrides).items():
        merged[key] = value
    return merged


def run_container(image, cmd_override=None, env_overrides=None):
    name, tag = image.split(":")
    manifest = load_manifest(name, tag)

    image_cmd = manifest.get("config", {}).get("Cmd", [])
    effective_cmd = list(cmd_override) if cmd_override else list(image_cmd)
    if not effective_cmd:
        raise ValueError(
            "No command to run. Image has no CMD and no runtime command override was provided."
        )

    workdir = manifest.get("config", {}).get("WorkingDir", "/") or "/"
    env_list = manifest.get("config", {}).get("Env", [])
    env = _build_env(env_list, env_overrides or [])
    rootfs = build_rootfs(manifest)

    if effective_cmd and effective_cmd[0] == "/bin/sh":
        shell_path = os.path.join(rootfs, "bin", "sh")
        if not os.path.exists(shell_path):
            raise FileNotFoundError(
                "Container command requires /bin/sh inside image rootfs. "
                "Import a base image that includes /bin/sh (and required shared libraries)."
            )

    cid = add_container(image)
    print(f"\nRunning container: {image}")
    print(f"Container ID: {cid}")

    try:
        rc = run_isolated(
            rootfs=rootfs,
            cmd=effective_cmd,
            env=env,
            workdir=workdir,
            fail_if_not_chroot=True,
        )
        if rc == 125:
            raise PermissionError(
                "Container run requires chroot isolation. Re-run as root (e.g. sudo) in WSL/Linux."
            )
        print(f"Container exited with code {rc}")
        return rc
    finally:
        stop_container(cid)
        shutil.rmtree(rootfs, ignore_errors=True)
