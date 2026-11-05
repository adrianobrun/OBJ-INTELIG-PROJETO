"""Validate one acquisition and preserve its acceptance or rejection."""
import argparse
from importlib import import_module
import json
from pathlib import Path

decode = import_module("a4-3b-analisar")
clock = import_module("a4-3c-tempo")

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def check(folder, pm25, command_id):
    log = folder / "mqtt.jsonl"
    result = decode.analyze(folder / "captura.vcd", log, log, folder.parent / "sem-log-externo.jsonl",
                            folder / "serial.txt", pm25)
    if result["actuator"]["id"] != command_id:
        raise ValueError("O comando analisado não corresponde ao ID registrado para esta tentativa")
    raw = decode.rows(log)
    device = result["client_id"]
    session = result["session"]
    status = [r["payload"] for r in raw if r.get("topic", "").endswith("/status")
              and r.get("payload", {}).get("client_id") == device]
    if len(status) != 1 or status[0].get("online") is not True or status[0].get("session") != session:
        raise ValueError("A presença MQTT não confirma sessão única e contínua")
    telemetry = [r for r in raw if r.get("topic", "").endswith("/telemetry") and
                 r.get("payload", {}).get("client_id") == device]
    index = next(i for i, row in enumerate(telemetry) if row["payload"]["pm25"] == pm25)
    if not index or telemetry[index - 1]["payload"]["pm25"] != 20:
        raise ValueError("Falta a telemetria inicial a 20 µg/m³ antes do estímulo")
    window = telemetry[:index + 1]
    if any(r.get("retain") or r["payload"]["sample_valid"] is not True for r in window):
        raise ValueError("Telemetria inválida ou retida na janela do sensor")
    seqs = [r["payload"]["seq"] for r in window]
    if any(after != before + 1 for before, after in zip(seqs, seqs[1:])):
        raise ValueError("Mensagem MQTT ausente ou repetida na janela do sensor")
    command = next(r for r in raw if r["kind"] == "publish" and r["payload"] == f"test,{command_id},500")
    if command.get("rc") != 0 or command.get("retain") or command.get("qos") != 0:
        raise ValueError("Parâmetros de publicação do comando divergentes")
    if sum(a["host_send_ns"] > command["host_ns"] for a in result["anchors"]) < 6:
        raise ValueError("Menos de seis sondas após o comando")
    bounds = clock.verify(result)
    save(folder / "analise.json", result)
    save(folder / "intervalos.json", bounds)
    return result, bounds

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--pm25", type=int, required=True)
    parser.add_argument("--id", type=int, required=True)
    args = parser.parse_args()
    record = {"attempt": args.folder.name, "initial_pm25": 20, "stimulus_pm25": args.pm25,
              "command_id": args.id, "firmware": "a4-3b-piloto", "unit": "ms"}
    try:
        result, bounds = check(args.folder, args.pm25, args.id)
    except (AssertionError, AttributeError, IndexError, KeyError, OSError, StopIteration, TypeError, ValueError) as exc:
        record["rejection"] = str(exc) or type(exc).__name__
        save(args.folder / "tentativa.json", record)
        raise
    record["client_id"] = result["client_id"]
    record["session"] = result["session"]
    record["probes"] = bounds["anchor_count"]
    for path in ("sensor", "actuator"):
        values = bounds[path]
        record[path] = {"accepted": values["accepted_width"], "interval_ms": values["report_interval_ms"],
                        "raw_width_ms": values["interval_width_ns"] / 1_000_000}
        if not values["accepted_width"]:
            record[path]["reason"] = "Intervalo bruto mais largo que 1.500 ms"
    save(args.folder / "tentativa.json", record)
    print(json.dumps(record, ensure_ascii=False))
