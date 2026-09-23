import argparse
import shlex
import sys

from builder.build_engine import build_image
from image.layer_system import list_images, remove_image
from runtime.container import run_container
from runtime.container_manager import list_containers


def _validate_image_ref(image):
    if ":" not in image:
        raise ValueError("Image must be in format name:tag")
    name, tag = image.split(":", 1)
    if not name.strip() or not tag.strip():
        raise ValueError("Image must be in format name:tag")


def interactive_shell():
    print("Docksmith Interactive CLI")
    print("Type 'exit' to quit\n")

    while True:
        raw = input("docksmith> ").strip()
        if raw == "exit":
            break
        if not raw:
            continue

        parts = shlex.split(raw)
        command = parts[0]

        try:
            if command == "build":
                no_cache = "--no-cache" in parts
                parts = [p for p in parts if p != "--no-cache"]
                if len(parts) != 4 or parts[1] not in {"-t", "--tag"}:
                    raise ValueError("Usage: build -t name:tag <context> [--no-cache]")
                build_image(parts[2], parts[3], no_cache=no_cache)

            elif command == "images":
                list_images()

            elif command == "rmi":
                if len(parts) != 2:
                    raise ValueError("Usage: rmi <name:tag>")
                _validate_image_ref(parts[1])
                name, tag = parts[1].split(":", 1)
                remove_image(name, tag)

            elif command == "run":
                if len(parts) < 2:
                    raise ValueError("Usage: run <image:tag> [-e KEY=VALUE] [cmd...]")
                env_overrides = []
                image = None
                cmd_override = []
                i = 1
                while i < len(parts):
                    part = parts[i]
                    if part == "-e":
                        if i + 1 >= len(parts):
                            raise ValueError("Usage: -e KEY=VALUE")
                        env_overrides.append(parts[i + 1])
                        i += 2
                        continue
                    if image is None:
                        image = part
                    else:
                        cmd_override.append(part)
                    i += 1

                _validate_image_ref(image)
                run_container(
                    image,
                    cmd_override=cmd_override or None,
                    env_overrides=env_overrides,
                )

            elif command == "ps":
                list_containers()

            else:
                print(f"Unknown command: {command}")
                print("Try: build, run, images, rmi, ps")
        except Exception as e:
            print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(prog="docksmith")
    subparsers = parser.add_subparsers(dest="command")

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("-t", "--tag", required=True)
    build_parser.add_argument("context")
    build_parser.add_argument("--no-cache", action="store_true")

    subparsers.add_parser("images")

    rmi_parser = subparsers.add_parser("rmi")
    rmi_parser.add_argument("image")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("-e", "--env", action="append", default=[], dest="envs")
    run_parser.add_argument("image")
    run_parser.add_argument("cmd", nargs=argparse.REMAINDER)

    subparsers.add_parser("ps")

    args = parser.parse_args()

    try:
        if args.command == "build":
            _validate_image_ref(args.tag)
            build_image(
                args.tag,
                args.context,
                no_cache=args.no_cache,
            )
        elif args.command == "images":
            list_images()
        elif args.command == "rmi":
            _validate_image_ref(args.image)
            name, tag = args.image.split(":", 1)
            remove_image(name, tag)
        elif args.command == "run":
            _validate_image_ref(args.image)
            cmd_override = args.cmd if args.cmd else None
            rc = run_container(
                args.image,
                cmd_override=cmd_override,
                env_overrides=args.envs,
            )
            raise SystemExit(rc)
        elif args.command == "ps":
            list_containers()
        else:
            parser.print_help()
    except Exception as e:
        print(f"Error: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        interactive_shell()
