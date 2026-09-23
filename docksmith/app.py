import json
import os

import streamlit as st

from builder.build_engine import build_image
from image.layer_system import IMAGES_DIR, init_storage, load_manifest, remove_image
from runtime.container import run_container
from runtime.container_manager import load_containers, stop_container

st.set_page_config(page_title="Docksmith UI", layout="wide")

st.title("Docksmith Container System")

# Sidebar
st.sidebar.header("Actions")
option = st.sidebar.selectbox(
    "Choose Action",
    [
        "Build Image",
        "Run Container",
        "View Images",
        "Inspect Image",
        "Remove Image",
        "View Containers",
        "Stop Container",
        "Initialize Storage",
    ]
)


def is_valid_image_ref(value):
    if ":" not in value:
        return False
    name, tag = value.split(":", 1)
    return bool(name.strip()) and bool(tag.strip())


def load_image_manifests():
    manifests = []
    if not os.path.exists(IMAGES_DIR):
        return manifests

    for file in os.listdir(IMAGES_DIR):
        if not file.endswith(".json"):
            continue
        path = os.path.join(IMAGES_DIR, file)
        with open(path) as f:
            data = json.load(f)
        manifests.append(data)

    manifests.sort(key=lambda x: x.get("created", ""), reverse=True)
    return manifests

# -----------------------
# BUILD IMAGE
# -----------------------
if option == "Build Image":
    st.header("Build Image")

    tag = st.text_input("Image Tag (name:tag)", "myapp:latest")
    context = st.text_input("Build Context", "sample-app")
    no_cache = st.checkbox("Disable cache (--no-cache)", value=False)
    st.caption("Build RUN uses mandatory chroot isolation. Run Streamlit with sudo in WSL/Linux.")

    if st.button("Build"):
        if not is_valid_image_ref(tag):
            st.error("Image tag must be in format name:tag")
        elif not os.path.isdir(context):
            st.error(f"Build context not found: {context}")
        elif not os.path.exists(os.path.join(context, "Docksmithfile")):
            st.error(f"Docksmithfile not found in context: {context}")
        else:
            try:
                with st.spinner("Building image..."):
                    build_image(
                        tag,
                        context,
                        no_cache=no_cache,
                    )
                st.success(f"Build complete: {tag}")
            except Exception as e:
                st.error(f"Build failed: {e}")

# -----------------------
# RUN CONTAINER
# -----------------------
elif option == "Run Container":
    st.header("Run Container")

    image = st.text_input("Image name:tag", "myapp:latest")
    env_overrides = st.text_area(
        "Environment overrides (one KEY=VALUE per line, optional)",
        value="",
    )
    cmd_override_raw = st.text_input(
        "Command override (space-separated, optional)",
        value="",
    )
    st.caption("Container run uses mandatory chroot isolation. Run Streamlit with sudo in WSL/Linux.")

    if st.button("Run"):
        if not is_valid_image_ref(image):
            st.error("Image name must be in format name:tag")
        else:
            try:
                with st.spinner("Running container..."):
                    env_list = [
                        line.strip()
                        for line in env_overrides.splitlines()
                        if line.strip()
                    ]
                    cmd_override = cmd_override_raw.split() if cmd_override_raw.strip() else None
                    run_container(
                        image,
                        cmd_override=cmd_override,
                        env_overrides=env_list,
                    )
                st.success("Container finished")
            except FileNotFoundError:
                st.error(f"Image not found: {image}")
            except Exception as e:
                st.error(f"Run failed: {e}")

# -----------------------
# VIEW IMAGES
# -----------------------
elif option == "View Images":
    st.header("Images")

    manifests = load_image_manifests()
    if manifests:
        rows = []
        for data in manifests:
            rows.append(
                {
                    "name": data.get("name", ""),
                    "tag": data.get("tag", ""),
                    "digest": data.get("digest", "")[:19],
                    "layers": len(data.get("layers", [])),
                    "created": data.get("created", ""),
                }
            )
        st.table(rows)
    else:
        st.write("No images found")

# -----------------------
# VIEW CONTAINERS
# -----------------------
elif option == "View Containers":
    st.header("Containers")

    data = load_containers()
    if data:
        st.table(data)
    else:
        st.write("No containers found")

# -----------------------
# INSPECT IMAGE
# -----------------------
elif option == "Inspect Image":
    st.header("Inspect Image")
    image = st.text_input("Image name:tag", "myapp:latest")

    if st.button("Inspect"):
        if not is_valid_image_ref(image):
            st.error("Image name must be in format name:tag")
        else:
            name, tag = image.split(":", 1)
            try:
                manifest = load_manifest(name, tag)
                st.json(manifest)
            except FileNotFoundError:
                st.error(f"Image not found: {image}")
            except Exception as e:
                st.error(f"Inspect failed: {e}")

# -----------------------
# REMOVE IMAGE
# -----------------------
elif option == "Remove Image":
    st.header("Remove Image")
    image = st.text_input("Image name:tag", "myapp:latest")

    if st.button("Remove"):
        if not is_valid_image_ref(image):
            st.error("Image name must be in format name:tag")
        else:
            name, tag = image.split(":", 1)
            try:
                remove_image(name, tag)
                st.success(f"Removed image: {image}")
            except FileNotFoundError:
                st.error(f"Image not found: {image}")
            except Exception as e:
                st.error(f"Failed to remove image: {e}")

# -----------------------
# STOP CONTAINER
# -----------------------
elif option == "Stop Container":
    st.header("Stop Container")
    cid = st.text_input("Container ID", "")

    if st.button("Stop"):
        if not cid.strip():
            st.error("Container ID is required")
        else:
            containers = load_containers()
            existing = next((c for c in containers if c.get("id") == cid.strip()), None)
            if not existing:
                st.error(f"Container not found: {cid}")
            else:
                stop_container(cid.strip())
                st.success(f"Container stopped: {cid}")

# -----------------------
# INITIALIZE STORAGE
# -----------------------
elif option == "Initialize Storage":
    st.header("Initialize Storage")
    st.write("Create Docksmith storage directories under ~/.docksmith")

    if st.button("Initialize"):
        try:
            init_storage()
            st.success("Storage initialized")
        except Exception as e:
            st.error(f"Initialization failed: {e}")
