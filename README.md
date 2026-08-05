# syslog-ng 4.12 → ClickHouse LTS + Prometheus

Проект разворачивает централизованный журнал событий на Linux:

```text
Linux clients
  ├─ system()/journald
  ├─ syslog-ng 4.12+
  ├─ mTLS TCP/6514
  ├─ native syslog-ng metrics :9577
  └─ node_exporter :9100
             │
             ▼
Central server
  ├─ syslog-ng 4.12+ → HTTP JSONEachRow
  ├─ ClickHouse LTS → 127.0.0.1:8123/9000
  ├─ ClickHouse metrics → 127.0.0.1:9363/metrics
  └─ Prometheus 3.13.2 → 127.0.0.1:9090
```

Клиенты и сервер взаимно проверяют сертификаты. ClickHouse и веб-интерфейс Prometheus не публикуются в локальную сеть по умолчанию. Prometheus собирает системные метрики, внутренние счётчики syslog-ng и штатные метрики ClickHouse.

## Поддерживаемые платформы

- управляющий узел: Debian/Ubuntu, Python 3.12+;
- целевые узлы: Debian 12/13 либо Ubuntu 24.04/26.04 LTS;
- amd64 и arm64;
- Ansible Core 2.20–2.21;
- ровно один узел `syslog_servers` и один или несколько `syslog_clients`.

## Версии по умолчанию

- syslog-ng: официальный stable-репозиторий, минимум 4.12.0;
- ClickHouse: официальный `lts` APT-канал; на 5 августа 2026 года актуальная линия — 26.3.17.110-lts;
- Prometheus: 3.13.2;
- Node Exporter: 1.12.1.

Prometheus и Node Exporter закреплены на точных версиях и проверяются по upstream SHA-256 manifest. syslog-ng и ClickHouse обновляются только внутри выбранных официальных каналов; автоматическое обновление можно отключить переменными `syslog_ng_upgrade_packages` и `clickhouse_upgrade_packages`.

## Быстрый запуск

```bash
./scripts/bootstrap.sh
```

Заполните `inventory/hosts.yml`. Адрес `prometheus_target_address` должен быть доступен с центрального сервера:

```yaml
client01:
  ansible_host: 10.0.2.21
  prometheus_target_address: 10.0.2.21
  syslog_tls_sans:
    - DNS:client01
    - IP:10.0.2.21
```

Создайте пароль ClickHouse в `group_vars/all/vault.yml`, затем зашифруйте файл:

```bash
.venv/bin/ansible-vault encrypt group_vars/all/vault.yml
```

Проверка и развёртывание:

```bash
make check
make syntax
make deploy
make verify
```

## Сеть

Разрешите только необходимые направления:

- управляющий узел → все узлы: TCP/22;
- клиенты → центральный сервер: TCP/6514;
- центральный сервер → все узлы: TCP/9100 и TCP/9577;
- ClickHouse 8123/9000/9363 и Prometheus 9090 остаются loopback-only.

TCP/9100 и TCP/9577 не имеют прикладной аутентификации. Ограничьте их на уровне nftables/UFW только адресом центрального сервера или выделенной сетью мониторинга.

## Prometheus

Веб-интерфейс по умолчанию доступен только через SSH-туннель:

```bash
ssh -L 9090:127.0.0.1:9090 log01
```

После этого откройте локально `http://127.0.0.1:9090`.

Настроены задания:

- `prometheus` — сам Prometheus;
- `clickhouse` — `system.metrics`, `system.events`, asynchronous metrics и errors;
- `node` — CPU, память, диски, сеть и состояние ОС;
- `syslog_ng` — очереди, обработанные/отброшенные сообщения и внутренние счётчики pipeline.

Правила предупреждают о недоступных целях, дефиците места/памяти и ошибках вычисления правил. Отправка уведомлений не включена, поскольку для неё нужны конкретные SMTP/webhook-реквизиты. Состояние правил видно в Prometheus на странице **Alerts**.

## ClickHouse

Создаётся таблица `syslog.events` с месячными партициями, ZSTD-кодированием, сортировкой по времени/узлу/программе и TTL 90 дней. Пользователь `syslog_ingest` имеет только право `INSERT`.

Проверка последних событий:

```bash
sudo clickhouse-client --query "SELECT event_time, host, program, severity, message FROM syslog.events ORDER BY event_time DESC LIMIT 20"
```

## Надёжность

- передача клиент → сервер: mutual TLS и reliable disk-buffer;
- запись сервер → ClickHouse: HTTP batching, flow-control и reliable disk-buffer;
- семантика доставки: at-least-once, поэтому при неоднозначном сетевом сбое возможны дубликаты;
- PKI хранится на управляющем узле в `~/.ansible/syslog-ng-clickhouse/pki`.

## Обновление существующей установки

См. [MIGRATION.md](MIGRATION.md). Перед обновлением сохраните резервные копии конфигураций, PKI и данных ClickHouse.

## Ограничения проверки

Статическая проверка анализирует YAML, Jinja2, shell и обязательную SHA-256-проверку бинарных релизов. Полный интеграционный тест выполняется playbook `scripts/verify.yml` на реальных узлах.
