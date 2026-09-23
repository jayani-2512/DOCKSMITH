import os
import subprocess
import sys


def run_isolated(rootfs, cmd, env, workdir="/", fail_if_not_chroot=False):
    """
    Shared process-isolation primitive for both build RUN and runtime run.
    Uses chroot when possible (requires root). Falls back to rootfs cwd when not root.
    """
    child = os.fork()
    if child == 0:
        try:
            target_workdir = workdir or "/"
            used_chroot = False

            if os.geteuid() == 0:
                os.chroot(rootfs)
                os.chdir(target_workdir)
                used_chroot = True
            else:
                if fail_if_not_chroot:
                    print("Docksmith isolation requires root privileges for chroot.", file=sys.stderr)
                    os._exit(125)
                host_cwd = os.path.join(rootfs, target_workdir.lstrip("/"))
                os.makedirs(host_cwd, exist_ok=True)
                os.chdir(host_cwd)

            if cmd and cmd[0] == "python3":
                cmd[0] = sys.executable

            completed = subprocess.run(cmd, env=env, cwd=None if used_chroot else os.getcwd())
            os._exit(completed.returncode)
        except Exception as e:
            print(f"Isolation error: {e}", file=sys.stderr)
            os._exit(126)

    _, status = os.waitpid(child, 0)
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    return 1
