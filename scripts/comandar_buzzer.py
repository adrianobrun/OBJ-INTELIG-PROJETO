"""Interactive publisher and observer for the simulated buzzer."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from threading import Event, Lock
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).with_name("mqtt-client-deps")))
from paho.mqtt.client import CallbackAPIVersion, Client, MQTTv311


BROKER = "broker.emqx.io"
PREFIX = "obj-intelig-projeto/pm/47db91f2"
STATUS = PREFIX + "/status"
TELEMETRY = PREFIX + "/telemetry"
BUZZER_EVENT = PREFIX + "/command-event"
print_lock = Lock()
online = {}
first_topic = None


def log(event, **fields):
    with print_lock:
        print(json.dumps({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event, **fields,
        }), flush=True)


def on_connect(client, userdata, flags, reason, properties):
    log("connack", reason=str(reason))
    if not reason.is_failure:
        client.subscribe([(STATUS, 1), (TELEMETRY, 0), (BUZZER_EVENT, 0)])


def on_message(client, userdata, message):
    global online, first_topic
    try:
        payload = json.loads(message.payload)
    except ValueError:
        return
    log("received", topic=message.topic, retained=message.retain, payload=payload)
    if message.topic == STATUS and isinstance(payload, dict):
        topic = payload.get("command_topic")
        if payload.get("online") is True and isinstance(topic, str) and topic.startswith(PREFIX + "/command/"):
            online = payload
            if first_topic is None:
                first_topic = topic
        elif payload.get("online") is False and payload.get("client_id") == online.get("client_id"):
            online = {}


def publish(client, topic, payload, retain=False):
    log("send", topic=topic, payload=payload, retained=retain)
    info = client.publish(topic, payload, qos=1 if retain else 0, retain=retain)
    info.wait_for_publish(timeout=3)
    if not info.is_published():
        raise RuntimeError("Publicação sem confirmação de envio")


def replace_connection(device_id):
    """End the specific simulated device session via MQTT client-ID takeover."""
    connected = Event()
    probe = Client(CallbackAPIVersion.VERSION2, device_id, protocol=MQTTv311)

    def acknowledge(client, userdata, flags, reason, properties):
        if not reason.is_failure:
            connected.set()

    probe.on_connect = acknowledge
    probe.connect_timeout = 4
    probe.connect(BROKER, 1883, keepalive=10)
    probe.loop_start()
    try:
        if not connected.wait(4):
            raise RuntimeError("Sem CONNACK para o ensaio de reconexão")
        log("takeover", client_id=device_id)
    finally:
        probe.disconnect()
        probe.loop_stop()


if __name__ == "__main__":
    client = Client(CallbackAPIVersion.VERSION2, f"pm-cmd-{uuid4().hex[:12]}",
                    protocol=MQTTv311)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_timeout = 10
    client.connect(BROKER, 1883, keepalive=20)
    client.loop_start()
    try:
        for line in sys.stdin:
            action, _, payload = line.strip().partition(" ")
            if action == "quit":
                break
            try:
                current = online
                if action == "send" and current:
                    publish(client, current["command_topic"], payload)
                elif action == "drop" and current:
                    replace_connection(current["client_id"])
                elif action == "old" and first_topic and first_topic != current.get("command_topic"):
                    publish(client, first_topic, payload, retain=True)
                elif action == "clear" and first_topic:
                    publish(client, first_topic, "", retain=True)
                else:
                    log("input_unavailable", action=action)
            except (OSError, RuntimeError, ValueError) as error:
                log("input_error", action=action, detail=str(error))
    finally:
        client.disconnect()
        client.loop_stop()
