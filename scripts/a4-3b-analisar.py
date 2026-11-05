"""Link the MQTT pilot records to a single Wokwi VCD."""
import argparse
import json
from pathlib import Path
import re
from statistics import median
import sys

root = Path(__file__).resolve().parent
from decode_vcd import read_vcd, decode_uart

def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

def analyze(vcd, observer, publisher, probes, serial_path, pm25):
    channels = read_vcd(vcd)
    data, errors = decode_uart(channels["PMS_TX"])
    assert not errors, errors
    sample_edges = [t for t, _ in channels["PMS_SAMPLE"] if t > 0]
    decoded = []
    for index in range(0, len(data) - 31, 32):
        frame = data[index:index + 32]
        raw = bytes(byte for _, byte in frame)
        assert raw[:4] == b"BM\x00\x1c" and sum(raw[:30]) == int.from_bytes(raw[30:], "big")
        decoded.append({
            "index": index // 32 + 1, "start_ns": frame[0][0],
            "end_ns": round(frame[-1][0] + 10 * 1e9 / 9600),
            "pm": [int.from_bytes(raw[i:i+2], "big") for i in (10, 12, 14)]
        })
    assert len(decoded) <= len(sample_edges) <= len(decoded) + 1
    for frame, stamp in zip(decoded, sample_edges):
        frame["marker_ns"] = stamp
        assert 0 <= frame["start_ns"] - stamp < 104167
    pub = rows(publisher)
    actuator_tx, = [r for r in pub if r["kind"] == "publish" and r["payload"].startswith("test,")]
    _, ident, duration = actuator_tx["payload"].split(",")
    ident, duration = int(ident), int(duration)
    started, finished = [r for r in pub if r.get("topic", "").endswith("/command-event") and r["payload"].get("id") == ident]
    assert started["payload"]["state"] == "started" and started["payload"]["buzzer_on"] and not started["payload"]["alert"]
    assert finished["payload"]["state"] == "finished" and not finished["payload"]["buzzer_on"]
    device = started["payload"]["client_id"]
    session = started["payload"]["session"]
    assert actuator_tx["topic"].endswith(f"{device}-{session}")
    obs = [r for r in rows(observer) if isinstance(r.get("payload"), dict) and r["payload"].get("client_id") == device]
    sensor_rx = next(r for r in obs if r["topic"].endswith("/telemetry") and r["payload"].get("pm25") == pm25)
    payload = sensor_rx["payload"]
    assert payload["sample_valid"] and not payload["alert"]
    seq = payload["sample_seq"]
    serial = serial_path.read_text(encoding="utf-8")
    assert f"client_id={device}" in serial
    seqs = re.findall(r"^FRAME OK n=(\d+) len=28 PM1.0=(\d+) PM2.5=(\d+) PM10=(\d+)", serial, re.M)
    triples = {int(s): [int(p1), int(p25), int(p10)] for s, p1, p25, p10 in seqs}
    expected = [payload[k] for k in ("pm1", "pm25", "pm10")]
    assert triples[seq] == expected
    first_serial = min(s for s, v in triples.items() if v[1] == pm25)
    assert triples[first_serial - 1][1] != pm25
    first_vcd = next(f["index"] for f in decoded if f["pm"][1] == pm25)
    frame = decoded[first_vcd - 1 + seq - first_serial]
    assert frame["pm"] == expected
    for s in range(first_serial - 1, seq + 1):
        assert decoded[first_vcd - 1 + s - first_serial]["pm"] == triples[s]

    match = re.search(rf"^PILOT ACT id={ident} session={session} level=(\d+) before_us=(\d+) after_us=(\d+)", serial, re.M)
    level, mark_lo, mark_hi = map(int, match.groups())
    # The ESP32 pins settle during setup. The pilot begins after 1 s.
    after_boot = 1_000_000_000
    (act_ns, act_level), = [(t, v) for t, v in channels["ACT_MARK"] if t > after_boot]
    assert act_level == level
    assert mark_lo * 1000 - 1000 <= act_ns <= mark_hi * 1000 + 1000
    rises = [t for t, v in channels["BUZZER"] if t > after_boot and v == 1]
    assert rises[0] >= act_ns and len(rises) > 5
    assert channels["BUZZER"][-1][1] == 0
    freq = 1e9 / median(b-a for a, b in zip(rises, rises[1:]))
    assert 3900 < freq < 4100

    sync_rows = [*rows(probes), *pub]
    requests = [r for r in sync_rows if r["kind"] == "publish" and r["payload"].startswith("sync,")]
    probes_sent = {int(r["payload"].split(",")[1]): r for r in requests}
    replies = [r for r in sync_rows if r.get("topic", "").endswith("/pilot-sync")]
    edges = [(t, v) for t, v in channels["SYNC_MARK"] if t > after_boot]
    assert len(requests) == len(probes_sent) == len(replies) == len(edges) >= 4
    assert set(probes_sent) == {r["payload"]["id"] for r in replies}
    anchors = []
    for reply, (stamp, v) in zip(replies, edges):
        p = reply["payload"]
        sent = probes_sent[p["id"]]
        assert p["level"] == v and p["client_id"] == device and p["session"] == session
        assert sent["host_ns"] < reply["host_ns"]
        assert p["before_us"] * 1000 - 1000 <= stamp <= p["after_us"] * 1000 + 1000
        anchors.append({"id": p["id"], "vcd_ns": stamp, "host_send_ns": sent["host_ns"],
                        "host_receive_ns": reply["host_ns"], "esp_before_us": p["before_us"],
                        "esp_after_us": p["after_us"]})
    for edge_ns in (frame["marker_ns"], rises[0]):
        assert anchors[0]["vcd_ns"] < edge_ns < anchors[-1]["vcd_ns"]
    return {"client_id": device, "session": session, "vcd_frames": len(decoded), "uart_errors": len(errors),
            "sensor": {"frame": frame, "first_changed_sample_seq": first_serial, "first_changed_vcd_index": first_vcd,
                       "mqtt_seq": payload["seq"], "sample_seq": seq, "host_receive_ns": sensor_rx["host_ns"],
                       "esp_publish_uptime_ms": payload["uptime_ms"]},
            "actuator": {"id": ident, "duration_ms": duration, "host_publish_ns": actuator_tx["host_ns"],
                         "vcd_marker_ns": act_ns, "esp_mark_before_us": mark_lo, "esp_mark_after_us": mark_hi,
                         "vcd_first_rise_ns": rises[0], "marker_to_gpio_ns": rises[0] - act_ns,
                         "frequency_hz": freq, "host_ack_ns": started["host_ns"],
                         "finished_esp_uptime_ms": finished["payload"]["uptime_ms"]},
            "anchors": anchors}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("vcd", "observer", "publisher", "probes", "serial", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--pm25", type=int, required=True)
    args = parser.parse_args()
    result = analyze(args.vcd, args.observer, args.publisher, args.probes, args.serial, args.pm25)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
