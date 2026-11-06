# Modelo PMS5003 usado no Wokwi

O chip personalizado monta pacotes de 32 bytes com cabeçalho `42 4D`, comprimento 28 e checksum calculado sobre os primeiros 30 bytes. O ESP32 utiliza os campos atmosféricos PM1.0, PM2.5 e PM10, nos bytes 10 a 15, em µg/m³. A transmissão usa UART a 9600 bit/s, 8N1.

Os controles da simulação fornecem as três concentrações. A montagem fixa o período em 1.000 ms e o aquecimento em zero. O modelo limita PM1.0 a PM2.5 e eleva PM10 até PM2.5 quando o controle de PM10 fica abaixo dela. Por isso, algumas capturas mostram PM10 igual a PM2.5 mesmo com o controle de PM10 ajustado a 30.

| Controle | Comportamento |
| --- | --- |
| `pm1`, `pm25`, `pm10` | Ajustam os valores sintéticos das concentrações. |
| `intervalMs` | Define o intervalo entre pacotes. A coleta foi feita com 1.000 ms. |
| `fault=0` | Transmite pacotes válidos. |
| `fault=1` | Altera um bit do checksum para testar a rejeição no firmware. |
| `fault=2` | Suspende os pacotes para testar timeout e recuperação. |

Os campos CF1 acompanham as concentrações por padrão. Os campos de contagem de partículas são produzidos por fórmulas determinísticas do simulador. Os atributos opcionais podem fornecer outros valores para esses campos. O modelo também implementa os comandos UART E1, E2 e E4 e os sinais SET e RESET. A demonstração usa o modo ativo, com SET e RESET em nível alto, e lê apenas o TX do sensor.

Na variante de medição, NC7 alterna depois de montar cada pacote e imediatamente antes de iniciar sua transmissão. O analisador lógico registra esse sinal junto à UART. Os marcadores adicionais do ESP32 usam GPIO4 e GPIO5. A interpretação desses sinais está em [Reprodução dos ensaios de tempo](Reproduzir-medicoes.md).

As medidas registram o tempo de resposta deste protótipo simulado e do caminho MQTT utilizado. O código C e a definição JSON do modelo estão em cada uma das três pastas de [firmware](../firmware/).
