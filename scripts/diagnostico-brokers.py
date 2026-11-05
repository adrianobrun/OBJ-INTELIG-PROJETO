"""Compare DNS, TCP, TLS and MQTT 3.1.1 without publishing messages."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import socket
import ssl
from threading import Lock
from time import perf_counter
from uuid import uuid4


MOSQUITTO = "test.mosquitto.org"
EMQX = "broker.emqx.io"
TIMEOUT = 6
LOG_LOCK = Lock()


def log(event, **data):
    with LOG_LOCK:
        print(json.dumps({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            **data,
        }), flush=True)


def resolve(host):
    addresses = {}
    for family, label in ((socket.AF_INET, "IPv4"), (socket.AF_INET6, "IPv6")):
        try:
            records = socket.getaddrinfo(host, 1883, family, socket.SOCK_STREAM)
            addresses[family] = list(dict.fromkeys(record[4][0] for record in records))
            log("dns", host=host, family=label, addresses=addresses[family])
        except socket.gaierror as error:
            log("dns_error", host=host, family=label, detail=str(error))
    return addresses


def connect_mqtt(connection):
    client_id = ("a4diag" + uuid4().hex[:12]).encode("ascii")
    variable_header = b"\x00\x04MQTT\x04\x02\x00\x14"
    body = variable_header + len(client_id).to_bytes(2, "big") + client_id
    connection.sendall(bytes((0x10, len(body))) + body)
    reply = bytearray()
    while len(reply) < 4:
        part = connection.recv(4 - len(reply))
        if not part:
            raise ConnectionError(f"peer closed, response={reply.hex()}")
        reply.extend(part)
    if reply[:2] != b"\x20\x02":
        raise ValueError(f"unexpected MQTT response={reply.hex()}")
    if reply[3] == 0:
        connection.sendall(b"\xe0\x00")
    return reply.hex(), reply[3]


def probe(host, address, port, mode, attempt):
    identity = dict(host=host, ip=address, port=port, mode=mode, attempt=attempt)
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    stage = "tcp"
    started = perf_counter()
    try:
        with socket.socket(family, socket.SOCK_STREAM) as tcp:
            tcp.settimeout(TIMEOUT)
            tcp.connect((address, port))
            log("tcp_ok", **identity, elapsed_ms=round((perf_counter() - started) * 1000))
            if mode == "mqtt":
                stage = "connack"
                started = perf_counter()
                packet, code = connect_mqtt(tcp)
                log("connack", **identity, packet=packet, code=code,
                    elapsed_ms=round((perf_counter() - started) * 1000))
            else:
                stage = "tls"
                started = perf_counter()
                context = ssl.create_default_context()
                with context.wrap_socket(tcp, server_hostname=host) as secured:
                    log("tls_ok", **identity, protocol=secured.version(),
                        elapsed_ms=round((perf_counter() - started) * 1000))
                    if mode == "mqtt_tls":
                        stage = "connack"
                        started = perf_counter()
                        packet, code = connect_mqtt(secured)
                        log("connack", **identity, packet=packet, code=code,
                            elapsed_ms=round((perf_counter() - started) * 1000))
    except (OSError, ValueError) as error:
        log("error", **identity, stage=stage, error_type=type(error).__name__,
            elapsed_ms=round((perf_counter() - started) * 1000), detail=str(error))


if __name__ == "__main__":
    resolved = {host: resolve(host) for host in (MOSQUITTO, EMQX)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for attempt in range(1, 4):
            tasks = []
            for host, addresses in resolved.items():
                for address in addresses.get(socket.AF_INET, []):
                    tasks.append(pool.submit(probe, host, address, 1883, "mqtt", attempt))
            if attempt == 1:
                for host, addresses in resolved.items():
                    for address in addresses.get(socket.AF_INET6, [])[:1]:
                        tasks.append(pool.submit(probe, host, address, 1883, "mqtt", attempt))
                for address in resolved[MOSQUITTO].get(socket.AF_INET, [])[:1]:
                    tasks.append(pool.submit(probe, MOSQUITTO, address, 8886, "mqtt_tls", attempt))
                    tasks.append(pool.submit(probe, MOSQUITTO, address, 443, "https_tls", attempt))
            for task in tasks:
                task.result()
