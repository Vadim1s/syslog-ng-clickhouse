#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import yaml
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = {
    "apt-key": re.compile(r"\bapt-key\b"),
    "root SSH login": re.compile(r"PermitRootLogin\s+yes", re.I),
    "SHA-1 SSH MAC": re.compile(r"hmac-sha1", re.I),
    "ssh-copy-id automation": re.compile(r"\bssh-copy-id\b"),
    "deprecated bare include": re.compile(r"^\s*-?\s*include:\s", re.M),
    "unverified binary download": re.compile(r"github\.com/.+/releases/download[\s\S]{0,400}?get_url:[\s\S]{0,400}?(?!checksum:)", re.I),
}

EXCLUDED = {
    ROOT / "AUDIT.md",
    ROOT / "README.md",
    ROOT / "TEST_REPORT.md",
    ROOT / "MIGRATION.md",
    Path(__file__).resolve(),
}

SAMPLE_CONTEXT = {
    "inventory_hostname": "log01",
    "groups": {"syslog_servers": ["log01"], "syslog_clients": ["client01"]},
    "hostvars": {
        "log01": {"ansible_host": "10.0.2.20", "prometheus_target_address": "10.0.2.20"},
        "client01": {"ansible_host": "10.0.2.21", "prometheus_target_address": "10.0.2.21"},
    },
    "syslog_ng_repository_url": "https://ose-repo.syslog-ng.com/apt",
    "syslog_ng_repository_component": "debian-bookworm",
    "syslog_ng_deb_architecture": "amd64",
    "syslog_tls_port": 6514,
    "syslog_tls_directory": "/etc/syslog-ng/tls",
    "syslog_local_file": "/var/log/syslog",
    "syslog_disk_buffer_bytes": 1073741824,
    "syslog_memory_buffer_bytes": 134217728,
    "syslog_batch_lines": 500,
    "syslog_batch_bytes": 8388608,
    "syslog_batch_timeout_ms": 1000,
    "syslog_http_workers": 4,
    "syslog_server_address": "10.0.2.20",
    "syslog_metrics_bind_address_resolved": "10.0.2.20",
    "syslog_metrics_port": 9577,
    "syslog_metrics_scrape_frequency_limit": 10,
    "clickhouse_http_host": "127.0.0.1",
    "clickhouse_http_port": 8123,
    "clickhouse_native_port": 9000,
    "clickhouse_metrics_port": 9363,
    "clickhouse_database": "syslog",
    "clickhouse_table": "events",
    "clickhouse_ingest_user": "syslog_ingest",
    "clickhouse_ingest_password": "A234567890bcdefghijkLMNO_pqrstuv",
    "clickhouse_retention_days": 90,
    "clickhouse_repository_url": "https://packages.clickhouse.com/deb",
    "clickhouse_repository_channel": "lts",
    "clickhouse_deb_architecture": "amd64",
    "node_exporter_install_dir": "/usr/local/bin",
    "node_exporter_bind_address_resolved": "10.0.2.20",
    "node_exporter_port": 9100,
    "node_exporter_textfile_dir": "/var/lib/node_exporter/textfile_collector",
    "prometheus_install_dir": "/usr/local/bin",
    "prometheus_config_dir": "/etc/prometheus",
    "prometheus_data_dir": "/var/lib/prometheus",
    "prometheus_web_listen_address": "127.0.0.1",
    "prometheus_web_port": 9090,
    "prometheus_scrape_interval": "15s",
    "prometheus_evaluation_interval": "15s",
    "prometheus_retention_time": "30d",
    "prometheus_retention_size": "0B",
}


def is_encrypted_vault(text: str) -> bool:
    return text.lstrip().startswith("$ANSIBLE_VAULT;")


