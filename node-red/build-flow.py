from pathlib import Path
import json

here = Path(__file__).resolve().parent
prefix = "obj-intelig-projeto/a4/47db91f2"
tab = "a400000000000001"
ids = {name: f"a4000000000000{i:02x}" for i, name in enumerate(
    ("broker", "base", "theme", "page", "group", "status", "telemetry", "event", "conn",
     "tick", "logic", "widget", "button", "publish", "file", "comment"), start=2)}
nodes = [{"id": tab, "type": "tab", "label": "A4 · Qualidade do ar", "disabled": False,
          "info": "ESP32-S3 no Wokwi. MQTT público EMQX. Painel FlowFuse em /painel/ar."}]

def config(key, kind, **opts):
    nodes.append({"id": ids[key], "type": kind, **opts})

def node(key, kind, x, y, wires, **opts):
    nodes.append({"id": ids[key], "type": kind, "z": tab, **opts,
                  "x": x, "y": y, "wires": [[ids[dest] for dest in route] for route in wires]})

config("broker", "mqtt-broker", name="EMQX público · demonstração", broker="broker.emqx.io", port="1883",
       clientid="", autoConnect=True, usetls=False, protocolVersion="4", keepalive="30", cleansession=True)
config("base", "ui-base", name="Projeto A4", path="/painel", appIcon="", includeClientData=False,
       acceptsClientConfig=["ui-notification", "ui-control"], showPathInSidebar=False, headerContent="page",
       navigationStyle="default", titleBarStyle="default", showReconnectNotification=True, showDisconnectNotification=True,
       allowInstall=False)
config("theme", "ui-theme", name="Qualidade do ar",
       colors=dict(surface="#ffffff", primary="#00685c", bgPage="#eff5f3", groupBg="#ffffff", groupOutline="#d7e5df"),
       sizes=dict(density="default", pagePadding="12px", groupGap="12px", groupBorderRadius="12px", widgetGap="12px"))
config("page", "ui-page", name="Projeto A4", ui=ids["base"], path="/ar", icon="air-filter", layout="grid",
       theme=ids["theme"], order=1, className="", visible=True, disabled=False,
       breakpoints=[dict(name=n, px=p, cols=c) for n,p,c in
                    [("Default",0,3),("Tablet",576,6),("Small Desktop",768,9),("Desktop",1024,12)]])
config("group", "ui-group", name="Qualidade do ar", page=ids["page"], width=12, height=1, order=1,
       showTitle=False, className="", visible=True, disabled=False, groupType="default")

for i, (key, topic, name) in enumerate([
    ("status", "status", "Presença e sessão"), ("telemetry", "telemetry", "Concentrações e estados"),
    ("event", "command-event", "Eventos do buzzer")
]):
    node(key, "mqtt in", 175, 140+i*55, [["logic"]], name=name, topic=f"{prefix}/{topic}", qos="0",
         datatype="auto-detect", broker=ids["broker"], nl=False, rap=True, rh=0, inputs=0)
node("conn", "status", 175, 305, [["logic"]], name="Conexão do broker", scope=[ids["status"]])
node("tick", "inject", 170, 360, [["logic"]], name="Idade da telemetria", props=[{"p":"topic","vt":"str"}],
     repeat="1", crontab="", once=True, onceDelay=0.2, topic="tick")
node("logic", "function", 485, 230, [["widget"], ["publish"], ["file"]], name="Validar, atualizar e comandar",
     func=(here/"painel-estado.js").read_text(encoding="utf-8"), outputs=3, timeout=0,
     noerr=0, initialize="", finalize="", libs=[])
node("widget", "ui-template", 825, 160, [["button"]], name="Painel de qualidade do ar", group=ids["group"],
     page="", ui="", order=1, width=12, height=0, head="", format=(here/"painel.vue").read_text(encoding="utf-8"),
     storeOutMessages=False, passthru=False, resendOnRefresh=True, templateScope="local", className="")
node("button", "change", 485, 350, [["logic"]], name="Pedido de autoteste",
     rules=[dict(t="delete",p="status",pt="msg"),dict(t="set",p="topic",pt="msg",to="ui/test",tot="str")],
     action="", property="", from_="", to="", reg=False)
node("publish", "mqtt out", 835, 230, [], name="Autoteste no tópico da sessão", topic="", qos="0",
     retain="false", respTopic="", contentType="", userProps="", correl="", expiry="", broker=ids["broker"])
node("file", "file", 825, 295, [], name="Histórico de comandos (JSONL)", filename="a4-comandos.jsonl",
     filenameType="str", appendNewline=True, createDir=False, overwriteFile="false", encoding="none")
node("comment", "comment", 190, 75, [], name="A4 · Telemetria e controle remoto",
     info="Importe em Node-RED com @flowfuse/node-red-dashboard instalado. O histórico de comandos é escrito no diretório de execução.")

data = json.dumps(nodes, ensure_ascii=False, indent=2) + "\n"
(here / "flows.json").write_text(data, encoding="utf-8")
