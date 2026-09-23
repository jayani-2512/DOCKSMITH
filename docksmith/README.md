# Docksmith (WSL + Frontend Runbook)

Docksmith must be run in a Linux environment (WSL2 on Windows is fine).  
This README gives exact terminal commands and the frontend UI flow.

## 1. Open WSL and enter project

```bash
cd /mnt/c/Users/User/Downloads/'docksmith (4)'/docksmith
```

## 2. Create and activate virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install streamlit
```

## 3. Initialize Docksmith storage

```bash
mkdir -p ~/.docksmith/images ~/.docksmith/layers ~/.docksmith/cache
```

## 4. Add local base image for FROM (offline prerequisite)

Your sample `Docksmithfile` uses:

```text
FROM base-shell:latest
```

Import a minimal shell base image once (offline after this step):

```bash
chmod +x scripts/setup_base_shell.sh
./scripts/setup_base_shell.sh
```

## 5. Run backend tests (optional sanity check)

```bash
python3 test_layer_system.py
python3 test.py
```

## 6. WSL Terminal Workflow (CLI)

Cold build (reset cache/image first, then build):

```bash
rm -f ~/.docksmith/cache/index.json
rm -f ~/.docksmith/images/myapp_latest.json
```

```bash
sudo -E python3 docksmith.py build -t myapp:latest sample-app
```

Warm build (run again without resetting anything):

```bash
sudo -E python3 docksmith.py build -t myapp:latest sample-app
```

No-cache build:

```bash
sudo -E python3 docksmith.py build --no-cache -t myapp:latest sample-app
```

List images:

```bash
python3 docksmith.py images
```

Run container (image CMD):

```bash
sudo -E python3 docksmith.py run myapp:latest
```

Run with env override:

```bash
sudo -E python3 docksmith.py run -e GREETING=Hi myapp:latest
```

Run with command override:

```bash
sudo -E python3 docksmith.py run myapp:latest /bin/sh -lc 'echo "override-run"'
```

List containers:

```bash
python3 docksmith.py ps
```

Remove image:

```bash
python3 docksmith.py rmi myapp:latest
```

## 7. Frontend Workflow (Streamlit in WSL)

Start UI:

```bash
sudo -E streamlit run app.py
```

Open the URL shown in terminal (usually `http://localhost:8501`).

Use the same prerequisites from sections 1-4 before opening the UI.

### UI flow (recommended order)

1. `Initialize Storage`
2. `Build Image`
   - Image tag: `myapp:latest`
   - Build context: `sample-app`
   - Optional: enable `Disable cache (--no-cache)`
3. `View Images`
4. `Inspect Image` (`myapp:latest`)
5. `Run Container`
   - Optional env overrides: one `KEY=VALUE` per line
   - Optional command override: space-separated command
6. `View Containers`
7. `Stop Container` (logical stop record update)
8. `Remove Image`

Build and run actions in the UI require chroot isolation, so run Streamlit with `sudo -E`.

## 8. Frontend to backend mapping

- `Build Image` -> `build_image(..., no_cache=...)`
- `Run Container` -> `run_container(..., cmd_override=..., env_overrides=...)`
- `View Images` -> reads manifests from `~/.docksmith/images`
- `Inspect Image` -> `load_manifest(...)`
- `Remove Image` -> `remove_image(...)`
- `View Containers` -> `load_containers()`
- `Stop Container` -> `stop_container(...)`
- `Initialize Storage` -> `init_storage()`

## 9. Important notes

- Run everything in WSL/Linux, not native Windows Python.
- `FROM` must reference a local image manifest already present in `~/.docksmith/images`.
- No network pulls are done during `build` or `run`.
- Docksmith now enforces chroot isolation for `RUN` during build and `docksmith run` at runtime.

## 10. Troubleshooting (/bin/sh issue)

If build/run fails with an error related to `/bin/sh`, your base image rootfs is missing:

- `/bin/sh` binary
- one or more shared libraries needed by that binary

Fix by re-running the base-image import steps in section 4 (they copy `/bin/sh`, `/bin/cat`, and dependent libs via `ldd`).
