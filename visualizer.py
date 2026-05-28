"""
visualizer.py — экспорт графа в HTML.
  export_to_html_sigma()  — Sigma.js (WebGL), 10k–100k узлов
  export_to_html_d3()     — алиас на sigma (совместимость)
  graph_to_json()         — данные без HTML
"""
import json, logging
from pathlib import Path
import networkx as nx

logger = logging.getLogger(__name__)

EDGE_COLORS = {"parent_child":"#e63946","common_founder":"#f4a261","common_director":"#2a9d8f","same_industry":"#457b9d"}
EDGE_LABELS = {"parent_child":"Учредительство","common_founder":"Общий учредитель","common_director":"Общий руководитель","same_industry":"Одна отрасль"}
INDUSTRY_CONFIG = {
    "Нефтегаз":{"color":"#ff7c50","center":[0.28,0.38]},
    "Банки и финансы":{"color":"#e05050","center":[0.72,0.28]},
    "Металлургия":{"color":"#f9c74f","center":[0.18,0.65]},
    "Энергетика":{"color":"#f4845f","center":[0.50,0.20]},
    "Телеком и ИТ":{"color":"#4cc9f0","center":[0.80,0.55]},
    "Розничная торговля":{"color":"#43d9ad","center":[0.68,0.78]},
    "Транспорт":{"color":"#a78bfa","center":[0.35,0.78]},
    "Госорганы":{"color":"#c084fc","center":[0.88,0.18]},
    "Химия":{"color":"#34d399","center":[0.12,0.48]},
    "Строительство":{"color":"#fbbf24","center":[0.55,0.68]},
    "Прочее":{"color":"#6b7280","center":[0.50,0.50]},
}

def _industry_color(okved):
    from metrics import get_industry_group
    return INDUSTRY_CONFIG.get(get_industry_group(okved), INDUSTRY_CONFIG["Прочее"])["color"]

def _node_size(n, pr):
    s = 5 + pr*2000
    s += min((n.get("employee_count") or 0)/80000, 8)
    s += min((n.get("capital") or 0)/3e10, 6)
    return max(4, min(s, 40))

def _edge_size(d):
    t=d.get("type","")
    if t=="parent_child": return 1+(d.get("share") or 0)/100*4
    if t=="common_director": return 1.5
    if t=="same_industry": return 0.4
    return 1.0

def graph_to_json(G):
    from metrics import get_industry_group
    nodes=[]
    for inn in G.nodes():
        n=G.nodes[inn]; pr=n.get("pagerank",0.01)
        ind=get_industry_group(n.get("okved",""))
        cfg=INDUSTRY_CONFIG.get(ind,INDUSTRY_CONFIG["Прочее"])
        cap=n.get("capital"); emp=n.get("employee_count")
        tooltip=(f"{n.get('name',inn)}\nИНН: {inn}\nОтрасль: {ind}\n"
                 f"ОКВЭД: {n.get('okved','')} {n.get('okved_name','')}\n"
                 f"Статус: {n.get('status','')}\n"
                 f"Капитал: {f'{cap:,.0f} руб' if cap else 'н/д'} | "
                 f"Сотрудников: {f'{emp:,}' if emp else 'н/д'}\n"
                 f"PageRank: {pr:.5f} | Степень: {n.get('degree',0)}")
        nodes.append({"id":inn,"label":n.get("label",inn),"x":cfg["center"][0],"y":cfg["center"][1],
                      "size":_node_size(n,pr),"color":cfg["color"],"industry":ind,
                      "pagerank":round(pr,6),"degree":n.get("degree",0),"community":n.get("community",0),"tooltip":tooltip})
    edges=[]; seen=set()
    for u,v,d in G.edges(data=True):
        key=tuple(sorted([u,v]))+(d.get("type",""),)
        if key in seen: continue
        seen.add(key); t=d.get("type","")
        edges.append({"id":f"{u}_{v}_{t}","source":u,"target":v,"type":t,
                      "label":EDGE_LABELS.get(t,t),"color":EDGE_COLORS.get(t,"#888"),
                      "size":_edge_size(d),"share":d.get("share"),"via":d.get("via","")})
    return {"nodes":nodes,"edges":edges}

