// ---- data views -------------------------------------------------------------
function itemRows(){
  var v=VIEWS.find(function(x){return x.id===VIEW});
  var rows=DATA.items;
  if(v&&v.group) rows=rows.filter(function(r){return r.group===v.group});
  if(VIEW==="locked") rows=rows.filter(function(r){return r.access!=="Available"&&r.access!=="Leveled before"});
  return rows;
}
// one convention in this table: a blank cell is "none" (never leveled, no MR needed), "—" is unknown
var blank0=function(v){ return v?esc(v):""; };
var DASH='<span class="muted">—</span>';
var ITEM_COLS=[
  {k:"name",l:"Name",cls:"name"},{k:"category",l:"Type"},{k:"state",l:"Status",fmt:pill},
  {k:"rank",l:"Rank",cls:"num",fmt:blank0},{k:"mr",l:"MR req",cls:"num",fmt:blank0},
  {k:"how",l:"How to get",fmt:function(v){ return v?esc(v):DASH; }},{k:"access",l:"Access",fmt:accessPill}
];
// a build that makes several at once says so: "Cipher ×10"
var batchName=function(v,r){ return esc(v)+(r.batch>1?' <span class="muted">×'+esc(r.batch)+'</span>':''); };
// warframe.market page for a trade name; target=_blank opens the system browser in the app window
function marketLink(slug){ return '<a href="https://warframe.market/items/'+encodeURIComponent(slug)+'" target="_blank" rel="noopener">'+esc(slug)+'</a>'; }
var RELIC_COLS=[
  {k:"name",l:"Relic",cls:"name"},{k:"tier",l:"Tier"},
  {k:"vaulted",l:"Status",fmt:function(v){return v?'<span class="pill p-warn">Vaulted</span>':'<span class="pill p-owned">Farmable</span>'}},
  {k:"count",l:"You have",cls:"num",fmt:function(v,r){ if(v==null) return '<span class="muted">?</span>'; var parts=Object.keys(r.refinements||{}).map(function(k){return r.refinements[k]+" "+k}); return '<b>'+v+'</b>'+(parts.length?' <span class="muted">('+esc(parts.join(", "))+')</span>':""); }},
  {k:"vaulted_parts",l:"Vaulted gear",fmt:function(v){return v?'<span class="pill p-violet">'+v+' vaulted</span>':'<span class="muted">-</span>'}},
  {k:"needed",l:"Parts you need",cls:"num"},
  {k:"price",l:"Market (p)",cls:"num",fmt:function(v){return v==null?'<span class="muted">-</span>':esc(v)}}
];
var BP_COLS=[
  {k:"name",l:"Blueprint for",cls:"name",fmt:batchName},
  {k:"ready",l:"Status",fmt:function(v,r){return v?'<span class="pill p-owned">Ready to build</span>':'<span class="pill p-warn">'+r.missing+' part'+(r.missing===1?"":"s")+' missing</span>'}},
  {k:"mastered",l:"Mastery",fmt:function(v){return v==null?'<span class="muted">-</span>':v?'<span class="pill p-mastered">Mastered</span>':'<span class="pill p-leveling">Not mastered</span>'}},
  {k:"blueprints",l:"Copies",cls:"num"},{k:"credits",l:"Credits",cls:"num",fmt:function(v){return (v||0).toLocaleString()}},{k:"hours",l:"Build h",cls:"num"}
];