def main() -> int:
    errors: list[str] = []

    yaml_paths = sorted(ROOT.rglob("*.yml")) + sorted(ROOT.rglob("*.yaml"))
    for path in yaml_paths:
        if ".venv" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if is_encrypted_vault(text):
            continue
        try:
            list(yaml.safe_load_all(text))
        except Exception as exc:
            errors.append(f"YAML parse error in {path.relative_to(ROOT)}: {exc}")

    environment = Environment(undefined=StrictUndefined, autoescape=False)
    for path in sorted(ROOT.rglob("*.j2")):
        text = path.read_text(encoding="utf-8")
        try:
            template = environment.from_string(text)
            rendered = template.render(**SAMPLE_CONTEXT)
            unresolved = rendered
            if path.name == "alerts.yml.j2":
                unresolved = re.sub(r"\{\{\s*\$labels\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}", "", unresolved)
            if "{{" in unresolved or "{%" in unresolved:
                errors.append(f"Unrendered Jinja expression in {path.relative_to(ROOT)}")
            if path.name.endswith((".yml.j2", ".yaml.j2")):
                try:
                    list(yaml.safe_load_all(rendered))
                except Exception as exc:
                    errors.append(f"Rendered YAML error in {path.relative_to(ROOT)}: {exc}")
            if path.name.endswith(".xml.j2"):
                try:
                    ET.fromstring(rendered)
                except Exception as exc:
                    errors.append(f"Rendered XML error in {path.relative_to(ROOT)}: {exc}")
        except (TemplateSyntaxError, Exception) as exc:
            errors.append(f"Jinja render error in {path.relative_to(ROOT)}: {exc}")

    for path in sorted(ROOT.rglob("*.sh")):
        result = subprocess.run(
            ["bash", "-n", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(f"Shell syntax error in {path.relative_to(ROOT)}: {result.stderr.strip()}")

    for path in ROOT.rglob("*"):
        if not path.is_file() or path in EXCLUDED or ".venv" in path.parts:
            continue
        if path.suffix.lower() not in {".yml", ".yaml", ".j2", ".sh", ".py", ".md", ".cfg"}:
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN.items():
            if label == "unverified binary download":
                continue
            if pattern.search(text):
                errors.append(f"Forbidden pattern ({label}) in {path.relative_to(ROOT)}")

    for path in list(ROOT.rglob("roles/*/tasks/*.yml")):
        text = path.read_text(encoding="utf-8")
        if "github.com/" in text and "/releases/download/" in text and "checksum:" not in text:
            errors.append(f"Release download without checksum verification in {path.relative_to(ROOT)}")

    for rel in [
        "roles/syslog_server/templates/syslog-ng-server.conf.j2",
        "roles/syslog_client/templates/syslog-ng-client.conf.j2",
    ]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if "stats-exporter-dont-log(" not in text or "source(s_metrics);" not in text:
            errors.append(f"Native syslog-ng metrics source is not connected to a log path in {rel}")

    for rel in [
        "roles/prometheus_server/tasks/main.yml",
        "roles/node_exporter/tasks/main.yml",
    ]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if "sha256:https://github.com/prometheus/" not in text:
            errors.append(f"Missing upstream SHA-256 manifest verification in {rel}")
        if 'dest: "/tmp/{{' not in text or "_archive }}" not in text:
            errors.append(f"Release archive destination is not filename-stable in {rel}")

    required = [
        "site.yml",
        "requirements.yml",
        "inventory/example.yml",
        "roles/syslog_pki/tasks/main.yml",
        "roles/clickhouse_server/tasks/main.yml",
        "roles/node_exporter/tasks/main.yml",
        "roles/prometheus_server/tasks/main.yml",
        "roles/syslog_server/templates/syslog-ng-server.conf.j2",
        "roles/syslog_client/templates/syslog-ng-client.conf.j2",
        "scripts/verify.yml",
    ]
    for rel in required:
        if not (ROOT / rel).is_file():
            errors.append(f"Missing required file: {rel}")

    if errors:
        print("STATIC CHECK FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("STATIC CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
