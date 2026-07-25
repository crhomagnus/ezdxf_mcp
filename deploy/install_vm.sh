#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "run as root: install_vm.sh WHEEL API_TOKEN CURSOR_TOKEN PUBLIC_KEY" >&2
  exit 1
fi
if [[ $# -ne 4 ]]; then
  echo "usage: install_vm.sh WHEEL API_TOKEN CURSOR_TOKEN PUBLIC_KEY" >&2
  exit 1
fi

wheel=$(realpath "$1")
api_token=$(realpath "$2")
cursor_token=$(realpath "$3")
public_key=$(realpath "$4")
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

for required in "$wheel" "$api_token" "$cursor_token" "$public_key"; do
  test -f "$required"
done
test "$(stat -c %a "$api_token")" = "600"
test "$(stat -c %a "$cursor_token")" = "600"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  python3-venv \
  tesseract-ocr \
  tesseract-ocr-eng \
  tesseract-ocr-por

if ! getent passwd ezdxf-api >/dev/null; then
  useradd \
    --system \
    --home-dir /var/lib/ezdxf-api \
    --create-home \
    --shell /usr/sbin/nologin \
    ezdxf-api
fi
if ! getent passwd ezdxf-tunnel >/dev/null; then
  useradd \
    --system \
    --home-dir /nonexistent \
    --no-create-home \
    --shell /usr/sbin/nologin \
    ezdxf-tunnel
fi

install -d -m 0755 -o root -g root /opt/ezdxf-api
install -d -m 0700 -o ezdxf-api -g ezdxf-api /var/lib/ezdxf-api
install -d -m 0750 -o root -g ezdxf-api /etc/ezdxf-api
install -m 0600 -o ezdxf-api -g ezdxf-api "$api_token" /etc/ezdxf-api/api-token
install -m 0600 -o ezdxf-api -g ezdxf-api "$cursor_token" /etc/ezdxf-api/cursor-token

if [[ ! -x /opt/ezdxf-api/venv/bin/python ]]; then
  python3 -m venv /opt/ezdxf-api/venv
fi
/opt/ezdxf-api/venv/bin/pip install \
  --no-cache-dir \
  --upgrade \
  "$wheel[api,image]"
/opt/ezdxf-api/venv/bin/pip install \
  --no-cache-dir \
  --force-reinstall \
  --no-deps \
  "$wheel"

install -d -m 0711 -o root -g root /etc/ssh/authorized_keys
key_value=$(<"$public_key")
printf \
  'restrict,port-forwarding,permitopen="127.0.0.1:8766",permitlisten="127.0.0.1:3472" %s\n' \
  "$key_value" \
  > /etc/ssh/authorized_keys/ezdxf-tunnel
chmod 0644 /etc/ssh/authorized_keys/ezdxf-tunnel
chown root:root /etc/ssh/authorized_keys/ezdxf-tunnel

install -m 0644 -o root -g root \
  "$source_dir/ssh/sshd-ezdxf-tunnel.conf" \
  /etc/ssh/sshd_config.d/91-ezdxf-tunnel.conf
sshd -t
systemctl reload ssh.service

install -m 0644 -o root -g root \
  "$source_dir/systemd/ezdxf-api.service" \
  /etc/systemd/system/ezdxf-api.service
systemctl daemon-reload
systemctl enable --now ezdxf-api.service
systemctl is-active --quiet ezdxf-api.service
curl --noproxy "*" --fail --silent --show-error http://127.0.0.1:8766/health
echo
echo "VM API installed"
