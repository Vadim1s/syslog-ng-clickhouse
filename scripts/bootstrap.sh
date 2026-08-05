#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' 'bootstrap.sh supports Debian/Ubuntu controllers. Install Python 3.12+, venv, pip, and OpenSSH client manually on other distributions.' >&2
    exit 1
fi

sudo env DEBIAN_FRONTEND=noninteractive apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv openssh-client

python3 - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit(f"Python 3.12+ is required on the control node; found {sys.version.split()[0]}")
PY

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install 'ansible-core>=2.20,<2.22'
.venv/bin/ansible-galaxy collection install -r requirements.yml

if [[ ! -f inventory/hosts.yml ]]; then
    install -m 0600 inventory/example.yml inventory/hosts.yml
    printf '%s\n' 'Created inventory/hosts.yml; replace example addresses before deployment.'
fi

if [[ ! -f group_vars/all/vault.yml ]]; then
    install -m 0600 group_vars/all/vault.yml.example group_vars/all/vault.yml
    printf '%s\n' 'Created group_vars/all/vault.yml; set a strong password and encrypt the file.'
fi

.venv/bin/python scripts/static_check.py

printf '%s\n' 'Bootstrap completed.'
printf '%s\n' 'Next: edit inventory/hosts.yml and group_vars/all/vault.yml.'
printf '%s\n' 'Then run: .venv/bin/ansible-vault encrypt group_vars/all/vault.yml'
printf '%s\n' 'And: .venv/bin/ansible-playbook site.yml --ask-vault-pass'