var price=function(v){return v==null?'<span class="muted">-</span>':esc(v)};
var FOUNDRY_COLS=[
  {k:"name",l:"Building",cls:"name",fmt:batchName},
  // worked out from ready_at now, not when the inventory was loaded: long sessions stay right
  {k:"ready",l:"Status",fmt:function(v,r){return foundryReady(r)?'<span class="pill p-owned">Ready to claim</span>':'<span class="pill p-leveling">Building</span>'}},
  {k:"hours_left",l:"Time left",cls:"num",fmt:function(v,r){return esc(foundryLeft(r))}}
];
function foundryReady(r){ return r.ready_at?Date.parse(r.ready_at)<=Date.now():!!r.ready; }
function foundryLeft(r){
  if(!r.ready_at) return r.hours_left==null?"-":r.hours_left+" h";
  var min=Math.ceil((Date.parse(r.ready_at)-Date.now())/60000);
  if(min<=0) return "Ready";
  return min<60?min+" min":Math.floor(min/60)+" h "+(min%60?(min%60)+" min":"");
}
var RES_COLS=[
  {k:"name",l:"Resource",cls:"name"},{k:"short",l:"Short",cls:"num",fmt:function(v){return v?'<b>'+v.toLocaleString()+'</b>':'<span class="pill p-owned">Enough</span>'}},
  {k:"have",l:"You have",cls:"num",fmt:function(v){return (v||0).toLocaleString()}},{k:"need",l:"Blueprints need",cls:"num",fmt:function(v){return (v||0).toLocaleString()}},
  {k:"blueprints",l:"Used by",cls:"num"},{k:"farm",l:"Where to farm",fmt:function(v){return v?esc(v):'<span class="muted">Market, Dojo or quest</span>'}}
];
var SELL_COLS=[
  {k:"name",l:"Part",cls:"name"},{k:"for",l:"For"},
  {k:"owned",l:"You have",cls:"num"},{k:"spare",l:"Spare",cls:"num",fmt:function(v){return v?'<b>'+v+'</b>':'<span class="muted">0</span>'}},
  {k:"ducats",l:"Ducats each",cls:"num"},{k:"ducats_total",l:"Ducats if sold",cls:"num"},
  {k:"price",l:"Market (p)",cls:"num",fmt:price},
  {k:"best",l:"Best",tip:"Baro when a part gives 10 or more ducats per platinum it would sell for, otherwise the market. Check market prices first.",fmt:function(v){ return v?'<span class="pill '+(v==="Baro"?"p-mastered":"p-owned")+'">'+esc(v)+'</span>':DASH; }},
  {k:"status",l:"Why",fmt:function(v){return v==="Mastered or built"?'<span class="pill p-mastered">'+esc(v)+'</span>':'<span class="pill p-leveling">'+esc(v)+'</span>'}}
];
var MOD_COLS=[
  {k:"name",l:"Name",cls:"name"},{k:"category",l:"Type"},{k:"rarity",l:"Rarity"},
  {k:"owned",l:"Owned",cls:"num"},{k:"spare",l:"Spare",cls:"num"},
  {k:"best_rank",l:"Best rank",cls:"num",fmt:function(v,r){return v+(r.max_rank!=null?' / '+r.max_rank:'')}},
  {k:"price",l:"Market (p)",cls:"num",fmt:price}
];
var MISSION_COLS=[
  {k:"place",l:"Where",cls:"name",fmt:function(v,r){return esc(v)+(r.popular?' <span class="pill p-mastered">popular</span>':'')}},
  {k:"mission",l:"Mission"},{k:"level",l:"Level",cls:"num"},
  {k:"tiers",l:"Relic tiers"},{k:"best_rotation",l:"Best rotation"},
  {k:"needed_count",l:"Things you need",cls:"num"},
  {k:"score",l:"Score",cls:"num",tip:"How much of what you still need one run can drop. Higher is better.",fmt:function(v){return v.toFixed(2)}}
];
var CRACK_COLS=[
  {k:"name",l:"Relic",cls:"name"},{k:"count",l:"You have",cls:"num"},
  {k:"needed",l:"Parts you need",cls:"num"},
  {k:"vaulted_parts",l:"Vaulted gear",fmt:function(v){return v?'<span class="pill p-violet">'+v+' vaulted</span>':'<span class="muted">-</span>'}}
];
function farmSub(){ return F.sub||"missions"; }
function liveSub(){ return F.sub||"fissures"; }
var mins=function(v){ if(v==null) return '<span class="muted">-</span>'; var h=Math.floor(v/60); return (h?h+'h ':'')+(v%60)+'m'; };
var relicCell=function(v,r){
  if(!v) return '<span class="muted">none</span>';
  if(r.best_relic_count==null) return '<span class="muted">e.g. </span>'+esc(v)+'<span class="muted"> (if you have it)</span>';
  return '<b>'+esc(v)+'</b><span class="muted"> ('+r.best_relic_needed+' needed · you have '+r.best_relic_count+')</span>';
};
var FISSURE_COLS=[
  {k:"tier",l:"Tier"},{k:"mission",l:"Mission",fmt:function(v,r){return esc(v)+(r.fast?' <span class="pill p-owned">quick</span>':'')}},
  {k:"where",l:"Where",cls:"name"},
  {k:"steel_path",l:"Mode",fmt:function(v){return v?'<span class="pill p-violet">Steel Path</span>':'Normal'}},
  {k:"minutes_left",l:"Time left",cls:"num",fmt:mins},
  {k:"useful_relics",l:"Useful relics",cls:"num"},
  {k:"best_relic",l:"Bring",fmt:relicCell}
];
var STORM_COLS=[
  {k:"tier",l:"Tier"},{k:"where",l:"Where",cls:"name"},{k:"minutes_left",l:"Time left",cls:"num",fmt:mins},
  {k:"useful_relics",l:"Useful relics",cls:"num"},{k:"best_relic",l:"Bring",fmt:relicCell}
];
// the faction you fight for gives its side's reward
function invSide(x,r){ if(x.faction) return x.faction; var side=x.side; return side==="Attacker"?(r.attacker_faction||r.attacker||side):side==="Defender"?(r.defender_faction||r.defender||side):side; }
var INV_COLS=[
  {k:"where",l:"Where",cls:"name"},
  {k:"attacker",l:"Fight",fmt:function(v,r){return esc(r.attacker_faction||v||"?")+' vs '+esc(r.defender_faction||r.defender||"?")}},
  {k:"rewards",l:"Rewards",fmt:function(v,r){return (v||[]).map(function(x){return (x.flag?'<b>':'')+'Side with '+esc(invSide(x,r))+': '+esc(x.count)+'× '+esc(x.name)+(x.flag?'</b>':'')}).join('<br>')}},
  {k:"progress",l:"Progress",cls:"num",fmt:function(v){return v+'%'}},
  {k:"worth_it",l:"For you",fmt:function(v){return v?'<span class="pill p-owned">You need this</span>':'<span class="muted">-</span>'}}
];
var BARO_COLS=[
  {k:"name",l:"Item",cls:"name"},{k:"ducats",l:"Ducats",cls:"num"},{k:"credits",l:"Credits",cls:"num",fmt:function(v){return (v||0).toLocaleString()}},
  {k:"for_mastery",l:"For you",fmt:function(v){return v?'<span class="pill p-leveling">Mastery</span>':'<span class="muted">-</span>'}}
];
var WEEKLY_COLS=[
  {k:"kind",l:"What"},{k:"what",l:"Name",cls:"name"},{k:"detail",l:"Details"},
  {k:"hours_left",l:"Time left",cls:"num",fmt:function(v){return v==null?'<span class="muted">-</span>':v>=48?Math.round(v/24)+' d':Math.round(v)+' h'}},
  {k:"for_you",l:"For you",fmt:function(v,r){return (v?'<span class="pill p-owned">'+esc(r.note)+'</span>':'<span class="muted">'+esc(r.note||'-')+'</span>')}}
];
var VARZIA_COLS=[
  {k:"name",l:"Item",cls:"name"},{k:"kind",l:"Kind"},
  {k:"aya",l:"Aya",cls:"num",fmt:function(v){return v==null?'<span class="muted">-</span>':esc(v)}},
  {k:"regal_aya",l:"Regal Aya",cls:"num",fmt:function(v){return v==null?'<span class="muted">-</span>':esc(v)}},
  {k:"for_you",l:"For you",fmt:function(v,r){return v?'<span class="pill p-leveling">'+esc(r.why)+'</span>':'<span class="muted">-</span>'}}
];
function loadLive(force){
  if(!force && LIVE && Date.now()-LIVE_AT<55000) return;
  api("/api/live"+(force?"?force=1":"")).then(function(d){ LIVE=d; LIVE_AT=Date.now(); if(VIEW==="live"||VIEW==="focus") renderAll(); else if(DATA) renderFocusBar(); })
    .catch(function(){ LIVE={error:"Could not load the world state."}; if(VIEW==="live") renderAll(); });
}
function liveHeader(){
  if(!LIVE) return '<div class="now"><div class="eyebrow">Live</div><div class="what">Loading the world state…</div></div>';
  if(LIVE.error) return '<div class="now"><div class="eyebrow">Live</div><div class="what">'+esc(LIVE.error)+'</div></div>';
  var h='<div class="now"><div class="eyebrow">Right now</div>';
  var best=(LIVE.fissures||[]).filter(function(f){return f.useful_relics && spOk(f)})[0];
  if(best) h+='<div class="what">'+esc(best.tier)+' '+esc(best.mission)+' fissure on '+esc(best.where)+(best.steel_path?' (Steel Path)':'')+', '+mins(best.minutes_left)+' left</div><div class="why">'+(LIVE.inventory?'Bring '+esc(best.best_relic)+': it holds '+best.best_relic_needed+' part'+(best.best_relic_needed===1?'':'s')+' you need and you have '+best.best_relic_count+'.':esc(best.tier)+' relics like '+esc(best.best_relic)+' hold parts you need. Load your inventory to see which you own.')+'</div>';
  else h+='<div class="what">No open fissure matches your relics right now.</div>';
  h+='<div class="also">';
  // the log keeps the last mission after the game closes: say how old it is, drop it when stale
  if(LIVE.here && !(LIVE.here.log_age_min>120)) h+='<span>'+(LIVE.here.log_age_min>10?'Last seen':'You are here')+': <b>'+esc(LIVE.here.where||LIVE.here.node)+'</b>'+(LIVE.here.mission?' · '+esc(LIVE.here.mission):'')+(LIVE.here.fissure?' · fissure':'')+'</span>';
  if(LIVE.baro) h+='<span>Baro: '+(LIVE.baro.here?'at <b>'+esc(LIVE.baro.where)+'</b> for '+LIVE.baro.hours_left+' h':'arrives at '+esc(LIVE.baro.where)+' in '+LIVE.baro.hours_until+' h')+'</span>';
  var vz=((LIVE.varzia||{}).stock||[]).filter(function(x){return x.for_you}).length;
  if(vz) h+='<span>Varzia has <b>'+vz+'</b> thing'+(vz===1?'':'s')+' you need</span>';
  var inv=(LIVE.invasions||[]).filter(function(i){return i.worth_it}).length;
  if(inv) h+='<span><b>'+inv+'</b> invasions reward things you need</span>';
  if(!LIVE.inventory) h+='<span>Load your inventory to match fissures to relics you own.</span>';
  return h+'</div></div>';
}
function currentSpec(){
  if(VIEW==="live"){
    var ls=liveSub(), L=LIVE||{};
    if(ls==="storms") return {rows:L.storms||[], cols:STORM_COLS, key:"storms"};
    if(ls==="invasions") return {rows:L.invasions||[], cols:INV_COLS, key:"invasions"};
    if(ls==="baro") return {rows:(L.baro||{}).stock||[], cols:BARO_COLS, key:"baro"};
    if(ls==="weekly") return {rows:L.weekly||[], cols:WEEKLY_COLS, key:"weekly"};
    if(ls==="varzia") return {rows:(L.varzia||{}).stock||[], cols:VARZIA_COLS, key:"varzia"};
    return {rows:L.fissures||[], cols:FISSURE_COLS, key:"fissures"};
  }
  if(VIEW==="farm"){
    var sub=farmSub();
    if(sub==="crack") return {rows:(DATA.farm||{}).crack||[], cols:CRACK_COLS, key:"crack"};
    if(sub==="finish") return {rows:(DATA.farm||{}).finish||[], cols:[], key:"finish"};
    return {rows:(DATA.farm||{}).missions||[], cols:MISSION_COLS, key:"missions"};
  }
  if(VIEW==="foundry") return {rows:DATA.foundry||[], cols:FOUNDRY_COLS, key:"foundry"};
  if(VIEW==="resources") return {rows:DATA.resources||[], cols:RES_COLS, key:"resources"};
  if(VIEW==="sell") return {rows:(DATA.sell||[]).map(sellBest), cols:SELL_COLS, key:"sell"};
  if(VIEW==="mods") return {rows:DATA.mods||[], cols:MOD_COLS, key:"mods"};
  if(VIEW==="relics") return {rows:DATA.relics, cols:RELIC_COLS, key:"relics"};
  if(VIEW==="blueprints") return {rows:DATA.blueprints, cols:BP_COLS, key:"blueprints"};
  return {rows:itemRows(), cols:ITEM_COLS, key:"items"};
}
// Baro or the market for one sell row: 10 or more ducats per platinum means Baro. No price: no verdict.
function sellBest(r){ var p=Number(r.price), d=Number(r.ducats); r.best=r.price==null||!(p>0)?null:(isFinite(d)&&d/p>=10?"Baro":"Market"); return r; }
var CHECKS={};  // checkbox filter key -> test, filled in by renderFilters
function matches(r){
  if(Q){
    var hay=(r.name+" "+(r.category||"")+" "+(r.how||"")+" "+(r.sources||[]).join(" ")+" "+(r.drops||[]).map(function(d){return d.part+" "+d.for}).join(" ")+" "+(r.parts||[]).map(function(p){return p.name}).join(" ")+" "+(r.pieces||[]).map(function(p){return p.name+" "+p.sources.join(" ")}).join(" ")+" "+(r.place||"")+" "+(r.gives||[]).join(" ")+" "+(r.where||"")+" "+(r.mission||"")+" "+(r.tier||"")).toLowerCase();
    if(hay.indexOf(Q)<0) return false;
  }
  for(var k in F){ var want=F[k]; if(want==null||want===""||k==="sub") continue;
    if(want===true&&CHECKS[k]){ if(!CHECKS[k](r)) return false; }
    else if(typeof want==="function"){ if(!want(r)) return false; }
    else if(String(r[k])!==String(want)) return false;
  }
  return true;
}
function filtered(){ var s=currentSpec(); return s.rows.filter(matches); }
function sorted(rows){
  var s=SORT[VIEW]; if(!s) return rows;
  var k=s.k, d=s.dir;
  return rows.slice().sort(function(a,b){
    var x=a[k], y=b[k];
    if(x==null&&y==null) return 0; if(x==null) return 1; if(y==null) return -1;
    if(typeof x==="number"&&typeof y==="number") return (x-y)*d;
    if(typeof x==="boolean") return ((x?1:0)-(y?1:0))*d;
    return String(x).localeCompare(String(y))*d;
  });
}

