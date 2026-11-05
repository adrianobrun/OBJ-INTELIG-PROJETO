"""Bound the host times of Wokwi edges using causal MQTT probe windows."""
import argparse
import json
from pathlib import Path

QPC_TICK_NS = 100
MAX_WIDTH_NS = 1_500_000_000
REPORT_STEP_NS = 10_000_000

def estimate_latency(vcd_edge_ns, anchors, host_edge_ns, *, sensor):
    before = [a for a in anchors if a["vcd_ns"] < vcd_edge_ns]
    after = [a for a in anchors if a["vcd_ns"] > vcd_edge_ns]
    if not before or not after:
        raise ValueError("Borda fora da sequência de sondas")
    left = max(before, key=lambda a: a["host_send_ns"])
    right = min(after, key=lambda a: a["host_receive_ns"])
    lower = left["host_send_ns"] - QPC_TICK_NS
    upper = right["host_receive_ns"] + QPC_TICK_NS
    if sensor:
        # The sample must exist before the matching telemetry callback.
        upper = min(upper, host_edge_ns + QPC_TICK_NS)
        lo = host_edge_ns - QPC_TICK_NS - upper
        hi = host_edge_ns + QPC_TICK_NS - lower
    else:
        # The command must be published before it can cause the GPIO transition.
        lower = max(lower, host_edge_ns - QPC_TICK_NS)
        lo = lower - (host_edge_ns + QPC_TICK_NS)
        hi = upper - (host_edge_ns - QPC_TICK_NS)
    lo = max(0, lo)
    if lower > upper or hi < lo:
        raise ValueError("Ordem incompatível entre as sondas e o evento MQTT")
    width = hi - lo
    return {
        "vcd_edge_ns": vcd_edge_ns,
        "host_edge_ns": host_edge_ns,
        "probe_before": left["id"],
        "probe_after": right["id"],
        "vcd_edge_host_interval_ns": [lower, upper],
        "latency_interval_ns": [lo, hi],
        "interval_width_ns": width,
        "midpoint_ns": (lo + hi) / 2,
        "half_width_ns": width / 2,
        "report_interval_ms": [
            (lo // REPORT_STEP_NS) * (REPORT_STEP_NS // 1_000_000),
            (-(-hi // REPORT_STEP_NS)) * (REPORT_STEP_NS // 1_000_000)
        ],
        "accepted_width": width <= MAX_WIDTH_NS
    }

def verify(data):
    anchors = data["anchors"]
    if len(anchors) < 4 or len({a["id"] for a in anchors}) != len(anchors):
        raise ValueError("A execução precisa de pelo menos quatro sondas com IDs distintos")
    for a, b in zip(anchors, anchors[1:]):
        for key in ("vcd_ns", "host_send_ns", "host_receive_ns"):
            if a[key] >= b[key]:
                raise ValueError(f"Sondas fora de ordem em {key}")
    for a in anchors:
        if not a["host_send_ns"] < a["host_receive_ns"]:
            raise ValueError("Resposta anterior ao envio da própria sonda")
        if not a["esp_before_us"] * 1000 - 1000 <= a["vcd_ns"] <= a["esp_after_us"] * 1000 + 1000:
            raise ValueError("Borda VCD fora da janela do ESP32")
    rtt_ns = [a["host_receive_ns"] - a["host_send_ns"] for a in anchors]
    s, b = data["sensor"], data["actuator"]
    return {
        "client_id": data["client_id"], "session": data["session"],
        "anchor_count": len(anchors), "probe_round_trip_ns": rtt_ns,
        "reported_step_ns": REPORT_STEP_NS, "max_width_ns": MAX_WIDTH_NS,
        "sensor": {"sample_seq": s["sample_seq"], "mqtt_seq": s["mqtt_seq"],
                   **estimate_latency(s["frame"]["marker_ns"], anchors, s["host_receive_ns"], sensor=True)},
        "actuator": {"command_id": b["id"],
                     **estimate_latency(b["vcd_first_rise_ns"], anchors, b["host_publish_ns"], sensor=False)}
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("analysis", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = verify(json.loads(args.analysis.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
