# Validação da cópia exportada · 05/11/2026

A etapa 4B partiu da extração de `A4-Pacote-Repositorio-4A.zip`. Os cinco arquivos de `firmware/demonstracao/` foram colados nas abas do Wokwi e conferidos por cópia integral do editor. O Node-RED usou o `flows.json` extraído, sem alterações no fluxo ou no firmware.

## Instalação e execução

Ambiente: Python 3.13, Node.js 24.22.1, pnpm 11.25.0, Node-RED 4.1.6, FlowFuse Dashboard 1.32.0, Arduino-ESP32 3.3.12 e ESP-IDF 5.5.5. As bibliotecas do firmware estão fixadas em `libraries.txt`.

A primeira instalação baixou as 347 dependências, mas o pnpm retornou erro por exigir decisão explícita sobre o pós-instalação do `core-js`. Foi acrescentado `allowBuilds: { core-js: false }` em `node-red/pnpm-workspace.yaml` e fixado o gerenciador em `package.json`. A instalação passou com código de saída 0. Uma segunda pasta, inicialmente sem `node_modules`, também instalou os 347 pacotes com `pnpm install --offline --frozen-lockfile`, usando o cache da primeira instalação. [Configuração de scripts do pnpm](https://pnpm.io/settings/build).

Como a porta 1889 estava ocupada pela sessão anterior, a cópia isolada executou:

```powershell
Set-Location node-red
pnpm install --frozen-lockfile
pnpm exec node-red --userDir . --settings settings.js --port 1891
```

O runtime carregou todos os nós, iniciou o Dashboard em `/painel`, abriu o painel em `http://127.0.0.1:1891/painel/ar` e registrou conexão com `mqtt://broker.emqx.io:1883`. O arquivo extraído é carregado pelo `userDir`, equivalente ao conteúdo do fluxo exportado. A verificação `node node-red/verify-flow.js` conferiu as fontes embutidas, validação, expiração em 15 s, amostra inválida e bloqueio de comando. A edição de paleta ficou indisponível nesse runtime por ausência de npm em seu PATH; as dependências fixadas foram instaladas pelo pnpm.

## Casos observados

| Caso | Resultado |
| --- | --- |
| PM2.5 a 25 µg/m³ | Leitura recebida, estado normal e buzzer desligado. |
| PM2.5 a 50 µg/m³ | Leitura recebida, estado normal e buzzer desligado. |
| PM2.5 a 51 µg/m³ | Alerta ativo e buzzer ligado. |
| Retorno a 25 µg/m³ e autoteste | ID `1793860760`, sessão 1: envio no painel, início e conclusão no ESP32 e no painel. |
| Falha 1: checksum | Quadros rejeitados; após expirar, painel sem leitura válida e ESP32 online. |
| Falha 2: ausência de quadros | Painel sem leitura válida com comunicação MQTT ativa. |
| Falha 0: recuperação | Leitura válida a 25 µg/m³ e operação normal restauradas. |

O dispositivo deste ensaio foi `a4-47db91f2-ee0f5367`. O firmware registrou início do autoteste em `153933 ms` e conclusão em `154933 ms`, diferença de 1.000 ms no relógio simulado. Este valor confirma a duração do teste; as latências do projeto continuam sendo as quatro medições de cada percurso documentadas em [Resultados](A4-Resultados-3E.md).

Os [registros da validação](../dados/validacao-4b/) incluem o MQTT recebido por assinante independente, o log dos comandos do Node-RED, capturas e estados das duas interfaces. As evidências de checksum e ausência foram mantidas em registros separados. Os testes completos da integração e as oito medições anteriores foram preservados.

## Conteúdo publicado

O pacote contém código, montagem, bibliotecas, fontes do chip, fluxo, scripts, dados simulados e documentação. Arquivos de runtime do Node-RED, dependências instaladas, caches e credenciais locais ficam fora do pacote. Não há usuário, senha ou chave de serviço na configuração. O broker é público e os tópicos são acessíveis por outros clientes; a limitação está descrita no README e no diagnóstico.

O arquivo `SHA256SUMS.txt` permite comparar os arquivos publicados com a versão validada. A versão final de publicação e o resultado da leitura pública sem autenticação ficam registrados no relatório externo da etapa 4B, para evitar autorreferência do hash do commit.
