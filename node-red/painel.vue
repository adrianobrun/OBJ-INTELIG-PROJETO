<template>
  <main class="a4-air" v-if="view">
    <header class="a4-intro">
      <div><span class="a4-tag">A4 · OBJETOS INTELIGENTES</span>
      <h1>Qualidade do ar</h1><p>ESP32-S3 · PMS5003 · MQTT</p></div>
      <div class="a4-network" aria-live="polite">
        <span>Broker {{ view.broker ? 'conectado' : 'desconectado' }}</span>
        <strong :class="view.reading ? 'a4-good' : 'a4-warn'">ESP32 · {{ view.deviceState }}</strong>
      </div>
    </header>
    <section class="a4-metrics" aria-label="Concentração de partículas">
      <article v-for="metric in metrics" :key="metric.key" class="a4-box" :class="{ 'a4-alert': metric.key === 'pm25' && view.reading?.alert }">
        <span>{{ metric.label }}</span>
        <div><strong>{{ view.reading?.[metric.key] ?? '—' }}</strong> <small>µg/m³</small></div>
      </article>
    </section>
    <section class="a4-box a4-status" aria-label="Estado atual" aria-live="polite">
      <span>Amostra <strong>{{ view.reading ? (view.reading.sample_valid ? 'Válida' : 'Sem leitura válida') : 'Indisponível' }}</strong></span>
      <span>Alerta <strong>{{ view.reading?.sample_valid ? (view.reading.alert ? 'Ativo' : 'Normal') : '—' }}</strong></span>
      <span>Buzzer <strong>{{ view.reading ? (view.reading.buzzer_on ? 'Ligado' : 'Desligado') : '—' }}</strong></span>
      <span>Autoteste <strong>{{ view.reading ? (view.reading.test_active ? 'Em execução' : 'Inativo') : '—' }}</strong></span>
      <span>Última telemetria <strong>{{ view.age === null ? '—' : 'há ' + view.age + ' s' }}</strong></span>
    </section>
    <div class="a4-lower">
      <section class="a4-box">
        <h2>Histórico de PM2.5</h2>
        <p>Últimos 24 envios da sessão · Alerta acima de 50 µg/m³</p>
        <svg v-if="view.series.some(v => v !== null)" class="a4-chart" viewBox="0 0 480 118" role="img"
             :aria-label="'Histórico de PM2.5, escala de 0 a ' + top + ' microgramas por metro cúbico'">
          <path d="M34 9 V104 H472" fill="none" stroke="#9cabb5"/>
          <path :d="'M34 ' + y(50) + ' H472'" stroke="#ad531e" stroke-dasharray="4 4"/>
          <text x="30" y="12" text-anchor="end">{{ top }}</text>
          <text x="30" y="107" text-anchor="end">0</text>
          <text x="36" :y="y(50)-3" fill="#ad531e">50</text>
          <path :d="trend" fill="none" stroke="#087263" stroke-width="2"/>
          <circle v-for="point in points" :key="point.x" :cx="point.x" :cy="point.y" r="2.8" fill="#087263"/>
        </svg>
        <p v-else class="a4-empty">Aguardando amostras válidas.</p>
      </section>
      <section class="a4-box">
        <div class="a4-action">
          <h2>Comando do buzzer</h2>
          <button type="button" :disabled="!view.canTest" @click="send({payload:true})">Testar buzzer · 1 s</button>
        </div>
        <p v-if="view.pending" role="status">Aguardando confirmação do ID {{ view.pending }}.</p>
        <p v-else>Teste remoto de 1 segundo. O alerta local continua ativo se PM2.5 estiver acima de 50.</p>
        <ol v-if="view.events.length" class="a4-events" aria-label="Registro de comandos">
          <li v-for="(event, i) in view.events" :key="event.at + '-' + i">
            <time :datetime="event.at">{{ time(event.at) }}</time>
            <strong>{{ eventName(event.state) }}</strong>
            <span>ID {{ event.id }} · sessão {{ event.session }}</span>
          </li>
        </ol>
        <p v-else class="a4-empty">Nenhum comando registrado nesta execução.</p>
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
.a4-air { color:#193239; background:#eff5f3; padding:clamp(12px,2vw,24px); border-radius:16px; display:grid; gap:14px; }
.a4-intro { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px; background:#153d3a; color:#fff; border-radius:12px; padding:18px 22px; }
.a4-intro h1 { margin:3px 0; font-size:clamp(1.5rem,3vw,2.4rem); line-height:1.2; }
.a4-intro p,.a4-tag { color:#bee4dc; }
.a4-tag { font-size:.73rem; font-weight:700; letter-spacing:.1em; }
.a4-network { display:grid; gap:4px; color:#e0efed; }
.a4-good { color:#9aedd6; }
.a4-warn { color:#ffdcaa; }
.a4-metrics,.a4-lower { display:grid; gap:12px; grid-template-columns:repeat(3,minmax(0,1fr)); }
.a4-lower { grid-template-columns:repeat(2,minmax(0,1fr)); }
.a4-box { background:#fff; border:1px solid #d7e5df; border-radius:12px; padding:14px; min-width:0; }
.a4-metrics strong { font-size:clamp(1.35rem,3vw,2.2rem); font-variant-numeric:tabular-nums; }
.a4-metrics small,.a4-lower p,.a4-status span,.a4-air footer { color:#496468; }
.a4-metrics .a4-alert { background:#fff2e6; border-color:#cc8455; }
.a4-status { display:flex; flex-wrap:wrap; gap:8px 22px; }
.a4-status strong { color:#193239; margin-left:3px; }
.a4-air h2 { font-size:1.05rem; margin:0 0 4px; }
.a4-chart { display:block; width:100%; height:auto; max-height:136px; margin-top:6px; }
.a4-chart text { font-size:9px; }
.a4-action { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-bottom:6px; }
.a4-action button { background:#00685c; color:#fff; border-radius:7px; padding:7px 11px; font-weight:700; }
.a4-action button:disabled { background:#e6eeec; color:#4e6462; cursor:not-allowed; }
.a4-action button:focus-visible { outline:2px solid #193239; outline-offset:2px; }
.a4-events { padding:0; list-style:none; margin:8px 0 0; max-height:145px; overflow:auto; }
.a4-events li { display:flex; flex-wrap:wrap; gap:4px 10px; padding:4px 0; border-top:1px solid #e6efeb; font-size:.86rem; }
.a4-events time { font-variant-numeric:tabular-nums; }
.a4-empty { margin-top:12px; }
.a4-air footer { font-size:.8rem; }
@media(max-width:760px) { .a4-lower { grid-template-columns:1fr; } }
@media(max-width:410px) { .a4-air { padding:7px; } .a4-metrics { gap:4px; } .a4-metrics .a4-box { padding:7px; } }
</style>
