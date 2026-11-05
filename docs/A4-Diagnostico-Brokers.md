# Diagnóstico dos brokers MQTT da A4

**4 de novembro de 2026** · Teste comparativo entre `test.mosquitto.org` e `broker.emqx.io`

O endereço público do Mosquitto resolveu no DNS, mas as tentativas na porta 1883 expiraram durante a abertura da conexão TCP. O EMQX abriu a conexão na mesma porta e aceitou a sessão MQTT 3.1.1. A diferença se repetiu no computador e em duas rodadas executadas com o mesmo firmware de diagnóstico no ESP32-S3 do Wokwi.

| Origem | `test.mosquitto.org:1883` | `broker.emqx.io:1883` |
| --- | --- | --- |
| Computador, IPv4 | `54.36.178.49` · 3 de 3 tentativas TCP expiraram após 6 s | `34.243.217.54` e `44.232.241.40` · 3 sessões MQTT aceitas por endereço, 6 de 6 no total |
| Wokwi, gateway público | `54.36.178.49` · 2 de 2 tentativas TCP expiraram em 6.004 ms | `44.232.241.40` · 2 de 2 conexões TCP em 250 ms, seguidas de confirmação MQTT |

Os clientes chegaram a enviar o pacote MQTT `CONNECT` somente depois que o TCP abriu. A falha da porta 1883 do Mosquitto ocorreu, portanto, antes de o broker poder avaliar a versão MQTT, o identificador do cliente ou os tópicos. O computador também registrou um timeout TCP na porta 1883 via IPv6.

## Testes complementares

O mesmo IPv4 do Mosquitto aceitou TCP e TLS nas portas 443 e 8886. Na porta 8886, anunciada para MQTT com TLS, a conexão foi encerrada após o envio do `CONNECT`, sem resposta `CONNACK`. A confirmação de TLS na porta 443 testa a disponibilidade daquele caminho até o endereço. A página do serviço também estava acessível via HTTPS. [Portas do servidor público Mosquitto](https://test.mosquitto.org/)

Em 1º de novembro, um usuário relatou falhas na porta 1883 a partir da China e dos Estados Unidos no repositório do projeto Mosquitto. O relato é compatível com os testes da A4. A causa interna da indisponibilidade da porta permanece sem confirmação pública. Os testes externos não distinguem entre uma falha no serviço que atende a porta e um filtro de rede no caminho até ele. [Relato no repositório oficial](https://github.com/eclipse-mosquitto/mosquitto/issues/3784)

## Reprodução

- No computador, rode `python -u scripts/diagnostico-brokers.py` com acesso à internet. O script tenta abrir TCP e envia apenas um `CONNECT` MQTT 3.1.1 nas portas MQTT que respondem. Os resultados estão em `dados/diagnostico/diagnostico-brokers-pc.jsonl`.
- No Wokwi, substitua temporariamente a função `networkTask` da versão em `dados/diagnostico/firmware-a4-1a-mqtt/` pelo trecho `dados/diagnostico/diagnostico-brokers-network-task.ino.txt`. Inicie a simulação e aguarde `DIAG DONE` na serial. Os registros do teste estão em `dados/diagnostico/diagnostico-brokers-wokwi.txt`.
