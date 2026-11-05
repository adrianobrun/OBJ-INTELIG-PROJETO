"""Build figures and the results table from accepted A4 measurements."""
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
from shutil import copyfile
import sys

work = Path(__file__).resolve().parents[1]
out = work / "docs"
figures = out / "A4-Figuras-3E"
figures.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(work / ".mpl-cache"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
from decode_vcd import read_vcd

source = work / "dados/medicoes"
evidence = work / "dados/testes-integrados"
labels = {"sensor": "Sensor PMS5003", "actuator": "Buzzer no GPIO21"}
routes = {"sensor": "Sensor PMS5003 até o cliente MQTT",
          "actuator": "Publicação MQTT até o buzzer"}
colors = {"sensor": "#106B70", "actuator": "#284F87"}
text_color = "#182B3B"
grid = "#DCE3E8"
step = 10_000_000

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def midpoint(lower, upper):
    return (Fraction(lower + upper, 2) + step // 2) // step * 10

def limits(lower, upper):
    return [lower // step * 10, -(-upper // step) * 10]

def pt(number):
    return f"{number:,}".replace(",", ".")

def save_plot(fig, name):
    fig.savefig(figures / (name + ".png"), dpi=300, facecolor="white")
    fig.savefig(figures / (name + ".svg"), facecolor="white")
    plt.close(fig)

raw = read_json(source / "medicoes.json")
summary = {}
table = ["| Núm. medida | Sensor/atuador | Tempo de resposta (ms) |",
         "| --- | --- | ---: |"]
for path, name in labels.items():
    measures = raw["measurements"][path]
    assert len(measures) == 4
    assert len({(m["client_id"], m["session"]) for m in measures}) == 4
    for i, item in enumerate(measures, 1):
        lower, upper = item["raw_latency_ns"]
        assert item["measurement"] == i and 0 <= lower <= upper and upper - lower <= 1_500_000_000
        interval = limits(lower, upper)
        estimate = midpoint(lower, upper)
        assert interval == item["report_latency_ms"] and estimate == item["midpoint_report_ms"]
        table.append(f"| {i} | {name} | {pt(estimate)} [{pt(interval[0])}–{pt(interval[1])}] |")
    lower = Fraction(sum(m["raw_latency_ns"][0] for m in measures), len(measures))
    upper = Fraction(sum(m["raw_latency_ns"][1] for m in measures), len(measures))
    mean_interval = limits(lower, upper)
    mean_estimate = midpoint(lower, upper)
    summary[path] = {"route": routes[path], "measurements": measures,
                     "mean_raw_bounds_ns": [str(lower), str(upper)],
                     "mean_interval_ms": mean_interval, "mean_estimate_ms": mean_estimate}
    table.append(f"| **Média** | **{name}** | **{pt(mean_estimate)} [{pt(mean_interval[0])}–{pt(mean_interval[1])}]** |")

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "text.color": text_color,
                     "axes.labelcolor": text_color, "xtick.color": text_color,
                     "ytick.color": text_color, "svg.fonttype": "path"})
fig, axes = plt.subplots(2, 1, figsize=(8.7, 5.8), sharex=True, layout="constrained")
for ax, (path, group) in zip(axes, summary.items()):
    ys = [4, 3, 2, 1, 0]
    intervals = [m["report_latency_ms"] for m in group["measurements"]] + [group["mean_interval_ms"]]
    estimates = [m["midpoint_report_ms"] for m in group["measurements"]] + [group["mean_estimate_ms"]]
    for y, (lo, hi), estimate in zip(ys, intervals, estimates):
        color = colors[path]
        ax.hlines(y, lo, hi, color=color, linewidth=3 if y == 0 else 1.8, alpha=1 if y == 0 else .76)
        ax.vlines([lo, hi], y - .13, y + .13, color=color, linewidth=1.3)
        ax.plot(estimate, y, marker="D" if y == 0 else "o", markersize=7 if y == 0 else 5.5,
                color=color, clip_on=False)
    ax.axhline(.52, color=grid, linewidth=.9)
    ax.set_title(group["route"], loc="left", fontweight="bold", fontsize=12, pad=9)
    ax.set_ylim(-.55, 4.55)
    ax.set_xlim(0, 2000)
    ax.set_yticks(ys, ["Medida 1", "Medida 2", "Medida 3", "Medida 4", "Média"])
    ax.get_yticklabels()[-1].set_fontweight("bold")
    ax.xaxis.set_major_locator(MultipleLocator(500))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: pt(int(x))))
    ax.grid(axis="x", color=grid, linewidth=.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", length=0, pad=6)
    for spine in ax.spines.values():
        spine.set_visible(False)
axes[-1].set_xlabel("Tempo de resposta (ms)")
save_plot(fig, "Grafico-1-Tempos-de-resposta")

attempt = source / "04"
analysis = read_json(attempt / "analise.json")
channels = read_vcd(attempt / "captura.vcd")
act = analysis["actuator"]
marker = act["vcd_marker_ns"]
rise = act["vcd_first_rise_ns"]
offset = (rise - marker) / 1_000_000
assert (marker, 1) in channels["ACT_MARK"] and (rise, 1) in channels["BUZZER"]
assert 3990 < act["frequency_hz"] < 4010 and 1 < offset < 2
fig, axes = plt.subplots(2, 1, figsize=(8.7, 3.65), sharex=True, layout="constrained")
for ax, channel, label, color in (
    (axes[0], "ACT_MARK", "GPIO4  Marcador", colors["sensor"]),
    (axes[1], "BUZZER", "GPIO21  Buzzer", colors["actuator"]),
):
    start, end = -0.25, 3.0
    edges = [((t - marker) / 1_000_000, value) for t, value in channels[channel]]
    initial = next(value for t, value in reversed(edges) if t < start)
    series = [(start, initial), *[(t, v) for t, v in edges if start <= t <= end]]
    series.append((end, series[-1][1]))
    x, y = zip(*series)
    ax.step(x, y, where="post", color=color, linewidth=1.9)
    for position in (0, offset):
        ax.axvline(position, color="#748492", linestyle=(0, (3, 3)), linewidth=1, zorder=0)
    ax.set_title(label, loc="left", fontsize=11.5, fontweight="bold")
    ax.set_yticks([0, 1])
    ax.set_ylim(-.16, 1.54)
    ax.set_xlim(start, end)
    ax.grid(axis="x", color=grid, linewidth=.7)
    ax.set_axisbelow(True)
    for side in ("right", "top"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(grid)
    ax.tick_params(length=0, pad=5)
axes[0].text(.14, .40, "Marcador do comando 4301", color=colors["sensor"])
axes[1].annotate("Primeira subida", xy=(offset, 1), xytext=(.37, 1.19),
                 arrowprops={"arrowstyle": "->", "color": colors["actuator"]}, color=colors["actuator"])
axes[-1].xaxis.set_major_locator(MultipleLocator(.5))
axes[-1].xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:g}".replace(".", ",")))
axes[-1].set_xlabel("Tempo simulado relativo ao marcador (ms)")
fig.supylabel("Nível lógico", fontsize=11)
save_plot(fig, "Figura-4-Pulso-GPIO21")

images = [
    ("13-antes-da-queda-wokwi.jpg", "Figura-1-Montagem-Wokwi.jpg",
     "Montagem em operação no Wokwi. O ESP32-S3 lê o PMS5003 simulado pela UART. "
     "O OLED mostra PM1.0, PM2.5 e PM10 de 10, 25 e 30 µg/m³, com estado NORMAL. "
     "A serial mostra o pacote de telemetria correspondente."),
    ("14-queda-com-alerta-local-wokwi.jpg", "Figura-2-Alerta-OLED.jpg",
     "Alerta local durante a falha simulada de comunicação. O OLED indica ALERTA com PM2.5 de 57 µg/m³ "
     "e a serial registra o buzzer ligado a 4 kHz e a falha de conexão TCP."),
    ("06-autoteste-sem-alerta-painel.jpg", "Figura-3-Telemetria-e-Comando.jpg",
     "Telemetria e comando no painel Node-RED. O ESP32 está online com PM2.5 de 25 µg/m³. "
     "O registro mostra envio, início e conclusão do comando 1793843075 na sessão 1. "
     "A saída voltou ao estado desligado ao terminar o autoteste."),
]
provenance = {}
for original, target, caption in images:
    copyfile(evidence / original, figures / target)
    case = original.rsplit("-", 1)[0] + ".json"
    provenance[target] = {"origin": f"dados/testes-integrados/{original}",
                          "record": f"dados/testes-integrados/{case}",
                          "sha256": digest(figures / target), "caption": caption}
provenance["Figura-4-Pulso-GPIO21.png"] = {
    "origin": "dados/medicoes/04/captura.vcd", "vcd_sha256": digest(attempt / "captura.vcd"),
    "command_id": act["id"], "client_id": analysis["client_id"], "session": analysis["session"],
    "marker_to_first_rise_ns": rise - marker
}
(out / "A4-Sintese-3E.json").write_text(json.dumps({
    "stage": "3E", "unit": "ms", "source": "dados/medicoes/medicoes.json",
    "source_sha256": digest(source / "medicoes.json"), "results": summary, "evidence": provenance,
    "version_sha256": {
        "firmware/medicao/sketch.ino": digest(work / "firmware/medicao/sketch.ino"),
        "firmware/demonstracao/sketch.ino": digest(work / "firmware/demonstracao/sketch.ino"),
        "firmware/teste-rede/sketch.ino": digest(evidence / "sketch-ensaio-rede.ino"),
        "node-red/flows.json": digest(work / "node-red/flows.json"),
    }
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

sensor = summary["sensor"]
actuator = summary["actuator"]
lines = [
    "# Resultados dos ensaios do sistema IoT A4",
    "",
    f"A média estimada do percurso do sensor PMS5003 até o cliente MQTT foi **{pt(sensor['mean_estimate_ms'])} ms**, "
    f"com intervalo de **{pt(sensor['mean_interval_ms'][0])} a {pt(sensor['mean_interval_ms'][1])} ms**. "
    f"Do envio do comando ao primeiro pulso do buzzer, a média estimada foi **{pt(actuator['mean_estimate_ms'])} ms**, "
    f"com intervalo de **{pt(actuator['mean_interval_ms'][0])} a {pt(actuator['mean_interval_ms'][1])} ms**. "
    "Os intervalos das médias se sobrepõem.",
    "",
    "## Tempos de resposta",
    "",
    "**Tabela 1 — Tempos de resposta nas quatro medições de cada percurso.**",
    "",
    *table,
    "",
    "Fonte — Ensaios do projeto no Wokwi, com firmware instrumentado `a4-3b-piloto`, broker público EMQX "
    "e cliente MQTT no computador. Cada linha mostra o ponto médio estimado seguido dos limites entre colchetes. "
    "A média usa os quatro pontos médios brutos, com o intervalo obtido pela média dos limites inferiores e dos superiores. "
    "O arredondamento foi feito ao final, em passos de 10 ms, com limites para fora. "
    "Os limites representam a incerteza da sincronização por sondas e o zero indica o limite inferior do intervalo.",
    "",
    "![Gráfico dos tempos do sensor e do buzzer com seus intervalos](A4-Figuras-3E/Grafico-1-Tempos-de-resposta.png)",
    "",
    "**Gráfico 1 — Tempos de resposta por medida.** Os círculos indicam os pontos médios, os losangos as médias "
    "e os traços horizontais os intervalos. Os dois painéis usam a mesma escala em milissegundos.",
    "",
    "## Funcionamento do protótipo",
    "",
]
for i, (_, target, caption) in enumerate(images, 1):
    lines.extend([f"![{caption}](A4-Figuras-3E/{target})", "", f"**Figura {i} —** {caption}", ""])
offset_text = f"{offset:.3f}".replace(".", ",")
lines.extend([
    "As figuras 1 e 2 vêm do ensaio de rede da etapa 3A, que usou o firmware `a4-2a-autoteste` "
    "com o controle de falha habilitado. A figura 3 vem do autoteste do firmware padrão com o painel da etapa 2B. "
    "As quatro sessões de medição usaram a variante instrumentada `a4-3b-piloto`.",
    "",
    "![Marcador do comando e início do trem de pulsos do buzzer](A4-Figuras-3E/Figura-4-Pulso-GPIO21.png)",
    "",
    "**Figura 4 — Primeiro pulso do autoteste remoto na tentativa 04.** Na captura VCD do comando 4301, "
    f"a primeira subida no GPIO21 aparece {offset_text} ms após o marcador local no GPIO4. "
    "O trem de pulsos foi verificado a 4 kHz. O eixo mostra tempo simulado relativo ao marcador. "
    "O percurso MQTT completo corresponde à linha 4 do buzzer na tabela.",
    "",
    "## Rastreabilidade",
    "",
    "Os registros brutos da etapa 3D acompanham o pacote. A síntese em JSON associa as linhas às sessões, às amostras, "
    "aos comandos e às capturas VCD. Ela também identifica os arquivos originais das figuras da etapa 3A. "
    "Os valores do piloto 3C ficam no respectivo relatório. Os resultados acima usam as oito medições aceitas da etapa 3D.",
    "",
])
(out / "A4-Resultados-3E.md").write_text("\n".join(lines), encoding="utf-8")
for path, group in summary.items():
    print(path, group["mean_estimate_ms"], group["mean_interval_ms"], group["mean_raw_bounds_ns"])
