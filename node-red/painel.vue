<template>
  <main class="pm-air" v-if="view">
    <header class="pm-intro">
      <div><span class="pm-tag">MONITORAMENTO DE PARTÍCULAS</span>
      <h1>Qualidade do ar</h1><p>ESP32-S3 · PMS5003 · MQTT</p></div>
      <div class="pm-network" aria-live="polite">
        <span>Broker {{ view.broker ? 'conectado' : 'desconectado' }}</span>
        <strong :class="view.reading ? 'pm-good' : 'pm-warn'">ESP32 · {{ view.deviceState }}</strong>
      </div>
    </header>
    <section class="pm-metrics" aria-label="Concentração de partículas">
      <article v-for="metric in metrics" :key="metric.key" class="pm-box" :class="{ 'pm-alert': metric.key === 'pm25' && view.reading?.alert }">
        <span>{{ metric.label }}</span>
        <div><strong>{{ view.reading?.[metric.key] ?? '—' }}</strong> <small>µg/m³</small></div>
      </article>
    </section>
    <section class="pm-box pm-status" aria-label="Estado atual" aria-live="polite">
      <span>Amostra <strong>{{ view.reading ? (view.reading.sample_valid ? 'Válida' : 'Sem leitura válida') : 'Indisponível' }}</strong></span>
      <span>Alerta <strong>{{ view.reading?.sample_valid ? (view.reading.alert ? 'Ativo' : 'Normal') : '—' }}</strong></span>
      <span>Buzzer <strong>{{ view.reading ? (view.reading.buzzer_on ? 'Ligado' : 'Desligado') : '—' }}</strong></span>
      <span>Autoteste <strong>{{ view.reading ? (view.reading.test_active ? 'Em execução' : 'Inativo') : '—' }}</strong></span>
      <span>Última telemetria <strong>{{ view.age === null ? '—' : 'há ' + view.age + ' s' }}</strong></span>
    </section>
    <div class="pm-lower">
      <section class="pm-box">
        <h2>Histórico de PM2.5</h2>
        <p>Últimos 24 envios da sessão · Alerta acima de 50 µg/m³</p>
        <svg v-if="view.series.some(v => v !== null)" class="pm-chart" viewBox="0 0 480 118" role="img"
             :aria-label="'Histórico de PM2.5, escala de 0 a ' + top + ' microgramas por metro cúbico'">
          <path d="M34 9 V104 H472" fill="none" stroke="#9cabb5"/>
          <path :d="'M34 ' + y(50) + ' H472'" stroke="#ad531e" stroke-dasharray="4 4"/>
          <text x="30" y="12" text-anchor="end">{{ top }}</text>
          <text x="30" y="107" text-anchor="end">0</text>
          <text x="36" :y="y(50)-3" fill="#ad531e">50</text>
          <path :d="trend" fill="none" stroke="#087263" stroke-width="2"/>
          <circle v-for="point in points" :key="point.x" :cx="point.x" :cy="point.y" r="2.8" fill="#087263"/>
        </svg>
        <p v-else class="pm-empty">Aguardando amostras válidas.</p>
      </section>
      <section class="pm-box">
        <div class="pm-action">
          <h2>Comando do buzzer</h2>
          <button type="button" :disabled="!view.canTest" @click="send({payload:true})">Testar buzzer · 1 s</button>
        </div>
        <p v-if="view.pending" role="status">Aguardando confirmação do ID {{ view.pending }}.</p>
        <p v-else>Teste remoto de 1 segundo. O alerta local continua ativo se PM2.5 estiver acima de 50.</p>
        <ol v-if="view.events.length" class="pm-events" aria-label="Registro de comandos">
          <li v-for="(event, i) in view.events" :key="event.at + '-' + i">
            <time :datetime="event.at">{{ time(event.at) }}</time>
            <strong>{{ eventName(event.state) }}</strong>
            <span>ID {{ event.id }} · sessão {{ event.session }}</span>
          </li>
        </ol>
        <p v-else class="pm-empty">Nenhum comando registrado nesta execução.</p>
      </section>
    </div>
    <footer>Ambiente de demonstração · EMQX público · 15 s sem telemetria desabilitam o comando</footer>
  </main>
  <p v-else role="status">Carregando painel de qualidade do ar…</p>
