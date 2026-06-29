#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web message-count dashboard built on the monitor base.

A background thread samples :class:`MessageStatsCollector` on a fixed cadence
and caches the latest serialized stats plus a bounded rate history. HTTP
clients only ever read the cache, so any number of browser tabs add zero extra
load on MySQL. The page polls ``/api/stats`` and draws a self-contained canvas
chart (no external CDN).

Run::

    uv run python scripts/monitor.py web --port 8787
"""

import threading
import time
from collections import deque

from flask import Flask, jsonify, render_template_string

from .collector import MessageStatsCollector


class StatsSampler:
    """Owns the collector and samples it on a background daemon thread."""

    def __init__(
        self,
        interval: float = 5.0,
        window: int = 12,
        history: int = 600,
        bucket: int = 60,
    ) -> None:
        self.interval = interval
        self.window = window
        self.bucket = bucket
        # Historical seed rebuilt from chat_messages.created_at — never evicted,
        # so the chart timeline always starts from the very first message.
        self._seed: list[dict] = []
        self._history: deque[dict] = deque(maxlen=history)
        self._latest: dict = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        with MessageStatsCollector(window=self.window) as col:
            # Seed the chart with the full message history reconstructed from
            # chat_messages.created_at so the timeline reaches back to the
            # very first message, not just the current session.
            seed = col.load_message_history(bucket_seconds=self.bucket)
            with self._lock:
                self._seed = seed
            while not self._stop.is_set():
                try:
                    col.poll()
                    stats = col.stats()
                    with self._lock:
                        self._latest = stats.to_dict()
                        self._history.append(
                            {
                                "t": stats.ts,
                                "instant": stats.rate_instant,
                                "avg": stats.rate_avg,
                                "ema": stats.rate_ema,
                                "total": stats.total,
                            }
                        )
                except Exception as exc:  # keep sampling despite transient errors
                    with self._lock:
                        self._latest = {"error": str(exc)}
                self._stop.wait(self.interval)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "stats": dict(self._latest),
                # Seed (full history) + live tail (high-resolution recent samples)
                "history": list(self._seed) + list(self._history),
                "interval": self.interval,
            }

    def stop(self) -> None:
        self._stop.set()


_PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Message Monitor</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; font-family: system-ui, sans-serif; background:#0f1115; color:#e6e6e6; }
  header { padding:16px 24px; border-bottom:1px solid #222; display:flex;
           justify-content:space-between; align-items:center; }
  h1 { font-size:16px; margin:0; color:#5bc0eb; }
  #updated { color:#888; font-size:12px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
          gap:12px; padding:24px; }
  .card { background:#171a21; border:1px solid #222; border-radius:10px; padding:16px; }
  .card .label { color:#9aa4b2; font-size:12px; }
  .card .value { font-size:26px; font-weight:700; margin-top:6px; }
  .value.green { color:#3ddc84; } .value.yellow { color:#f5c542; }
  .wrap { padding:0 24px 24px; }
  canvas { width:100%; height:240px; background:#171a21; border:1px solid #222; border-radius:10px; }
  canvas.timeline { height:72px; margin-top:8px; cursor:grab; touch-action:none; }
  canvas.timeline.drag { cursor:grabbing; }
  .tl-hint { color:#666; font-size:11px; margin-top:6px; }
  table { width:100%; border-collapse:collapse; margin-top:12px; }
  td, th { text-align:left; padding:6px 10px; border-bottom:1px solid #222; font-size:13px; }
  th { color:#9aa4b2; } td.n { text-align:right; font-variant-numeric:tabular-nums; }
</style>
</head>
<body>
<header>
  <h1>QQ Copilot Bot — 消息数量看板</h1>
  <span id="updated">连接中…</span>
</header>
<div class="grid" id="cards"></div>
<div class="wrap">
  <canvas id="chart" width="1200" height="240"></canvas>
  <canvas id="timeline" class="timeline" width="1200" height="72"></canvas>
  <div class="tl-hint">滚轮缩放 · 拖动平移 · 拖动两端把手缩放 · 双击复位并跟随最新</div>
</div>
<div class="wrap">
  <table id="sessions">
    <thead><tr><th>会话</th><th class="n">消息数</th></tr></thead>
    <tbody></tbody>
  </table>
</div>
<script>
const REFRESH = {{ interval }} * 1000;

function fmtDur(s){
  if(s==null) return '—';
  s=Math.floor(s);
  const h=Math.floor(s/3600), m=Math.floor(s%3600/60), x=s%60;
  return h ? `${h}:${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}`
           : `${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}`;
}
function card(label,value,cls){
  return `<div class="card"><div class="label">${label}</div><div class="value ${cls||''}">${value}</div></div>`;
}
function fmtTime(t){ return new Date(t*1000).toLocaleTimeString(); }
function labelSession(sid){
  if(sid.startsWith('group:')) return '群 '+sid.slice(6);
  if(sid.startsWith('private:')) return '私聊 '+sid.slice(8);
  return sid;
}

// ---- timeline / chart state ------------------------------------------------
let HIST=[], view={t0:null,t1:null,follow:true}, drag=null;
const MIN_SPAN=10;

function dataRange(){ return HIST.length ? [HIST[0].t, HIST[HIST.length-1].t] : [0,1]; }

function clampView(){
  const [dmin,dmax]=dataRange();
  let span=view.t1-view.t0;
  if(!(span>0)){ view.t0=dmin; view.t1=dmax; return; }
  span=Math.max(MIN_SPAN, span);
  const wasFull=view.follow && view.t0<=dmin+1e-6;
  if(view.follow){ view.t1=dmax; view.t0=wasFull?dmin:Math.max(dmin,dmax-span); }
  else {
    // Maintain span while panning — shift window instead of shrinking it.
    if(view.t1>dmax){ view.t1=dmax; view.t0=dmax-span; }
    if(view.t0<dmin){ view.t0=dmin; view.t1=Math.min(dmax,dmin+span); }
  }
}

function zoomView(t, factor){
  // Zoom in/out keeping time t (epoch seconds) fixed under the cursor.
  const [,dmax]=dataRange();
  const ratio=(t-view.t0)/Math.max(1e-9,view.t1-view.t0);
  const newSpan=Math.max(MIN_SPAN,(view.t1-view.t0)*factor);
  view.t0=t-ratio*newSpan;
  view.t1=t+(1-ratio)*newSpan;
  view.follow=view.t1>=dmax-1e-6;
  clampView(); render();
}

function applyData(hist){
  HIST=hist||[];
  const [dmin,dmax]=dataRange();
  if(view.t0===null){ view.t0=dmin; view.t1=dmax; view.follow=true; }
  clampView(); render();
}

function visible(){ return HIST.filter(h=>h.t>=view.t0-1e-6 && h.t<=view.t1+1e-6); }
function canvasX(canvas,e){ const r=canvas.getBoundingClientRect(); return (e.clientX-r.left)*(canvas.width/r.width); }

function drawSeries(data,t0,t1){
  const c=document.getElementById('chart'), ctx=c.getContext('2d');
  const W=c.width, H=c.height, P=30; ctx.clearRect(0,0,W,H);
  if(!data.length){
    ctx.fillStyle='#666'; ctx.font='13px sans-serif';
    ctx.fillText('此时间段暂无数据',P,H/2); return;
  }
  const vals=data.map(h=>Math.max(h.avg,h.ema)), max=Math.max(1,...vals);
  ctx.font='11px sans-serif';
  ctx.strokeStyle='#2a2f3a'; ctx.lineWidth=1;
  for(let i=0;i<=4;i++){
    const y=P+(H-2*P)*i/4;
    ctx.beginPath(); ctx.moveTo(P,y); ctx.lineTo(W-P,y); ctx.stroke();
    ctx.fillStyle='#666'; ctx.fillText(Math.round(max*(1-i/4)),4,y+3);
  }
  const span=(t1-t0)||1, xOf=t=>P+(W-2*P)*(t-t0)/span;
  function line(key,color){
    ctx.strokeStyle=color; ctx.lineWidth=2; ctx.beginPath();
    data.forEach((h,i)=>{ const x=xOf(h.t), y=P+(H-2*P)*(1-h[key]/max);
      i?ctx.lineTo(x,y):ctx.moveTo(x,y); }); ctx.stroke();
  }
  line('avg','#5bc0eb'); line('ema','#3ddc84');
  ctx.fillStyle='#777';
  ctx.textAlign='left';   ctx.fillText(fmtTime(t0),P,H-8);
  ctx.textAlign='center'; ctx.fillText(fmtTime((t0+t1)/2),W/2,H-8);
  ctx.textAlign='right';  ctx.fillText(fmtTime(t1),W-P,H-8); ctx.textAlign='left';
  ctx.fillStyle='#5bc0eb'; ctx.fillText('avg',W-70,16);
  ctx.fillStyle='#3ddc84'; ctx.fillText('ema',W-40,16);
}

const TL_P=8;
function tlXOf(t){
  const [dmin,dmax]=dataRange(), span=(dmax-dmin)||1;
  const c=document.getElementById('timeline');
  return TL_P+(c.width-2*TL_P)*(t-dmin)/span;
}

function drawTimeline(){
  const c=document.getElementById('timeline'), ctx=c.getContext('2d');
  const W=c.width, H=c.height; ctx.clearRect(0,0,W,H);
  if(!HIST.length) return;
  const max=Math.max(1,...HIST.map(h=>h.ema));
  ctx.strokeStyle='#3a4150'; ctx.lineWidth=1; ctx.beginPath();
  HIST.forEach((h,i)=>{ const x=tlXOf(h.t), y=TL_P+(H-2*TL_P)*(1-h.ema/max);
    i?ctx.lineTo(x,y):ctx.moveTo(x,y); }); ctx.stroke();
  const xs=tlXOf(view.t0), xe=tlXOf(view.t1);
  ctx.fillStyle='rgba(15,17,21,0.55)'; ctx.fillRect(0,0,xs,H); ctx.fillRect(xe,0,W-xe,H);
  ctx.fillStyle='rgba(91,192,235,0.12)'; ctx.fillRect(xs,0,xe-xs,H);
  ctx.strokeStyle=view.follow?'#3ddc84':'#5bc0eb'; ctx.lineWidth=1.5; ctx.strokeRect(xs,0.5,xe-xs,H-1);
  ctx.fillStyle=view.follow?'#3ddc84':'#5bc0eb';
  ctx.fillRect(xs-2,0,4,H); ctx.fillRect(xe-2,0,4,H);
}

function render(){ drawSeries(visible(),view.t0,view.t1); drawTimeline(); }

(function initTimeline(){
  const c=document.getElementById('timeline');
  function timeAt(x){ const [dmin,dmax]=dataRange(), span=(dmax-dmin)||1;
    return dmin+(x-TL_P)/(c.width-2*TL_P)*span; }
  c.addEventListener('pointerdown', e=>{
    if(!HIST.length) return;
    const x=canvasX(c,e), xs=tlXOf(view.t0), xe=tlXOf(view.t1);
    let mode='pan';
    if(Math.abs(x-xs)<=6) mode='left';
    else if(Math.abs(x-xe)<=6) mode='right';
    else if(x<xs||x>xe){ const span=view.t1-view.t0, t=timeAt(x);
      view.t0=t-span/2; view.t1=t+span/2; view.follow=false; }
    drag={mode,x,t0:view.t0,t1:view.t1};
    c.setPointerCapture(e.pointerId); c.classList.add('drag'); clampView(); render();
  });
  c.addEventListener('pointermove', e=>{
    if(!drag) return;
    const x=canvasX(c,e), [dmin,dmax]=dataRange(), span=(dmax-dmin)||1;
    const dt=(x-drag.x)/(c.width-2*TL_P)*span;
    if(drag.mode==='pan'){ view.t0=drag.t0+dt; view.t1=drag.t1+dt; }
    else if(drag.mode==='left'){ view.t0=Math.min(drag.t1-MIN_SPAN,drag.t0+dt); view.t1=drag.t1; }
    else if(drag.mode==='right'){ view.t1=Math.max(drag.t0+MIN_SPAN,drag.t1+dt); view.t0=drag.t0; }
    view.follow=view.t1>=dmax-1e-6; clampView(); render();
  });
  function end(){ if(drag){ drag=null; c.classList.remove('drag'); } }
  c.addEventListener('pointerup', end);
  c.addEventListener('pointercancel', end);
  c.addEventListener('dblclick', ()=>{
    const [dmin,dmax]=dataRange();
    view.t0=dmin; view.t1=dmax; view.follow=true; render();
  });
  // Scroll wheel: zoom in/out centred on cursor position.
  c.addEventListener('wheel', e=>{
    e.preventDefault();
    if(!HIST.length) return;
    const [dmin,dmax]=dataRange(), span=(dmax-dmin)||1;
    const x=canvasX(c,e);
    const t=dmin+(x-TL_P)/(c.width-2*TL_P)*span;
    zoomView(t, e.deltaY>0 ? 1.25 : 0.8);
  },{passive:false});
})();

// Scroll wheel zoom on the main chart canvas.
(function initChartWheel(){
  const c=document.getElementById('chart');
  c.addEventListener('wheel', e=>{
    e.preventDefault();
    if(!HIST.length) return;
    const W=c.width, P=30, span=view.t1-view.t0;
    const x=canvasX(c,e);
    const t=view.t0+(x-P)/Math.max(1,W-2*P)*span;
    zoomView(t, e.deltaY>0 ? 1.25 : 0.8);
  },{passive:false});
})();

async function tick(){
  try{
    const r=await fetch('/api/stats');
    const d=await r.json();
    const s=d.stats||{};
    if(s.error){ document.getElementById('updated').textContent='错误: '+s.error; return; }
    const rc=s.rate_avg>0?'green':'yellow';
    document.getElementById('cards').innerHTML =
      card('消息总数', (s.total||0).toLocaleString()) +
      card('用户消息', (s.total_user||0).toLocaleString()) +
      card('机器人回复', (s.total_assistant||0).toLocaleString()) +
      card('私聊', (s.total_private||0).toLocaleString()) +
      card('群聊', (s.total_group||0).toLocaleString()) +
      card('本轮新增', '+'+(s.delta||0)) +
      card('瞬时 msgs/min', (s.rate_instant||0).toFixed(1), rc) +
      card('平均 msgs/min', (s.rate_avg||0).toFixed(1)) +
      card('EMA msgs/min', (s.rate_ema||0).toFixed(1)) +
      card('已运行', fmtDur(s.elapsed_s));
    const tb=document.querySelector('#sessions tbody');
    tb.innerHTML='';
    Object.entries(s.per_session||{}).forEach(([k,v])=>{
      const tr=document.createElement('tr');
      tr.innerHTML=`<td>${labelSession(k)}</td><td class="n">${v.toLocaleString()}</td>`;
      tb.appendChild(tr);
    });
    applyData(d.history||[]);
    document.getElementById('updated').textContent='更新于 '+new Date().toLocaleTimeString();
  } catch(e){
    document.getElementById('updated').textContent='离线，重试中…';
  }
}
tick(); setInterval(tick, REFRESH);
</script>
</body>
</html>"""


def create_app(sampler: StatsSampler) -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index() -> str:
        return render_template_string(_PAGE, interval=sampler.interval)

    @app.route("/api/stats")
    def api_stats():
        return jsonify(sampler.snapshot())

    return app


def run_web(
    host: str = "127.0.0.1",
    port: int = 8787,
    interval: float = 5.0,
    window: int = 12,
    history: int = 600,
    bucket: int = 60,
) -> None:
    """Start the Flask web dashboard. Blocks until interrupted."""
    sampler = StatsSampler(interval=interval, window=window, history=history, bucket=bucket)
    sampler.start()
    app = create_app(sampler)
    print(f"message monitor at http://{host}:{port}  (Ctrl-C to stop)")
    try:
        app.run(host=host, port=port, threaded=True)
    finally:
        sampler.stop()
