"""Independent MQTT capture and one deliberately invalid command for A4 3A."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import re
import sys
from threading import Event, Lock
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).with_name("mqtt-client-deps")))
from paho.mqtt.client import CallbackAPIVersion, Client, MQTTv311

BASE = "obj-intelig-projeto/a4/47db91f2"
BROKER = "broker.emqx.io"
DEST = Path(__file__).resolve().parents[1] / "dados/novos-ensaios/testes-integrados.jsonl"
lock = Lock()

def log(kind, **fields):
    row = dict(at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"), kind=kind, **fields)
    with lock, DEST.open("a", encoding="utf-8") as f:
        print(json.dumps(row, ensure_ascii=False), file=f, flush=True)
    if kind in {"ready", "invalid_sent"}:
        print(row, flush=True)

def client():
    c = Client(CallbackAPIVersion.VERSION2, f"a4-3a-{uuid4().hex[:14]}", protocol=MQTTv311)
    c.connect_timeout = 8
    return c

def observe():
    c = client()

    def connected(c, _u, _flags, reason, _p):
        if not reason.is_failure:
            c.subscribe([(BASE + "/status", 1), (BASE + "/telemetry", 0), (BASE + "/command-event", 0)])

    def subscribed(_c, _u, _mid, reasons, _p):
        log("ready", suback=[str(r) for r in reasons])

    def received(_c, _u, message):
        raw = message.payload.decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw
        log("received", topic=message.topic, retain=message.retain, payload=body)

    c.on_connect, c.on_subscribe, c.on_message = connected, subscribed, received
    c.connect(BROKER, 1883, keepalive=20)
    c.loop_forever()

def invalid(client_id, session):
    if not re.fullmatch(r"a4-47db91f2-[0-9a-f]{8}", client_id) or not 1 <= session < 2**32:
        raise ValueError("Identificador da simulação inválido")
    topic = f"{BASE}/command/{client_id}-{session}"
    payload = "test,123456,2000"
    c = client()
    ready = Event()
    current = Event()

    def connected(c, _u, _flags, reason, _p):
        if not reason.is_failure:
            c.subscribe(BASE + "/status", 1)
            ready.set()

    def status(_c, _u, message):
        p = json.loads(message.payload)
        if (p.get("client_id"), p.get("online"), p.get("session"), p.get("command_topic")) == (client_id, True, session, topic):
            current.set()

    c.on_connect, c.on_message = connected, status
    c.connect(BROKER, 1883, keepalive=20)
    c.loop_start()
    try:
        if not ready.wait(5) or not current.wait(5):
            raise RuntimeError("A presença MQTT não confirma a sessão informada")
        result = c.publish(topic, payload, qos=0, retain=False)
        result.wait_for_publish(timeout=5)
        if not result.is_published():
            raise RuntimeError("A publicação MQTT não saiu do cliente")
        log("invalid_sent", topic=topic, retain=False, payload=payload)
    finally:
        c.disconnect()
        c.loop_stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("observe")
    send = sub.add_parser("invalid")
    send.add_argument("client_id")
    send.add_argument("session", type=int)
    args = parser.parse_args()
    DEST.parent.mkdir(exist_ok=True)
    observe() if args.mode == "observe" else invalid(args.client_id, args.session)
