# Reference Deployment

The deployment templates build a loopback-only API on a remote Linux VM and a
restricted pointer bridge on an X11 desktop. They do not print token values.

Review every template before using it. The installer changes system users,
systemd units, SSH configuration, and packages.

## Prerequisites

- a wheel built from this repository;
- two independent random token files with mode `0600`;
- root access on both systems;
- an X11 desktop with `xdotool`;
- a VM reachable by SSH;
- firewall policy that permits SSH only from expected sources.

Example token creation:

```bash
umask 077
python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > api.token
python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > cursor.token
chmod 600 api.token cursor.token
```

Never create token files inside the repository.

## Install the graphical host

Set deployment-specific values explicitly:

```bash
export EZDXF_VM_HOST=vm.example.com
export EZDXF_VM_IP=203.0.113.10
export EZDXF_DESKTOP_USER=desktop-user
export EZDXF_X11_DISPLAY=:0
export EZDXF_XAUTHORITY=/run/user/1000/gdm/Xauthority

sudo --preserve-env=EZDXF_VM_HOST,EZDXF_VM_IP,EZDXF_DESKTOP_USER,EZDXF_X11_DISPLAY,EZDXF_XAUTHORITY \
  ./deploy/install_host.sh \
  dist/ezdxf_mcp-3.2.1-py3-none-any.whl \
  /secure/path/cursor.token
```

The installer creates the restricted cursor service, a dedicated tunnel user,
an Ed25519 key, a strict known-hosts file, and deployment-specific copies of
the systemd/SSH templates.

The public key is placed at:

```text
/var/lib/ezdxf-tunnel/.ssh/id_ed25519.pub
```

Verify `EZDXF_XAUTHORITY` against the active graphical session before starting
the cursor service.

## Install the VM

Copy the wheel, `deploy/` directory, both token files, and the tunnel public
key to a root-only staging directory on the VM. Then run:

```bash
sudo ./deploy/install_vm.sh \
  ezdxf_mcp-3.2.1-py3-none-any.whl \
  api.token \
  cursor.token \
  id_ed25519.pub
```

The installer:

- installs Python venv and Tesseract English/Portuguese packages;
- creates `ezdxf-api` and `ezdxf-tunnel` system users without shells;
- installs the API under `/opt/ezdxf-api`;
- stores isolated jobs under `/var/lib/ezdxf-api`;
- restricts the SSH account to the two loopback forwards;
- validates SSH configuration before reload;
- enables the loopback API service.

Install additional Tesseract language packs when required.

## Start the tunnel

On the graphical host:

```bash
sudo systemctl enable --now ezdxf-api-tunnel.service
curl --noproxy '*' --fail http://127.0.0.1:8766/health
```

Confirm that neither the API port nor the reverse cursor port is publicly
reachable.

## Rollback

Host:

```bash
sudo systemctl disable --now ezdxf-api-tunnel.service
sudo systemctl disable --now ezdxf-cursor-bridge.service
```

VM:

```bash
sudo systemctl disable --now ezdxf-api.service
```

This stops the capability without deleting jobs, credentials, keys, packages,
or artifacts. Remove persistent state only as a separate, reviewed operation.