</template>
<script>
export default {
  data() { return { metrics: [{key:'pm1',label:'PM1.0'}, {key:'pm25',label:'PM2.5'}, {key:'pm10',label:'PM10'}] } },
  computed: {
    view() { return this.msg?.payload },
    top() { return Math.max(60, Math.ceil(Math.max(...this.view.series) / 10) * 10) },
    points() { return this.view.series.flatMap((v, i) => v === null ? [] : [{x: this.x(i), y: this.y(v)}]) },
    trend() { return this.view.series.map((v, i, a) => v === null ? '' :
      (i === 0 || a[i-1] === null ? 'M' : 'L') + this.x(i) + ' ' + this.y(v)).join(' ') }
  },
  methods: {
    x(i) { return 37 + 18.7*i },
    y(v) { return 104 - 95*v/this.top },
    time(value) { return new Date(value).toLocaleTimeString('pt-BR', {hour12:false}) },
    eventName(value) {
      return ({sent:'Enviado',started:'Iniciado',finished:'Concluído',busy:'Ocupado',no_reply:'Sem resposta',
        connection_lost:'Broker caiu',device_offline:'ESP32 desconectou',session_changed:'Sessão mudou'})[value] ?? value
    }
  }
}
</script>
<style>
.pm-air { color:#193239; background:#eff5f3; padding:clamp(12px,2vw,24px); border-radius:16px; display:grid; gap:14px; }
.pm-intro { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px; background:#153d3a; color:#fff; border-radius:12px; padding:18px 22px; }
.pm-intro h1 { margin:3px 0; font-size:clamp(1.5rem,3vw,2.4rem); line-height:1.2; }
.pm-intro p,.pm-tag { color:#bee4dc; }
.pm-tag { font-size:.73rem; font-weight:700; letter-spacing:.1em; }
.pm-network { display:grid; gap:4px; color:#e0efed; }
.pm-good { color:#9aedd6; }
.pm-warn { color:#ffdcaa; }
.pm-metrics,.pm-lower { display:grid; gap:12px; grid-template-columns:repeat(3,minmax(0,1fr)); }
.pm-lower { grid-template-columns:repeat(2,minmax(0,1fr)); }
.pm-box { background:#fff; border:1px solid #d7e5df; border-radius:12px; padding:14px; min-width:0; }
.pm-metrics strong { font-size:clamp(1.35rem,3vw,2.2rem); font-variant-numeric:tabular-nums; }
.pm-metrics small,.pm-lower p,.pm-status span,.pm-air footer { color:#496468; }
.pm-metrics .pm-alert { background:#fff2e6; border-color:#cc8455; }
.pm-status { display:flex; flex-wrap:wrap; gap:8px 22px; }
.pm-status strong { color:#193239; margin-left:3px; }
.pm-air h2 { font-size:1.05rem; margin:0 0 4px; }
.pm-chart { display:block; width:100%; height:auto; max-height:136px; margin-top:6px; }
.pm-chart text { font-size:9px; }
.pm-action { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-bottom:6px; }
.pm-action button { background:#00685c; color:#fff; border-radius:7px; padding:7px 11px; font-weight:700; }
.pm-action button:disabled { background:#e6eeec; color:#4e6462; cursor:not-allowed; }
.pm-action button:focus-visible { outline:2px solid #193239; outline-offset:2px; }
.pm-events { padding:0; list-style:none; margin:8px 0 0; max-height:145px; overflow:auto; }
.pm-events li { display:flex; flex-wrap:wrap; gap:4px 10px; padding:4px 0; border-top:1px solid #e6efeb; font-size:.86rem; }
.pm-events time { font-variant-numeric:tabular-nums; }
.pm-empty { margin-top:12px; }
.pm-air footer { font-size:.8rem; }
@media(max-width:760px) { .pm-lower { grid-template-columns:1fr; } }
@media(max-width:410px) { .pm-air { padding:7px; } .pm-metrics { gap:4px; } .pm-metrics .pm-box { padding:7px; } }
</style>
