"""Observe connection and sample state for the MQTT particulate monitor."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import monotonic
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).with_name("mqtt-client-deps")))
from paho.mqtt.client import CallbackAPIVersion, Client, MQTT_ERR_SUCCESS, MQTTv311


BROKER = "broker.emqx.io"
TELEMETRY = "obj-intelig-projeto/pm/47db91f2/telemetry"
STATUS = "obj-intelig-projeto/pm/47db91f2/status"
FRESHNESS_SECONDS = 15


def log(event, **fields):
    print(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }), flush=True)


class Observer:
    def __init__(self):
        self.state = None
        self.client_id = None
        self.online_since = None
        self.last_telemetry = None

    def set_state(self, state, cause):
        if state != self.state:
            self.state = state
            log("state", state=state, cause=cause, client_id=self.client_id)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        log("connack", reason=str(reason_code))
        if not reason_code.is_failure:
            client.subscribe([(STATUS, 1), (TELEMETRY, 0)])
            self.set_state("aguardando_dispositivo", "inscricao")

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.set_state("broker_indisponivel", str(reason_code))

    def on_subscribe(self, client, userdata, mid, reason_codes, properties):
        log("suback", qos=[str(reason) for reason in reason_codes])

    def on_message(self, client, userdata, message):
        try:
            payload = json.loads(message.payload)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(payload, dict) or not isinstance(payload.get("client_id"), str):
            return
        log("message", topic=message.topic, qos=message.qos,
            retain=message.retain, payload=payload)
        now = monotonic()
        if message.topic == STATUS and type(payload.get("online")) is bool:
            if payload["online"]:
                self.client_id = payload["client_id"]
                self.online_since = now
                self.last_telemetry = None
                self.set_state("aguardando_telemetria", "status_online")
            elif self.client_id in (None, payload["client_id"]):
                self.online_since = None
                self.last_telemetry = None
                self.set_state("dispositivo_desconectado", "last_will")
        elif (message.topic == TELEMETRY and not message.retain
              and payload["client_id"] == self.client_id and self.online_since is not None
              and type(payload.get("sample_valid")) is bool):
            self.last_telemetry = now
            self.set_state("amostra_valida" if payload["sample_valid"] else "amostra_expirada",
                           "telemetria")

    def check_freshness(self):
        reference = self.last_telemetry or self.online_since
        if reference is not None and monotonic() - reference >= FRESHNESS_SECONDS:
            self.set_state("dispositivo_desconectado", "sem_telemetria_por_15_s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=240)
    args = parser.parse_args()
    observer = Observer()
    client = Client(CallbackAPIVersion.VERSION2, f"pm-obs-{uuid4().hex[:12]}",
                    protocol=MQTTv311)
    client.on_connect = observer.on_connect
    client.on_disconnect = observer.on_disconnect
    client.on_subscribe = observer.on_subscribe
    client.on_message = observer.on_message
    client.connect_timeout = 10
    client.connect(BROKER, 1883, keepalive=20)
    deadline = monotonic() + args.duration
    try:
        while monotonic() < deadline:
            if client.loop(timeout=0.5) != MQTT_ERR_SUCCESS:
                break
            observer.check_freshness()
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
