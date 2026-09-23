import os
import json
import uuid

CONTAINER_FILE = os.path.expanduser("~/.docksmith/containers.json")


def load_containers():
    if not os.path.exists(CONTAINER_FILE):
        return []
    with open(CONTAINER_FILE) as f:
        return json.load(f)


def save_containers(containers):
    os.makedirs(os.path.dirname(CONTAINER_FILE), exist_ok=True)
    with open(CONTAINER_FILE, "w") as f:
        json.dump(containers, f, indent=2)


def add_container(image):
    containers = load_containers()

    cid = str(uuid.uuid4())[:8]

    containers.append({
        "id": cid,
        "image": image,
        "status": "running"
    })

    save_containers(containers)
    return cid


def stop_container(cid):
    containers = load_containers()

    for c in containers:
        if c["id"] == cid:
            c["status"] = "stopped"

    save_containers(containers)


def list_containers():
    containers = load_containers()

    if not containers:
        print("No containers found")
        return

    print("CONTAINER ID   IMAGE          STATUS")
    for c in containers:
        print(f"{c['id']}   {c['image']}   {c['status']}")