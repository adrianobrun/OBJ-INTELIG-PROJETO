# Plano A4 · coleta das medições

**4 de novembro de 2026 · etapa 3D concluída.** Foram aceitas quatro medições do sensor e quatro do buzzer, em quatro sessões do Wokwi. As 184 sondas das sessões aceitas tiveram respostas correspondentes e as oito larguras brutas ficaram abaixo de 1.500 ms.

A coleta usa o firmware instrumentado `a4-3b-piloto` e o critério da etapa 3C. Em cada tentativa, o PMS5003 começou com PM2.5 de 20 µg/m³. O cliente MQTT confirmou a leitura inicial, enviou sondas com cadência nominal de 250 ms e registrou o primeiro pacote no novo patamar. Com o buzzer desligado e o alerta normal, o mesmo cliente enviou um autoteste de 500 ms. O ESP32 manteve a telemetria periódica de 5 s.

O percurso do sensor vai da geração do quadro correspondente na UART à entrada no callback MQTT. O percurso do atuador vai da chamada de publicação ao primeiro pulso no GPIO21. A captura do Wokwi associa o quadro e o pulso aos IDs do log. As sondas delimitam os instantes da captura no relógio do computador. Cada percurso é aceito com intervalo bruto de até 1.500 ms de largura.

| Tentativa | PM2.5 (µg/m³) | Amostra / seq MQTT | Sensor → cliente (ms) | Comando | Comando → GPIO21 (ms) |
| --- | ---: | --- | ---: | ---: | ---: |
| 01 | 28 | 81 / 16 | 790–1.860 | 4001 | 0–1.150 |
| 02 | 33 | 48 / 8 | 230–1.100 | 4101 | 0–800 |
| 03 | 38 | 63 / 13 | 470–1.320 | 4201 | 0–910 |
| 04 | 45 | 46 / 6 | 540–1.480 | 4301 | 0–1.110 |

Os limites foram arredondados para fora em passos de 10 ms. O zero é o limite inferior dos intervalos do atuador. A maior largura bruta foi de aproximadamente 1.143 ms.

Houve reinícios do Wokwi antes da coleta para restabelecer o Wi-Fi. Uma partida da tentativa 04 foi excluída porque o broker retornou a desconexão da execução anterior como presença retida enquanto a telemetria já vinha do novo dispositivo. O cliente expirou antes de publicar sondas ou comando. O VCD e o log dessa partida foram guardados em separado. A tentativa 04 aceita começou após a confirmação da desconexão e o anúncio da nova sessão. As ocorrências de partida estão em `dados/medicoes/partidas.md`.

O arquivo `dados/medicoes/medicoes.json` relaciona os extremos de cada medida, a unidade de tempo, a versão, os IDs e as evidências. A pasta numerada de cada tentativa contém VCD, log MQTT, serial, associação dos eventos, intervalos brutos e decisão de aceitação. `SHA256SUMS.txt` permite conferir as fontes e os registros.

Para reproduzir a análise após descompactar o pacote, use a raiz do pacote como pasta de trabalho e execute os comandos abaixo. A primeira linha exemplifica a tentativa 01. Substitua a pasta, a concentração e o ID pelos valores da tentativa que deseja conferir.

```text
python scripts/a4-3d-verificar.py dados/medicoes/01 --pm25 28 --id 4001
python scripts/a4-3d-reunir.py
```

A etapa **3E** prepara a tabela de entrega, calcula as médias com seus intervalos e gera os gráficos a partir destas oito medições.
