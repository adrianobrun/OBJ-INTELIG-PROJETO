# Reprodução dos ensaios de tempo

Os registros da coleta estão em [`dados/medicoes/`](../dados/medicoes/), com uma pasta por sessão. Cada pasta conserva VCD, log MQTT, serial, associação dos eventos e decisão de aceitação. O [resultado consolidado](A4-Resultados-3E.md) usa as quatro medições do PMS5003 e as quatro do buzzer. Os dados de piloto e calibração ficam em [`dados/piloto/`](../dados/piloto/) e [`dados/calibracao/`](../dados/calibracao/).

## Coletar uma nova tentativa

1. Abra no Wokwi os cinco arquivos de [`firmware/medicao/`](../firmware/medicao/). O analisador lógico registra `PMS_TX` em D0, `BUZZER` em D1, `PMS_SAMPLE` (NC7) em D2, `ACT_MARK` (GPIO4) em D3 e `SYNC_MARK` (GPIO5) em D4. Mantenha PM2.5 em 20 µg/m³ e o modo de falha em 0.
2. Instale as dependências do cliente em um ambiente Python 3.13. Inicie a simulação e copie o `client_id` anunciado na serial. Execute os comandos abaixo na raiz do repositório, usando o ID real. Eles criam uma pasta nova para a tentativa.

```powershell
python -m pip install -r scripts/requirements.txt
New-Item -ItemType Directory -Force dados/novos-ensaios/05
New-Item -ItemType File dados/novos-ensaios/sem-log-externo.jsonl
python scripts/a4-3b-cliente.py calibrate --device ID_DO_ESP32 --id 4401 --pm25 40 --probes 160 --cadence-ms 250 --log dados/novos-ensaios/05/mqtt.jsonl
```

3. Depois de pelo menos três sondas respondidas e uma telemetria válida a 20 µg/m³ no log, mude PM2.5 para 40 µg/m³. O cliente registra a primeira amostra válida do novo patamar e envia um autoteste de 500 ms. Aguarde o registro de seis sondas posteriores ao comando.
4. Salve a serial do Wokwi em `dados/novos-ensaios/05/serial.txt`. Preserve o ID da conexão, os quadros imediatamente antes e depois da mudança, a amostra selecionada e o registro `PILOT ACT`. Pare a simulação para exportar o VCD e guarde-o como `dados/novos-ensaios/05/captura.vcd`. [Exportação do analisador lógico](https://docs.wokwi.com/parts/wokwi-logic-analyzer)
5. Execute a verificação da tentativa.

```powershell
python scripts/a4-3d-verificar.py dados/novos-ensaios/05 --pm25 40 --id 4401
```

## Associar eventos e calcular os limites

O início da medição do sensor é a borda do marcador de geração do quadro, logo antes do primeiro bit da UART. O fim é a entrada do callback MQTT do cliente para a mesma amostra. O intervalo inclui a UART e a espera até a publicação periódica. Para o buzzer, o início é o instante imediatamente anterior à chamada de publicação no cliente. O fim é a primeira subida elétrica simulada no GPIO21, identificada no VCD pelo marcador e pelo ID do autoteste.

Cada sonda registra a publicação e a recepção no relógio monotônico do computador e uma borda no GPIO5 do Wokwi. As sondas dos dois lados do evento delimitam seu instante no relógio do computador. Os extremos precisam estar associados na mesma sessão, sem ambiguidade, e a largura bruta de cada intervalo deve ser de até 1.500 ms. Os limites são arredondados para fora em passos de 10 ms. Os pontos médios servem de estimativa e as médias usam os valores brutos. Guarde as tentativas com perdas, duplicatas ou largura superior ao limite em pasta separada.

## Gerar os resultados

Execute os cinco comandos de análise no [README](../README.md) para reproduzir os dados consolidados. Com as dependências de Python instaladas, rode o gerador de figuras.

```powershell
python scripts/a4-3e-resultados.py
```

O script usa as oito medições já aceitas em `dados/medicoes/medicoes.json`. A tabela, a síntese e as figuras ficam em [`docs/`](./).
