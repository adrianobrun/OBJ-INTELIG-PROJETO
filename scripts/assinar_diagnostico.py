import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import ssl
import sys
from threading import Event
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).with_name("mqtt-client-deps")))
from paho.mqtt.client import CallbackAPIVersion, Client, MQTTv311


parser = argparse.ArgumentParser()
parser.add_argument("--broker", default="broker.emqx.io")
parser.add_argument("--port", type=int, choices=[1883, 8081, 8084, 8886], default=1883)
parser.add_argument("--topic", default="obj-intelig-projeto/pm/47db91f2/probe")
parser.add_argument("--count", type=int, default=1)
parser.add_argument("--timeout", type=float, default=180)
args = parser.parse_args()
if args.count < 1 or args.timeout <= 0:
    parser.error("--count e --timeout devem ser positivos")
broker = args.broker
topic = args.topic
received = Event()
message_count = 0


def log(event, **fields):
    print(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }), flush=True)


def on_connect(client, userdata, flags, reason_code, properties):
    log("connack", reason=str(reason_code))
    if not reason_code.is_failure:
        client.subscribe(topic, qos=0)


def on_subscribe(client, userdata, mid, reason_codes, properties):
    log("suback", topic=topic, qos=[str(reason) for reason in reason_codes])


def on_message(client, userdata, message):
    global message_count
    log("message", topic=message.topic, qos=message.qos, retain=message.retain,
        payload=message.payload.decode("utf-8", errors="replace"))
    if not message.retain:
        message_count += 1
        if message_count >= args.count:
            received.set()


transport = "websockets" if args.port in (8081, 8084) else "tcp"
client = Client(CallbackAPIVersion.VERSION2, f"pm-sub-{uuid4().hex[:12]}",
                protocol=MQTTv311, transport=transport)
client.on_connect = on_connect
client.on_subscribe = on_subscribe
client.on_message = on_message
client.connect_timeout = 10
if args.port != 1883:
    client.tls_set_context(ssl.create_default_context())
log("connect", broker=broker, port=args.port, transport=transport)
try:
    client.connect(broker, args.port, keepalive=20)
except OSError as error:
    log("connect_error", detail=str(error))
    sys.exit(1)
client.loop_start()
try:
    if not received.wait(args.timeout):
        log("timeout", topic=topic, received=message_count, expected=args.count)
        sys.exit(1)
finally:
    client.disconnect()
    client.loop_stop()