def export_to_html_sigma(G, filename="org_network.html"):
    data=graph_to_json(G)
    gj=json.dumps(data,ensure_ascii=False)
    ij=json.dumps({k:v["color"] for k,v in INDUSTRY_CONFIG.items()},ensure_ascii=False)
    elj=json.dumps(EDGE_LABELS,ensure_ascii=False)
    ecj=json.dumps(EDGE_COLORS,ensure_ascii=False)
    html=f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>Карта связей организаций РФ</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/graphology/0.25.1/graphology.umd.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/sigma.js/2.4.0/sigma.min.js"></script>
<style>
:root{{--bg:#070b12;--bg2:#0d1321;--border:rgba(255,255,255,0.07);--border2:rgba(255,255,255,0.14);--text:#e2e8f0;--text2:#8899b4;--text3:#4a6080;--accent:#3d8bff;--accent2:#00d4aa}}
*{{box-sizing:border-box;margin:0;padding:0}}body{{background:var(--bg);font-family:Inter,sans-serif;color:var(--text);overflow:hidden}}
#sc{{position:fixed;inset:0}}.panel{{background:rgba(13,19,33,.95);border:1px solid var(--border);border-radius:12px;padding:16px;backdrop-filter:blur(20px)}}
#lp{{position:fixed;left:16px;top:16px;bottom:16px;width:268px;display:flex;flex-direction:column;gap:10px;z-index:100;pointer-events:none}}
#lp>*{{pointer-events:all}}
#hdr h1{{font-family:monospace;font-size:13px;font-weight:600;color:var(--accent);letter-spacing:.05em}}
#hdr .sub{{font-size:10px;color:var(--text3);font-family:monospace;margin-top:2px}}
#stats{{display:flex;padding:0}}
.si{{flex:1;text-align:center;border-right:1px solid var(--border);padding:8px 4px}}.si:last-child{{border-right:none}}
.sn{{font-family:monospace;font-size:18px;font-weight:600;color:var(--accent);display:block}}
.sl{{font-size:9px;color:var(--text3);text-transform:uppercase;letter-spacing:.08em;margin-top:2px;display:block}}
#sw{{position:relative}}
#si{{width:100%;background:rgba(255,255,255,.05);border:1px solid var(--border2);border-radius:8px;color:var(--text);padding:9px 12px;font-size:12px;outline:none}}
#si:focus{{border-color:var(--accent)}}#si::placeholder{{color:var(--text3)}}
#sr{{margin-top:6px;display:flex;flex-direction:column;gap:3px;max-height:110px;overflow-y:auto}}
.sri{{padding:6px 10px;border-radius:6px;font-size:11px;cursor:pointer;color:var(--text2);border:1px solid transparent;transition:all .15s}}
.sri:hover{{background:rgba(61,139,255,.12);border-color:rgba(61,139,255,.3);color:var(--text)}}
.sri .inn{{font-family:monospace;font-size:9px;color:var(--text3);display:block;margin-top:1px}}
#flt h3{{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:var(--text3);margin-bottom:10px}}
.fgl{{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:var(--text3);margin-bottom:6px;display:block}}
.fb{{display:inline-flex;align-items:center;gap:5px;padding:4px 9px;border-radius:100px;font-size:10px;cursor:pointer;border:1px solid;transition:all .2s;margin:2px 3px 2px 0;user-select:none}}
.fb .dot{{width:6px;height:6px;border-radius:50%;flex-shrink:0}}.fb.off{{opacity:.25;filter:saturate(.2)}}
.ic{{display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:6px;font-size:10px;cursor:pointer;border:1px solid var(--border);transition:all .2s;margin-bottom:3px;user-select:none}}
.ic .bar{{width:3px;height:14px;border-radius:2px;flex-shrink:0}}.ic.off{{opacity:.2}}
#det{{position:fixed;right:16px;top:16px;width:292px;background:rgba(13,19,33,.97);border:1px solid var(--border);border-radius:12px;backdrop-filter:blur(24px);z-index:100;transform:translateX(340px);opacity:0;transition:transform .35s cubic-bezier(.16,1,.3,1),opacity .35s;overflow:hidden}}
#det.open{{transform:translateX(0);opacity:1}}
#dc{{position:absolute;top:12px;right:12px;width:24px;height:24px;border-radius:6px;background:rgba(255,255,255,.06);border:1px solid var(--border);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:14px;color:var(--text3);transition:all .2s}}
#dc:hover{{background:rgba(255,255,255,.12);color:var(--text)}}
.dh{{padding:18px 20px 12px;border-bottom:1px solid var(--border)}}
.dbg{{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:100px;font-size:10px;font-weight:500;margin-bottom:8px;border:1px solid}}
.dn{{font-size:14px;font-weight:600;line-height:1.3;margin-bottom:4px;padding-right:28px}}
.di{{font-family:monospace;font-size:11px;color:var(--text3)}}
.dm{{display:grid;grid-template-columns:repeat(3,1fr);border-bottom:1px solid var(--border)}}
.dmi{{padding:10px 12px;border-right:1px solid var(--border);text-align:center}}.dmi:last-child{{border-right:none}}
.dmv{{font-family:monospace;font-size:15px;font-weight:600;color:var(--accent);display:block}}
.dml{{font-size:9px;color:var(--text3);text-transform:uppercase;letter-spacing:.07em;margin-top:2px;display:block}}
.dinfo{{padding:12px 20px;border-bottom:1px solid var(--border)}}
.ir{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;font-size:12px;gap:8px}}.ir:last-child{{margin-bottom:0}}
.ik{{color:var(--text3);flex-shrink:0}}.iv{{color:var(--text2);text-align:right;font-size:11px}}
.dco{{padding:12px 20px}}.ct{{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:var(--text3);margin-bottom:8px}}
.ci{{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:6px;margin-bottom:3px;cursor:pointer;border:1px solid transparent;transition:all .15s}}
.ci:hover{{background:rgba(255,255,255,.04);border-color:var(--border)}}
.cd{{width:6px;height:6px;border-radius:50%;flex-shrink:0}}.cn{{font-size:11px;color:var(--text2);flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.ctl{{font-size:9px;color:var(--text3);white-space:nowrap}}
#leg{{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);display:flex;align-items:center;background:rgba(13,19,33,.95);border:1px solid var(--border);border-radius:100px;padding:8px 16px;z-index:100;backdrop-filter:blur(20px);gap:0}}
.ls{{width:1px;height:18px;background:var(--border);margin:0 10px}}
.le{{display:flex;align-items:center;gap:5px;font-size:10px;color:var(--text3);cursor:pointer;padding:0 3px}}.le:hover{{color:var(--text)}}
.ll{{width:18px;height:2px;border-radius:1px;flex-shrink:0}}
#ctr{{position:fixed;bottom:16px;right:16px;display:flex;flex-direction:column;gap:6px;z-index:100}}
.cb{{width:36px;height:36px;background:rgba(13,19,33,.95);border:1px solid var(--border);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:15px;color:var(--text2);backdrop-filter:blur(20px);transition:all .2s;user-select:none}}.cb:hover{{background:rgba(255,255,255,.07);color:var(--text)}}
#tt{{position:fixed;background:rgba(13,19,33,.98);border:1px solid var(--border2);border-radius:8px;padding:9px 13px;font-size:11px;pointer-events:none;display:none;z-index:200;backdrop-filter:blur(20px);color:var(--text2);max-width:300px;line-height:1.6;white-space:pre-line}}
#ld{{position:fixed;inset:0;background:var(--bg);display:flex;align-items:center;justify-content:center;z-index:1000;flex-direction:column;gap:14px;transition:opacity .6s}}
#ld.done{{opacity:0;pointer-events:none}}
.lt{{font-family:monospace;font-size:12px;color:var(--accent);letter-spacing:.1em}}
.lb{{width:200px;height:2px;background:var(--border2);border-radius:1px;overflow:hidden}}
.lf{{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:1px;animation:ld 1.2s ease-in-out forwards}}
@keyframes ld{{from{{width:0}}to{{width:100%}}}}
::-webkit-scrollbar{{width:4px}}::-webkit-scrollbar-thumb{{background:var(--border2);border-radius:4px}}
</style></head><body>
<div id="ld"><div class="lt">ИНИЦИАЛИЗАЦИЯ ГРАФА</div><div class="lb"><div class="lf"></div></div></div>
<div id="sc"></div>
<div id="lp">
  <div class="panel" id="hdr"><h1>ORG NETWORK / РФ</h1><div class="sub">карта корпоративных связей</div></div>
  <div class="panel" id="stats">
    <div class="si"><span class="sn" id="sn">—</span><span class="sl">Организаций</span></div>
    <div class="si"><span class="sn" id="se">—</span><span class="sl">Связей</span></div>
    <div class="si"><span class="sn" id="sk">—</span><span class="sl">Кластеров</span></div>
  </div>
  <div class="panel" id="sw">
    <input id="si" type="text" placeholder="Поиск по названию или ИНН…" autocomplete="off">
    <div id="sr"></div>
  </div>
  <div class="panel" id="flt">
    <h3>Фильтры</h3>
    <div style="margin-bottom:12px"><span class="fgl">Тип связи</span><div id="efw"></div></div>
    <div><span class="fgl">Отрасль</span><div id="ifw"></div></div>
  </div>
</div>
<div id="det">
  <div id="dc">✕</div>
  <div class="dh"><div class="dbg" id="db">—</div><div class="dn" id="dn">—</div><div class="di" id="dinn">ИНН: —</div></div>
  <div class="dm">
    <div class="dmi"><span class="dmv" id="dpr">—</span><span class="dml">PageRank</span></div>
    <div class="dmi"><span class="dmv" id="ddeg">—</span><span class="dml">Степень</span></div>
    <div class="dmi"><span class="dmv" id="dcls">—</span><span class="dml">Кластер</span></div>
  </div>
  <div class="dinfo" id="dinfo"></div>
  <div class="dco" id="dco"></div>
</div>
<div id="leg">
  <div class="le" data-type="parent_child"><div class="ll" style="background:#e63946"></div>Учредительство</div>
  <div class="ls"></div>
  <div class="le" data-type="common_founder"><div class="ll" style="background:#f4a261"></div>Общий учредитель</div>
  <div class="ls"></div>
  <div class="le" data-type="common_director"><div class="ll" style="background:#2a9d8f"></div>Общий директор</div>
  <div class="ls"></div>
  <div class="le" data-type="same_industry"><div class="ll" style="background:#457b9d;opacity:.6"></div>Одна отрасль</div>
</div>
<div id="ctr">
  <div class="cb" id="ci">＋</div><div class="cb" id="co">－</div>
  <div class="cb" id="cf">⌂</div><div class="cb" id="cl" title="ForceLayout">↺</div>
</div>
<div id="tt"></div>
<script>
const GD={gj},IC={ij},EL={elj},EC={ecj};
const nb=Object.fromEntries(GD.nodes.map(n=>[n.id,n]));
let AE=new Set(['parent_child','common_founder','common_director','same_industry']);
let AI=new Set(Object.keys(IC));
let SN=null;
const graph=new graphology.Graph({{multi:true,type:'undirected'}});
GD.nodes.forEach(n=>graph.addNode(n.id,{{label:n.label,x:(n.x+(Math.random()-.5)*.15)*window.innerWidth,y:(n.y+(Math.random()-.5)*.15)*window.innerHeight,size:n.size,color:n.color,industry:n.industry,pagerank:n.pagerank,degree:n.degree,community:n.community,tooltip:n.tooltip}}));
GD.edges.forEach(e=>{{try{{graph.addEdge(e.source,e.target,{{id:e.id,type:e.type,label:e.label,color:e.color,size:e.size,share:e.share,via:e.via}})}}catch(err){{}}}}); 
const R=new Sigma(graph,document.getElementById('sc'),{{renderEdgeLabels:false,defaultEdgeType:'line',labelFont:'Inter,sans-serif',labelSize:11,labelColor:{{color:'rgba(200,215,235,.85)'}},minCameraRatio:.005,maxCameraRatio:20,enableEdgeHoverEvents:true,
  edgeReducer:(e,d)=>{{const t=d.type;if(!AE.has(t))return{{...d,hidden:true}};const si=graph.getNodeAttribute(graph.source(e),'industry'),ti=graph.getNodeAttribute(graph.target(e),'industry');if(!AI.has(si)||!AI.has(ti))return{{...d,hidden:true}};if(SN){{const s=graph.source(e),tg=graph.target(e);if(s!==SN&&tg!==SN)return{{...d,color:d.color+'28',size:d.size*.4}}}};return d}},
  nodeReducer:(n,d)=>{{if(!AI.has(d.industry))return{{...d,hidden:true}};if(SN&&n!==SN){{const nb2=graph.neighbors(SN);if(!nb2.includes(n))return{{...d,color:d.color+'28',size:d.size*.5}}}};return d}}
}});
const tt=document.getElementById('tt');
R.on('enterNode',({{node}})=>{{tt.textContent=graph.getNodeAttribute(node,'tooltip');tt.style.display='block'}});
R.on('leaveNode',()=>tt.style.display='none');
R.on('enterEdge',({{edge}})=>{{const d=graph.getEdgeAttributes(edge);let tx=EL[d.type]||d.type;if(d.share)tx+=`\\nДоля: ${{d.share}}%`;if(d.via)tx+=`\\nЧерез: ${{d.via}}`;tt.textContent=tx;tt.style.display='block'}});
R.on('leaveEdge',()=>tt.style.display='none');
document.addEventListener('mousemove',e=>{{if(tt.style.display==='block'){{tt.style.left=Math.min(e.clientX+14,window.innerWidth-310)+'px';tt.style.top=Math.min(e.clientY+14,window.innerHeight-120)+'px'}}}});
function showDetail(id){{
  const n=nb[id],cfg=IC[n.industry]||'#6b7280';
  const b=document.getElementById('db');b.textContent=n.industry;b.style.background=cfg+'22';b.style.borderColor=cfg+'55';b.style.color=cfg;
  document.getElementById('dn').textContent=graph.getNodeAttribute(id,'label');
  document.getElementById('dinn').textContent='ИНН: '+id;
  document.getElementById('dpr').textContent=(n.pagerank*1000).toFixed(2);
  document.getElementById('ddeg').textContent=n.degree;
  document.getElementById('dcls').textContent='#'+n.community;
  document.getElementById('dinfo').innerHTML=`<div class="ir"><span class="ik">Отрасль</span><span class="iv">${{n.industry}}</span></div><div class="ir"><span class="ik">PageRank</span><span class="iv">${{n.pagerank.toFixed(6)}}</span></div><div class="ir"><span class="ik">Степень</span><span class="iv">${{n.degree}} связей</span></div><div class="ir"><span class="ik">Кластер</span><span class="iv">#${{n.community}}</span></div>`;
  const nbs=graph.neighbors(id);
  document.getElementById('dco').innerHTML='<div class="ct">Связи ('+(nbs.length)+')</div>'+nbs.slice(0,20).map(nb2=>{{const es=graph.edges(id,nb2);const ed=es.length?graph.getEdgeAttributes(es[0]):{{}};return `<div class="ci" onclick="focusNode('${{nb2}}')"><div class="cd" style="background:${{EC[ed.type]||'#888'}}"></div><span class="cn">${{graph.getNodeAttribute(nb2,'label')}}</span><span class="ctl">${{(EL[ed.type]||'').split(' ')[0]}}${{ed.share?' '+ed.share+'%':''}}</span></div>`}}).join('');
  document.getElementById('det').classList.add('open');
}}
function focusNode(id){{SN=id;R.refresh();showDetail(id);R.getCamera().animate({{x:graph.getNodeAttribute(id,'x'),y:graph.getNodeAttribute(id,'y'),ratio:.3}},{{duration:600}})}}
window.focusNode=focusNode;
R.on('clickNode',({{node}})=>{{SN=node;R.refresh();showDetail(node)}});
R.on('clickStage',()=>{{SN=null;R.refresh();document.getElementById('det').classList.remove('open')}});
document.getElementById('dc').onclick=()=>{{SN=null;R.refresh();document.getElementById('det').classList.remove('open')}};
function updStats(){{
  document.getElementById('sn').textContent=graph.filterNodes((_,d)=>AI.has(d.industry)).length.toLocaleString();
  document.getElementById('se').textContent=graph.filterEdges((_,d)=>AE.has(d.type)).length.toLocaleString();
  document.getElementById('sk').textContent=new Set(graph.filterNodes((_,d)=>AI.has(d.industry)).map(n=>graph.getNodeAttribute(n,'community'))).size;
}}
['parent_child','common_founder','common_director','same_industry'].forEach(t=>{{
  const c=EC[t],btn=document.createElement('div');btn.className='fb';btn.style.borderColor=c+'55';btn.style.color=c;
  btn.innerHTML=`<div class="dot" style="background:${{c}}"></div>${{EL[t]}}`;
  btn.onclick=()=>{{if(AE.has(t)){{if(AE.size<=1)return;AE.delete(t);btn.classList.add('off')}}else{{AE.add(t);btn.classList.remove('off')}};R.refresh();updStats()}};
  document.getElementById('efw').appendChild(btn);
}});
[...new Set(GD.nodes.map(n=>n.industry))].filter(i=>i!=='Прочее').forEach(ind=>{{
  const c=IC[ind]||'#888',ch=document.createElement('div');ch.className='ind-chip ic';
  ch.innerHTML=`<div class="bar" style="background:${{c}}"></div><span>${{ind}}</span>`;
  ch.onclick=()=>{{if(AI.has(ind)){{if(AI.size<=1)return;AI.delete(ind);ch.classList.add('off')}}else{{AI.add(ind);ch.classList.remove('off')}};R.refresh();updStats()}};
  document.getElementById('ifw').appendChild(ch);
}});
document.getElementById('si').addEventListener('input',e=>{{
  const q=e.target.value.toLowerCase().trim(),res=document.getElementById('sr');res.innerHTML='';if(!q)return;
  GD.nodes.filter(n=>n.label.toLowerCase().includes(q)||n.id.includes(q)).slice(0,6).forEach(n=>{{
    const el=document.createElement('div');el.className='sri';
    el.innerHTML=n.label+`<span class="inn">${{n.id}} · ${{n.industry}}</span>`;
    el.onclick=()=>{{res.innerHTML='';e.target.value='';focusNode(n.id)}};res.appendChild(el);
  }});
}});
document.getElementById('ci').onclick=()=>R.getCamera().animatedZoom({{factor:1.5}});
document.getElementById('co').onclick=()=>R.getCamera().animatedUnzoom({{factor:1.5}});
document.getElementById('cf').onclick=()=>R.getCamera().animatedReset();
let lw=false;
document.getElementById('cl').onclick=()=>{{
  if(lw)return;lw=true;const btn=document.getElementById('cl');btn.style.color='var(--accent)';
  const ns=graph.nodes();let i=0;
  const inv=setInterval(()=>{{
    if(i++>=300){{clearInterval(inv);lw=false;btn.style.color='';return}}
    const f={{}};ns.forEach(n=>f[n]={{x:0,y:0}});
    for(let a=0;a<ns.length;a++)for(let b=a+1;b<ns.length;b++){{
      const na=ns[a],nb2=ns[b],ax=graph.getNodeAttribute(na,'x'),ay=graph.getNodeAttribute(na,'y');
      const bx=graph.getNodeAttribute(nb2,'x'),by=graph.getNodeAttribute(nb2,'y'),dx=ax-bx,dy=ay-by;
      const d2=dx*dx+dy*dy+1,fv=(graph.getNodeAttribute(na,'size')*80)/d2;
      f[na].x+=fv*dx;f[na].y+=fv*dy;f[nb2].x-=fv*dx;f[nb2].y-=fv*dy;
    }}
    graph.forEachEdge((e,d,s,t)=>{{if(d.hidden)return;const sx=graph.getNodeAttribute(s,'x'),sy=graph.getNodeAttribute(s,'y'),tx=graph.getNodeAttribute(t,'x'),ty=graph.getNodeAttribute(t,'y'),dx=tx-sx,dy=ty-sy,dist=Math.sqrt(dx*dx+dy*dy)+1,k=d.size*.008;f[s].x+=k*dx;f[s].y+=k*dy;f[t].x-=k*dx;f[t].y-=k*dy}});
    const cool=1-i/300;
    ns.forEach(n=>{{graph.setNodeAttribute(n,'x',graph.getNodeAttribute(n,'x')+f[n].x*2*cool);graph.setNodeAttribute(n,'y',graph.getNodeAttribute(n,'y')+f[n].y*2*cool)}});
    R.refresh();
  }},16);
}};
document.querySelectorAll('.le').forEach(el=>el.addEventListener('click',()=>{{const t=el.dataset.type;if(AE.has(t)&&AE.size>1)AE.delete(t);else AE.add(t);R.refresh();updStats()}}));
updStats();
setTimeout(()=>document.getElementById('ld').classList.add('done'),1200);
</script></body></html>"""
    Path(filename).write_text(html, encoding="utf-8")
    logger.info("Sigma export → %s (%d nodes, %d edges)", filename, G.number_of_nodes(), G.number_of_edges())
    return filename

def export_to_html_d3(G, filename="org_network.html"):
    if G.number_of_nodes() > 3000:
        logger.warning("D3/SVG падает на %d узлах — используется Sigma.js", G.number_of_nodes())
    return export_to_html_sigma(G, filename)
