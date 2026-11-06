# Protocolo MQTT e ensaios de falha

O firmware usa MQTT 3.1.1 sobre TCP/IP em `broker.emqx.io:1883`. Os tópicos abaixo são relativos ao prefixo `obj-intelig-projeto/pm/47db91f2`. O broker é público e a porta 1883 usa TCP sem criptografia. A demonstração trafega apenas valores simulados e comandos de autoteste. [EMQX público](https://www.emqx.com/en/mqtt/public-mqtt5-broker)

| Tópico | Origem | QoS e retenção |
| --- | --- | --- |
| `/status` | ESP32-S3 anuncia presença e tópico da sessão. Em uma queda, o broker publica o Last Will. | Presença QoS 0 e Last Will QoS 1. Ambas retidas. |
| `/telemetry` | ESP32-S3 publica leituras e estado da saída a cada 5 s. | QoS 0, sem retenção. |
| `/command/<client_id>-<sessão>` | Node-RED ou cliente de ensaio publica um autoteste. | QoS 0, sem retenção. |
| `/command-event` | ESP32-S3 publica `started`, `finished` ou `busy`. | QoS 0, sem retenção. |
| `/pilot-sync` | A variante de medição devolve a janela do relógio do ESP32 após uma sonda `sync,ID`. | QoS 0, sem retenção. |

O anúncio abaixo associa o dispositivo a um tópico de comando. Após a reconexão, o firmware incrementa a sessão, anuncia um tópico novo e reinicia a sequência de IDs de comando.

```json
{"client_id":"pm-47db91f2-69429b3a","online":true,"session":1,"command_topic":"obj-intelig-projeto/pm/47db91f2/command/pm-47db91f2-69429b3a-1"}
```

O Last Will anuncia a perda da conexão.

```json
{"client_id":"pm-47db91f2-69429b3a","online":false}
```

Uma mensagem de telemetria indica a sequência da publicação (`seq`), a sequência da amostra (`sample_seq`), as três concentrações e o estado da saída.

```json
{"version":"pm-autoteste","client_id":"pm-47db91f2-69429b3a","seq":5,"uptime_ms":23292,"unit":"ug/m3","sample_seq":23,"pm1":10,"pm25":25,"pm10":30,"sample_valid":true,"alert":false,"test_active":false,"buzzer_on":false}
```

Após 5 s sem pacote válido, o ESP32 publica `sample_valid:false` e deixa `sample_seq`, `pm1`, `pm25` e `pm10` como `null`. O painel mostra **Sem leitura válida** enquanto recebe mensagens do ESP32. Depois de 15 s sem telemetria recente, oculta os valores e desabilita o comando.

O payload do autoteste é `test,ID,DURACAO_MS`. Os IDs são inteiros positivos e crescentes dentro da sessão. O firmware aceita durações de 100 a 1.500 ms. Um autoteste pode manter o buzzer ligado durante seu intervalo. Ao terminar, o estado volta a depender da validade da amostra e do limiar de PM2.5.

```text
test,1793842074,1000
```

```json
{"client_id":"pm-47db91f2-69429b3a","session":1,"id":1793842074,"state":"finished","duration_ms":1000,"uptime_ms":11973,"alert":false,"buzzer_on":false}
```

## Falha controlada de rede

Carregue os cinco arquivos de [`firmware/teste-rede/`](../firmware/teste-rede/) no Wokwi. Envie `R` pela serial para liberar o broker após a partida. Após receber telemetria, use `X` para fechar o TCP e direcionar as novas tentativas a um endereço de teste. Ajuste o PM2.5 enquanto a rede está indisponível e compare o OLED e o buzzer com o estado offline no painel. Envie `R` para restaurar o destino e aguarde o tópico da nova sessão.

Se o Wokwi permanecer na conexão Wi-Fi, reinicie o simulador e confirme `MQTT CONNACK OK` na serial. Se um ensaio receber telemetria de um dispositivo novo enquanto a presença retida ainda indica a desconexão da sessão anterior, pare a simulação e aguarde a confirmação de desconexão antes de abrir a próxima sessão. Essa ocorrência e os dados da partida excluída estão em [`dados/medicoes/partidas.md`](../dados/medicoes/partidas.md).

As capturas e os logs do ensaio funcional estão em [`dados/testes-integrados/`](../dados/testes-integrados/). O diagnóstico anterior ao uso do EMQX está em [`Diagnostico-Brokers.md`](Diagnostico-Brokers.md).
