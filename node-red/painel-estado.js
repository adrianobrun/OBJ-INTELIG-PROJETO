// Corpo do nó Function do Node-RED.
const base = 'obj-intelig-projeto/a4/47db91f2';
const staleMs = 15000;
const now = Date.now();
const s = context.get('a4') || { broker: false, device: null, reading: null,
    received: 0, pending: null, lastId: 0, events: [], series: [], rejected: 0 };
const body = msg.payload;
const uint = (v, max = 4294967295) => Number.isInteger(v) && v >= 0 && v <= max;
const positive = v => uint(v) && v > 0;
const bool = v => typeof v === 'boolean';
const idOk = v => typeof v === 'string' && /^a4-47db91f2-[0-9a-f]{8}$/.test(v);
const pm = ['pm1', 'pm25', 'pm10'];
const logs = [];
let outgoing = null;

function log(state, data) {
    const row = { at: new Date(now).toISOString(), state, ...data };
    s.events = [row, ...s.events].slice(0, 10);
    logs.push({ payload: JSON.stringify(row) });
}
function clearPending(state) {
    if (!s.pending) return;
    const { id, client_id, session, duration_ms } = s.pending;
    log(state, { id, client_id, session, duration_ms });
    s.pending = null;
}
function resetReadings() {
    s.reading = null;
    s.received = 0;
    s.series = [];
}
function reject() {
    s.rejected++;
}
function isFresh() {
    return !!(s.broker && s.device?.online && s.received && now - s.received < staleMs);
}
function validReading(p) {
    if (p?.version !== 'a4-2a-autoteste' || !idOk(p.client_id)
        || !positive(p.seq) || !uint(p.uptime_ms) || p.unit !== 'ug/m3'
        || ![p.sample_valid, p.alert, p.test_active, p.buzzer_on].every(bool)) return false;
    if (p.sample_valid) {
        return positive(p.sample_seq) && pm.every(k => uint(p[k], 65535)) && p.alert === (p.pm25 > 50);
    }
    return p.sample_seq === null && pm.every(k => p[k] === null) && p.alert === false;
}

if (msg.status) {
    s.broker = msg.status.fill === 'green';
    if (!s.broker) {
        clearPending('connection_lost');
        s.device = null;
        resetReadings();
    }
} else if (msg.topic === base + '/status') {
    if (!idOk(body?.client_id) || !bool(body.online) || (body.online &&
        (!positive(body.session) || body.command_topic !== base + '/command/' + body.client_id + '-' + body.session))) {
        reject();
    } else if (body.online) {
        s.broker = true;
        if (!s.device?.online || s.device.client_id !== body.client_id || s.device.session !== body.session) {
            clearPending('session_changed');
            resetReadings();
        }
        s.device = { client_id: body.client_id, online: true, session: body.session, command_topic: body.command_topic, at: now };
    } else if (!s.device || s.device.client_id === body.client_id) {
        s.broker = true;
        clearPending('device_offline');
        s.device = { client_id: body.client_id, online: false, at: now };
        resetReadings();
    }
} else if (msg.topic === base + '/telemetry') {
    if (!validReading(body) || msg.retain === true) {
        reject();
    } else if (s.device?.online && s.device.client_id === body.client_id &&
               (!s.reading || body.seq > s.reading.seq)) {
        s.broker = true;
        s.reading = body;
        s.received = now;
        s.series = [...s.series, body.sample_valid ? body.pm25 : null].slice(-24);
    }
} else if (msg.topic === base + '/command-event') {
    if (!idOk(body?.client_id) || !positive(body.session) || !positive(body.id) ||
        !['started', 'finished', 'busy'].includes(body.state) || !uint(body.duration_ms, 1500) ||
        body.duration_ms < 100 || !uint(body.uptime_ms) || !bool(body.alert) ||
        !bool(body.buzzer_on) || msg.retain === true) {
        reject();
    } else if (s.device?.online && s.device.client_id === body.client_id && s.device.session === body.session) {
        const { id, client_id, session, state, duration_ms, uptime_ms, alert, buzzer_on } = body;
        log(state, { id, client_id, session, duration_ms, uptime_ms, alert, buzzer_on });
        if (s.pending?.id === id && s.pending.duration_ms === duration_ms && state !== 'started') s.pending = null;
    }
} else if (msg.topic === 'ui/test' && body === true) {
    if (isFresh() && !s.pending && !s.reading.test_active) {
        const id = Math.max(Math.floor(now / 1000), s.lastId + 1);
        if (positive(id)) {
            const { client_id, session, command_topic } = s.device;
            const duration_ms = 1000;
            s.lastId = id;
            s.pending = { id, client_id, session, duration_ms, at: now };
            outgoing = { topic: command_topic, payload: 'test,' + id + ',' + duration_ms, qos: 0, retain: false };
            log('sent', { id, client_id, session, duration_ms, topic: command_topic });
        }
    }
}

if (s.pending && now - s.pending.at >= staleMs) clearPending('no_reply');
const fresh = isFresh();
const reading = fresh ? s.reading : null;
const deviceState = !s.broker ? 'Sem ligação com o broker'
    : !s.device ? 'Aguardando dispositivo'
    : !s.device.online ? 'Desconectado'
    : fresh ? 'Online'
    : now - (s.received || s.device.at) >= staleMs ? 'Sem telemetria recente'
    : 'Aguardando telemetria';
context.set('a4', s);
return [{ payload: {
    broker: s.broker, deviceState, clientId: s.device?.client_id, session: s.device?.session,
    reading, age: s.received ? Math.floor((now - s.received) / 1000) : null,
    canTest: fresh && !s.pending && !reading.test_active,
    pending: s.pending?.id, events: s.events, series: s.series, rejected: s.rejected
} }, outgoing, logs.length ? logs : null];
