"""Capture the MQTT ends of the A4 pilot on one Windows host clock."""
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from threading import Lock
from time import monotonic, perf_counter_ns
from uuid import uuid4
import argparse
import json
import sys

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK / "mqtt-client-deps"))
from paho.mqtt.client import CallbackAPIVersion, Client, MQTTv311

BASE = "obj-intelig-projeto/a4/47db91f2"
TOPICS = [(f"{BASE}/{leaf}", qos) for leaf, qos in [
    ("status", 1), ("telemetry", 0), ("command-event", 0), ("pilot-sync", 0)
]]

def execute(args):
    dest = Path(args.log)
    received = Queue()
    target_sample = None
    log_lock = Lock()
    client = Client(CallbackAPIVersion.VERSION2, "a4-pilot-" + uuid4().hex[:12], protocol=MQTTv311)
    client.connect_timeout = 8
    with dest.open("x", encoding="utf-8", buffering=1) as file:
        def log(kind, time_ns, **data):
            row = {"kind": kind, "host_ns": time_ns, "utc": datetime.now(timezone.utc).isoformat(), **data}
            with log_lock:
                file.write(json.dumps(row, separators=(",", ":")) + "\n")

        def connect(c, _u, _flags, reason, _p):
            if not reason.is_failure:
                c.subscribe(TOPICS)

        def subscribed(_c, _u, _mid, reasons, _p):
            log("suback", perf_counter_ns(), qos=[str(reason) for reason in reasons])

        def message(_c, _u, msg):
            nonlocal target_sample
            edge = perf_counter_ns()
            try:
                body = json.loads(msg.payload)
            except ValueError:
                return
            if isinstance(body, dict):
                log("receive", edge, topic=msg.topic, retain=msg.retain, payload=body)
                if (args.mode == "calibrate" and msg.topic == f"{BASE}/telemetry"
                        and not msg.retain and body.get("client_id") == args.device
                        and body.get("pm25") == args.pm25 and body.get("sample_valid") is True
                        and body.get("alert") is False and body.get("buzzer_on") is False):
                    target_sample = body
                if args.mode != "observe":
                    received.put((msg.topic, body))

        def expect(suffix, match, timeout=14):
            end = monotonic() + timeout
            while (remaining := end - monotonic()) > 0:
                try:
                    topic, data = received.get(timeout=remaining)
                except Empty:
                    break
                if topic == f"{BASE}/{suffix}" and match(data):
                    return data
            raise RuntimeError(f"Tempo esgotado aguardando {suffix}")

        client.on_connect, client.on_subscribe, client.on_message = connect, subscribed, message
        client.connect("broker.emqx.io", 1883, keepalive=20)
        if args.mode == "observe":
            client.loop_forever()
            return

        client.loop_start()
        try:
            status = expect("status", lambda data: data.get("client_id") == args.device and data.get("online") is True)
            session = status["session"]
            topic = f"{BASE}/command/{args.device}-{session}"
            if status.get("command_topic") != topic:
                raise RuntimeError("Tópico da sessão não corresponde ao esperado")

            def send(payload):
                stamp = perf_counter_ns()
                info = client.publish(topic, payload, qos=0, retain=False)
                log("publish", stamp, topic=topic, payload=payload, qos=0, retain=False, rc=int(info.rc))
                info.wait_for_publish(timeout=5)
                if not info.is_published():
                    raise RuntimeError(f"Publicação não enviada: {payload}")

            def matches(p, id):
                return p.get("client_id") == args.device and p.get("session") == session and p.get("id") == id

            def sync(id):
                send(f"sync,{id}")
                answer = expect("pilot-sync", lambda p: matches(p, id))
                print(f"Sonda {id} respondida. ESP32 {answer['before_us']}–{answer['after_us']} us.", flush=True)

            def paced_calibration():
                waiting = {}
                count = replies = post = 0
                test_sent = False
                next_probe = monotonic()
                cadence = args.cadence_ms / 1000
                while post < 6 or waiting:
                    now = monotonic()
                    if any(now - sent > 4 for sent in waiting.values()):
                        raise RuntimeError(f"Sonda sem resposta: {list(waiting)}")
                    if target_sample is not None and replies >= 3 and not test_sent:
                        send(f"test,{args.id},500")
                        test_sent = True
                    if now >= next_probe and len(waiting) < 6 and post < 6 and count < args.probes:
                        ident = args.id + count + 1
                        waiting[ident] = now
                        send(f"sync,{ident}")
                        count += 1
                        post += int(test_sent)
                        next_probe = now + cadence
                    if count >= args.probes and not waiting and post < 6:
                        raise RuntimeError("Limite de sondas atingido antes do fim do piloto")
                    try:
                        topic, data = received.get(timeout=0.02)
                    except Empty:
                        continue
                    if topic == f"{BASE}/status" and data.get("client_id") == args.device and (
                        data.get("online") is False or data.get("session") != session
                    ):
                        raise RuntimeError("A sessão MQTT mudou durante o ensaio")
                    if topic == f"{BASE}/pilot-sync" and data.get("client_id") == args.device:
                        ident = data.get("id")
                        if ident not in waiting or not matches(data, ident):
                            raise RuntimeError(f"Resposta duplicada ou fora da sessão: {ident}")
                        waiting.pop(ident)
                        replies += 1
                        if replies == 3:
                            print(f"Pode aplicar o patamar de {args.pm25} µg/m³.", flush=True)
                print(f"{replies} sondas respondidas, incluindo {post} após o comando.", flush=True)

            if args.mode == "calibrate" and args.cadence_ms:
                paced_calibration()
            elif args.mode == "calibrate":
                sent_at = None
                print(f"Pronto para sondar {args.device}, sessão {session}. Aguarde a terceira sonda.", flush=True)
                for i in range(args.probes):
                    sync(args.id + i + 1)
                    if i == 2:
                        print(f"Pode aplicar o patamar de {args.pm25} µg/m³.", flush=True)
                    if i >= 2 and sent_at is None and target_sample is not None:
                        send(f"test,{args.id},500")
                        sent_at = i
                    if sent_at is not None and i - sent_at >= 4:
                        break
                if sent_at is None or i - sent_at < 4:
                    raise RuntimeError("Piloto incompleto: amostra ausente ou sondas finais insuficientes")
            elif args.mode == "run":
                sync(args.id - 1)
                send(f"test,{args.id},500")
                expect("command-event", lambda p: matches(p, args.id) and p.get("state") == "started")
                expect("command-event", lambda p: matches(p, args.id) and p.get("state") == "finished")
                print(f"Autoteste {args.id} iniciado e finalizado.", flush=True)
                sync(args.id + 1)
            else:
                sync(args.id - 1)
                sync(args.id + 1)
        finally:
            client.disconnect()
            client.loop_stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("observe", "run", "sync", "calibrate"))
    parser.add_argument("--log", required=True)
    parser.add_argument("--device")
    parser.add_argument("--id", type=int, default=1001)
    parser.add_argument("--pm25", type=int)
    parser.add_argument("--probes", type=int, default=55)
    parser.add_argument("--cadence-ms", type=int)
    args = parser.parse_args()
    if args.mode != "observe" and (not args.device or not 1 < args.id < 2**32 - 1):
        parser.error("Informe o ID do dispositivo e um ID inteiro de 2 a 4294967294")
    if args.mode == "calibrate" and (
        args.pm25 is None or not 0 <= args.pm25 <= 50 or args.probes < 8
        or args.id + args.probes >= 2**32
    ):
        parser.error("Informe um PM2.5 de 0 a 50 e pelo menos oito sondas com IDs válidos")
    if args.cadence_ms is not None and (args.mode != "calibrate" or not 100 <= args.cadence_ms <= 1000):
        parser.error("A cadência do modo calibrate deve ficar entre 100 e 1000 ms")
    execute(args)
