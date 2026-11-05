"""Select the first four accepted measurements of each path in attempt order."""
import json
from pathlib import Path

data = Path(__file__).resolve().parents[1] / "dados/medicoes"
paths = {"sensor": [], "actuator": []}
attempts = []

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

for path in sorted(data.glob("[0-9][0-9]/tentativa.json")):
    attempt = load(path)
    attempts.append(attempt)
    if "rejection" in attempt:
        continue
    analysis = load(path.with_name("analise.json"))
    bounds = load(path.with_name("intervalos.json"))
    for name, measures in paths.items():
        if not attempt[name]["accepted"] or len(measures) == 4:
            continue
        values = bounds[name]
        lower, upper = values["latency_interval_ns"]
        if name == "sensor":
            endpoint_1 = {"event": "geracao_do_quadro_NC7", "clock": "VCD", "ns": values["vcd_edge_ns"]}
            endpoint_2 = {"event": "entrada_callback_MQTT", "clock": "QPC", "ns": values["host_edge_ns"]}
            identifiers = {"sample_seq": values["sample_seq"], "mqtt_seq": values["mqtt_seq"],
                           "vcd_frame": analysis["sensor"]["frame"]["index"]}
        else:
            endpoint_1 = {"event": "inicio_publicacao_MQTT", "clock": "QPC", "ns": values["host_edge_ns"]}
            endpoint_2 = {"event": "primeira_subida_GPIO21", "clock": "VCD", "ns": values["vcd_edge_ns"]}
            identifiers = {"command_id": values["command_id"]}
        measures.append({
            "measurement": len(measures) + 1,
            "attempt": attempt["attempt"],
            "firmware": attempt["firmware"],
            "client_id": attempt["client_id"],
            "session": attempt["session"],
            "initial_pm25_ug_m3": attempt["initial_pm25"],
            "stimulus_pm25_ug_m3": attempt["stimulus_pm25"],
            "identifiers": identifiers,
            "start": endpoint_1,
            "end": endpoint_2,
            "probe_before": values["probe_before"],
            "probe_after": values["probe_after"],
            "raw_latency_ns": [lower, upper],
            "report_latency_ms": values["report_interval_ms"],
            "midpoint_report_ms": (lower + upper + 10_000_000) // 20_000_000 * 10,
            "evidence": [f"{attempt['attempt']}/{file}" for file in (
                "captura.vcd", "mqtt.jsonl", "serial.txt", "analise.json", "intervalos.json"
            )]
        })
bundle = {"version": "a4-3d", "attempts": attempts, "measurements": paths}
(data / "medicoes.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
for name, measures in paths.items():
    print(name, len(measures), [(m["attempt"], m["identifiers"], m["report_latency_ms"]) for m in measures])
