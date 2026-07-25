#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "run as root: install_host.sh WHEEL CURSOR_TOKEN_FILE" >&2
  exit 1
fi
if [[ $# -ne 2 ]]; then
  echo "usage: install_host.sh WHEEL CURSOR_TOKEN_FILE" >&2
  exit 1
fi

wheel=$(realpath "$1")
cursor_token=$(realpath "$2")
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
vm_host=${EZDXF_VM_HOST:?set EZDXF_VM_HOST to the VM hostname}
vm_ip=${EZDXF_VM_IP:?set EZDXF_VM_IP to the VM IP address}
vm_host_key_sha256=${EZDXF_VM_HOST_KEY_SHA256:?set the trusted VM SSH host-key fingerprint}
desktop_user=${EZDXF_DESKTOP_USER:-${SUDO_USER:-}}
x11_display=${EZDXF_X11_DISPLAY:-:0}

test -f "$wheel"
test -f "$cursor_token"
test "$(stat -c %a "$cursor_token")" = "600"
if [[ -z "$desktop_user" || "$desktop_user" == "root" ]]; then
  echo "set EZDXF_DESKTOP_USER to the unprivileged X11 desktop user" >&2
  exit 1
fi
if ! id "$desktop_user" >/dev/null 2>&1; then
  echo "desktop user does not exist: $desktop_user" >&2
  exit 1
fi
desktop_group=$(id -gn "$desktop_user")
desktop_uid=$(id -u "$desktop_user")
xauthority=${EZDXF_XAUTHORITY:-/run/user/$desktop_uid/gdm/Xauthority}

if ! getent passwd ezdxf-tunnel >/dev/null; then
  useradd \
    --system \
    --home-dir /var/lib/ezdxf-tunnel \
    --create-home \
    --shell /usr/sbin/nologin \
    ezdxf-tunnel
fi

install -d -m 0755 -o root -g root /opt/ezdxf-cursor-bridge
install -d -m 0750 -o root -g "$desktop_group" /etc/ezdxf-cursor-bridge
install \
  -m 0600 \
  -o "$desktop_user" \
  -g "$desktop_group" \
  "$cursor_token" \
  /etc/ezdxf-cursor-bridge/token

if [[ ! -x /opt/ezdxf-cursor-bridge/venv/bin/python ]]; then
  python3 -m venv /opt/ezdxf-cursor-bridge/venv
fi
/opt/ezdxf-cursor-bridge/venv/bin/pip install --no-cache-dir --upgrade "$wheel"
/opt/ezdxf-cursor-bridge/venv/bin/pip install \
  --no-cache-dir \
  --force-reinstall \
  --no-deps \
  "$wheel"

install -d -m 0700 -o ezdxf-tunnel -g ezdxf-tunnel /var/lib/ezdxf-tunnel/.ssh
if [[ ! -f /var/lib/ezdxf-tunnel/.ssh/id_ed25519 ]]; then
  runuser -u ezdxf-tunnel -- \
    ssh-keygen -q -t ed25519 -N "" -f /var/lib/ezdxf-tunnel/.ssh/id_ed25519
fi
host_key_scan=$(mktemp)
verified_host_keys=$(mktemp)
cursor_unit=$(mktemp)
tunnel_unit=$(mktemp)
ssh_config=$(mktemp)
trap \
  'rm -f "$host_key_scan" "$verified_host_keys" "$cursor_unit" "$tunnel_unit" "$ssh_config"' \
  EXIT

ssh-keyscan -T 10 -H "$vm_host" > "$host_key_scan" 2>/dev/null
while IFS= read -r host_key; do
  fingerprint=$(
    printf '%s\n' "$host_key" |
      ssh-keygen -lf - -E sha256 |
      awk '{print $2}'
  )
  if [[ "$fingerprint" == "$vm_host_key_sha256" ]]; then
    printf '%s\n' "$host_key" >> "$verified_host_keys"
  fi
done < "$host_key_scan"
if [[ ! -s "$verified_host_keys" ]]; then
  echo "VM SSH host-key fingerprint did not match the trusted value" >&2
  exit 1
fi
install \
  -m 0600 \
  -o ezdxf-tunnel \
  -g ezdxf-tunnel \
  "$verified_host_keys" \
  /var/lib/ezdxf-tunnel/.ssh/known_hosts

sed \
  -e "s|__EZDXF_DESKTOP_USER__|$desktop_user|g" \
  -e "s|__EZDXF_DESKTOP_GROUP__|$desktop_group|g" \
  -e "s|__EZDXF_X11_DISPLAY__|$x11_display|g" \
  -e "s|__EZDXF_XAUTHORITY__|$xauthority|g" \
  "$source_dir/systemd/ezdxf-cursor-bridge.service" \
  > "$cursor_unit"
sed \
  -e "s|203\\.0\\.113\\.10|$vm_ip|g" \
  "$source_dir/systemd/ezdxf-api-tunnel.service" \
  > "$tunnel_unit"
sed \
  -e "s|vm\\.example\\.com|$vm_host|g" \
  "$source_dir/ssh/ezdxf-api-tunnel.conf" \
  > "$ssh_config"

install \
  -m 0644 \
  -o root \
  -g root \
  "$cursor_unit" \
  /etc/systemd/system/ezdxf-cursor-bridge.service
install \
  -m 0644 \
  -o root \
  -g root \
  "$tunnel_unit" \
  /etc/systemd/system/ezdxf-api-tunnel.service
install \
  -m 0644 \
  -o root \
  -g root \
  "$ssh_config" \
  /etc/ezdxf-api-tunnel.conf

systemctl daemon-reload
systemctl enable --now ezdxf-cursor-bridge.service
systemctl is-active --quiet ezdxf-cursor-bridge.service

echo "host bridge installed"
echo "public key: /var/lib/ezdxf-tunnel/.ssh/id_ed25519.pub"
echo "after VM installation: systemctl enable --now ezdxf-api-tunnel.service"
