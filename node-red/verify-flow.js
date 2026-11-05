const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const here = __dirname;
const raw = fs.readFileSync(path.join(here, 'flows.json'), 'utf8');
const nodes = JSON.parse(raw);
const func = nodes.find(n => n.type === 'function');
assert.equal(func.func, fs.readFileSync(path.join(here, 'painel-estado.js'), 'utf8').replace(/\r\n/g, '\n'));
assert.equal(nodes.find(n => n.type === 'ui-template').format, fs.readFileSync(path.join(here, 'painel.vue'), 'utf8').replace(/\r\n/g, '\n'));
const step = new Function('msg', 'context', 'Date', func.func);
let now = 1793842100000;
let state;
class Clock extends Date { static now() { return now; } }
const context = { get: () => state, set: (_key, v) => { state = v; } };
const base = 'obj-intelig-projeto/a4/47db91f2';
const client_id = 'a4-47db91f2-1234abcd';
const session = 1;
const command_topic = base + '/command/' + client_id + '-' + session;
const input = (name, payload, extra) => step({topic: base + '/' + name, payload, ...extra}, context, Clock);
const tick = () => step({topic:'tick'}, context, Clock)[0].payload;
const click = () => step({topic:'ui/test',payload:true}, context, Clock);

input('status', {client_id, session, command_topic: 'other/topic', online:true});
assert.equal(tick().canTest, false);
input('status', {client_id, session, command_topic, online:true});
const sample = { version:'a4-2a-autoteste', client_id, seq:1, uptime_ms:5000, unit:'ug/m3',
    sample_seq:5, pm1:10, pm25:25, pm10:30, sample_valid:true, alert:false, test_active:false, buzzer_on:false };
input('telemetry', sample, {retain:false});
assert.equal(tick().reading.pm25, 25);
assert.equal(tick().canTest, true);
now += 14999;
input('telemetry', '{"pm25":');
input('telemetry', {...sample, seq:2, pm25:'51'});
input('telemetry', {...sample, seq:3, pm25:51, alert:false});
input('telemetry', {...sample, seq:4}, {retain:true});
input('telemetry', sample); // Replay de sequência: não renova a idade.
assert.equal(tick().rejected, 5);
assert.equal(tick().reading.pm25, 25);
assert.equal(tick().age, 14);
now++;
assert.equal(tick().deviceState, 'Sem telemetria recente');
assert.equal(tick().reading, null);
assert.equal(click()[1], null);

input('telemetry', {...sample, seq:5, sample_valid:false, sample_seq:null, pm1:null, pm25:null, pm10:null});
assert.equal(tick().deviceState, 'Online');
assert.equal(tick().reading.sample_valid, false);
const [ui, out, logs] = click();
assert.equal(out.topic, command_topic);
assert.equal(out.retain, false);
assert.equal(out.qos, 0);
assert.equal(out.payload, 'test,' + ui.payload.pending + ',1000');
assert.equal(JSON.parse(logs[0].payload).state, 'sent');
assert.equal(click()[1], null);
input('status', {client_id, online:false}, {retain:true});
assert.equal(tick().deviceState, 'Desconectado');
assert.equal(tick().canTest, false);
console.log('O fluxo contém as fontes do painel. Validação, expiração aos 15 s, amostra inválida e bloqueio do comando verificados.');
