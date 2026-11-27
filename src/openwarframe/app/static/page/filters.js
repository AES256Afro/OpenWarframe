// ---- filters ------------------------------------------------------------------
function chipGroup(label, field, values, counts){
  var h='<span class="muted">'+esc(label)+'</span>';
  h+='<button class="chip" type="button" data-f="'+field+'" data-v="" aria-pressed="'+(!F[field])+'">All</button>';
  values.forEach(function(v){ h+='<button class="chip" type="button" data-f="'+field+'" data-v="'+esc(v)+'" aria-pressed="'+(F[field]===v)+'">'+esc(v)+(counts?'<span class="c">'+(counts[v]||0)+'</span>':"")+'</button>'; });
  return h;
}
function countBy(rows, k){ var c={}; rows.forEach(function(r){ c[r[k]]=(c[r[k]]||0)+1 }); return c; }
function renderFilters(){
  var el=$("filters"); var h="";
  if(VIEW==="overview"||VIEW==="earn"||VIEW==="rewards"){ el.hidden=true; return; }
  el.hidden=false;
  var spec=currentSpec();
  if(VIEW==="live"){
    var lsubs=[["fissures","Fissures"],["storms","Void storms"],["invasions","Invasions"],["baro","Baro"],["weekly","This week"],["varzia","Varzia"]];
    h+=lsubs.map(function(s){return '<button class="chip" type="button" data-sub="'+s[0]+'" aria-pressed="'+(liveSub()===s[0])+'">'+s[1]+'</button>'}).join("");
    if(spec.key==="fissures"){
      h+=chipGroup("Tier","tier",["Lith","Meso","Neo","Axi","Requiem","Omnia"],countBy(spec.rows,"tier"));
      h+='<label><input type="checkbox" id="fuse"'+(F._use?" checked":"")+'> Only where my relics help</label>';
      h+='<label><input type="checkbox" id="fsponly"'+(F._sponly?" checked":"")+'> Steel Path only</label>';
      h+='<label><input type="checkbox" id="fnosp"'+(F._nosp?" checked":"")+'> Hide Steel Path</label>';
      h+='<label><input type="checkbox" id="ffast"'+(F._fast?" checked":"")+'> Only quick missions</label>';
    }
    if(spec.key==="invasions") h+='<label><input type="checkbox" id="fworth"'+(F._worth?" checked":"")+'> Only rewards I need</label>';
    h+='<button class="btn" type="button" id="liverefresh">Refresh</button>';
  } else if(VIEW==="farm"){
    var subs=[["missions","Missions to run"],["finish","Finish an item"],["crack","Relics to crack"]];
    h+=subs.map(function(s){return '<button class="chip" type="button" data-sub="'+s[0]+'" aria-pressed="'+(farmSub()===s[0])+'">'+s[1]+'</button>'}).join("");
    if(spec.key==="missions"){
      var kinds=Object.keys(countBy(spec.rows,"mission")).sort();
      h+='<label>Mission <select id="fmis"><option value="">All</option>'+kinds.map(function(c){return '<option'+(F.mission===c?" selected":"")+'>'+esc(c)+'</option>'}).join("")+'</select></label>';
      h+='<label><input type="checkbox" id="fpop"'+(F._pop?" checked":"")+'> Only popular farms</label>';
    }
    if(spec.key==="finish"){
      if(F.id){ var one=(spec.rows||[]).find(function(x){return x.id===F.id});
        h+='<span class="clear"><span>Showing <b>'+esc(one?one.name:"one item")+'</b></span><button class="btn" type="button" id="fshowall">Show all</button></span>'; }
      h+='<label><input type="checkbox" id="fone"'+(F._one?" checked":"")+'> Only one piece away</label>';
      if(DATA.meta.inventory) h+='<label><input type="checkbox" id="fdo"'+(F._do?" checked":"")+'> Only with relics I own</label>';
    }
  } else if(spec.key==="items"){
    var states=Object.keys(countBy(spec.rows,"state")).sort();
    h+=chipGroup("Status", "state", states, countBy(spec.rows,"state"));
    var cats=Object.keys(countBy(spec.rows,"category")).sort();
    if(cats.length>1){ h+='<label>Type <select id="fcat"><option value="">All</option>'+cats.map(function(c){return '<option'+(F.category===c?" selected":"")+'>'+esc(c)+'</option>'}).join("")+'</select></label>'; }
    var acc=Object.keys(countBy(spec.rows,"access")).sort();
    if(acc.length>1){ h+='<label>Access <select id="facc"><option value="">All</option>'+acc.map(function(c){return '<option'+(F.access===c?" selected":"")+'>'+esc(c)+'</option>'}).join("")+'</select></label>'; }
  } else if(spec.key==="relics"){
    h+=chipGroup("Tier", "tier", ["Lith","Meso","Neo","Axi","Requiem"], countBy(spec.rows,"tier"));
    h+='<label><input type="checkbox" id="fneed"'+(F._need?" checked":"")+'> Only relics with parts I need</label>';
    h+='<label><input type="checkbox" id="ffarm"'+(F._farm?" checked":"")+'> Only farmable</label>';
    h+='<label><input type="checkbox" id="fvault"'+(F._vault?" checked":"")+'> Only relics with vaulted gear</label>';
    h+='<button class="btn" type="button" id="prices">Check market prices</button>';
    if(DATA.meta.inventory) h+='<label><input type="checkbox" id="fown"'+(F._own?" checked":"")+'> Only relics I own</label>';
  } else if(spec.key==="sell"){
    h+='<label><input type="checkbox" id="fspare"'+(F._spare?" checked":"")+'> Only spares</label>';
    h+='<button class="btn" type="button" id="prices">Check market prices</button>';
    var tot=spec.rows.filter(function(r){return r.spare}).reduce(function(a,r){return a+r.ducats_total},0);
    h+='<span class="muted">Spares are worth <b>'+tot.toLocaleString()+'</b> ducats at Baro. Best says where each part is worth more: Baro when it gives 10 or more ducats per platinum, otherwise the market.</span>';
  } else if(spec.key==="mods"){
    h+=chipGroup("Type", "category", Object.keys(countBy(spec.rows,"category")).sort(), countBy(spec.rows,"category"));
    h+='<label><input type="checkbox" id="fspare"'+(F._spare?" checked":"")+'> Only spares</label>';
    h+='<label><input type="checkbox" id="frare"'+(F._rare?" checked":"")+'> Only rare and legendary</label>';
    h+='<button class="btn" type="button" id="prices">Check market prices</button>';
  } else if(spec.key==="resources"){
    h+='<label><input type="checkbox" id="fshort"'+(F._short?" checked":"")+'> Only what I am short of</label>';
  } else if(spec.key==="blueprints"){
    h+='<label><input type="checkbox" id="fready"'+(F._ready?" checked":"")+'> Only ready to build</label>';
    h+='<label><input type="checkbox" id="funm"'+(F._unm?" checked":"")+'> Only not yet mastered</label>';
  }
  el.innerHTML=h;
  el.querySelectorAll(".chip").forEach(function(b){ b.onclick=function(){ F[b.dataset.f]=b.dataset.v||null; renderAll(); }; });
  // checkbox filters store `true` (a function would be lost when the view is saved and
  // restored); the test itself is looked up in CHECKS
  var bind=function(id,key,fn,clears){ if(fn) CHECKS[key]=fn; var x=$(id); if(x) x.onchange=function(){
    F[key]=x.type==="checkbox"?(x.checked?true:null):(x.value||null);
    if(x.checked&&clears) F[clears]=null;  // "Steel Path only" and "Hide Steel Path" exclude each other
    renderAll(); }; };
  bind("fcat","category"); bind("facc","access");
  bind("fneed","_need",function(r){return r.needed>0});
  bind("ffarm","_farm",function(r){return !r.vaulted});
  bind("fown","_own",function(r){return r.count>0});
  bind("fvault","_vault",function(r){return r.vaulted_parts>0});
  bind("fspare","_spare",function(r){return r.spare>0});
  bind("frare","_rare",function(r){return r.rarity==="Rare"||r.rarity==="Legendary"});
  bind("fshort","_short",function(r){return r.short>0});
  bind("fmis","mission"); bind("fpop","_pop",function(r){return r.popular});
  bind("fone","_one",function(r){return r.missing<=1});
  bind("fdo","_do",function(r){return r.doable!==false});
  bind("fuse","_use",function(r){return r.useful_relics>0});
  bind("fsponly","_sponly",function(r){return r.steel_path},"_nosp");
  bind("fnosp","_nosp",function(r){return !r.steel_path},"_sponly");
  bind("ffast","_fast",function(r){return r.fast});
  bind("fworth","_worth",function(r){return r.worth_it});
  var lr=$("liverefresh"); if(lr) lr.onclick=function(){ toast("Refreshing the world state…"); loadLive(true); };
  el.querySelectorAll("[data-sub]").forEach(function(b){ b.onclick=function(){ var keep=b.dataset.sub; F={sub:keep}; OPEN={}; setHash(VIEW+"/"+keep, true); renderAll(); }; });
  var sa=$("fshowall"); if(sa) sa.onclick=function(){ F.id=null; renderAll(); };
  var pb=$("prices"); if(pb) pb.onclick=checkPrices;
  bind("fready","_ready",function(r){return r.ready});
  bind("funm","_unm",function(r){return r.mastered===false});
}

