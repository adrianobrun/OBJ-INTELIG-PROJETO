# Registro das partidas do Wokwi

| Tentativa | Ocorrência antes do início das sondas |
| --- | --- |
| 01 | Sessão MQTT aberta na partida. O controle de PM2.5 voltou a 20 µg/m³ antes da coleta. |
| 02 | A primeira partida ficou em conexão Wi-Fi. Um reinício da simulação permitiu estabelecer a sessão. |
| 03 | O console exibiu `WiFi Internet error Event` antes da coleta. Após reinícios e recarga da página, as cinco fontes do circuito instrumentado foram recolocadas e conferidas no editor. A nova execução estabeleceu outra sessão e iniciou a medição. |
| 04 | O cliente recebeu telemetria da execução atual, mas a presença retida era a desconexão do ESP32 da tentativa 03. O cliente expirou aguardando o anúncio da sessão atual. A partida ficou excluída em `04/partida-mqtt.jsonl` e `04/partida.vcd`. O simulador foi parado e a coleta retomada após confirmar a desconexão no broker. |

As partidas sem sessão ocorreram antes do estímulo, das sondas e do comando. Nenhuma delas produziu uma medida.
