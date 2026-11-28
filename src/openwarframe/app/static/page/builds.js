// ---- suggested builds for guns: computed from the game data on request -----------------
var BUILD={}, BUILD_OPTS={target:"none", owned:true, stacks:true, level:"sp", stripped:false, combo:"12", xstatus:"0", attack:"normal", aim:"body"};
// weapon arcane per weapon: "" = the best one that can be scored, "none" = empty slot
var BUILD_ARC={};
// your Riven per weapon: its stat lines as the game shows them, and its drain; kept in this browser
var BUILD_RIVEN={};
try{ BUILD_RIVEN=JSON.parse(localStorage.getItem("owf-rivens")||"{}")||{}; }catch(e){ BUILD_RIVEN={}; }
function rivenOf(id){ return BUILD_RIVEN[id]||{text:"",drain:"18"}; }
// Incarnon per weapon: mode "" (default), "off", "normal" or "form", and a perk per tier ("" = best)
var BUILD_INC={}, BUILD_INC_OPTS={};
function incOf(id){ return BUILD_INC[id]||{mode:"",perks:{}}; }
function incPerks(id){ var p=incOf(id).perks, out=[]; Object.keys(p).sort().forEach(function(t){ if(p[t]) out.push(t+":"+p[t]); }); return out.join("|"); }
function saveRivens(){ try{ localStorage.setItem("owf-rivens",JSON.stringify(BUILD_RIVEN)); }catch(e){} }
var BUILD_LEVELS=[["none","No armor (damage test)"],["normal","Normal missions"],["sp","Steel Path"]];
var BUILD_TARGETS=[["none","Any enemy"],["Grineer","Grineer"],["Corpus","Corpus"],["Infested","Infested"],["Orokin","Corrupted (Orokin)"],["Murmur","The Murmur"],["Sentient","Sentient"],["Scaldra","Scaldra"],["Techrot","Techrot"]];
function isGun(r){ return r.category==="Primary"||r.category==="Secondary"||r.category==="Melee"; }
function buildKey(id){ return [id,BUILD_OPTS.target,BUILD_OPTS.owned&&DATA.meta.inventory?1:0,BUILD_OPTS.stacks?1:0,BUILD_OPTS.level,BUILD_OPTS.stripped?1:0,BUILD_OPTS.combo,BUILD_OPTS.xstatus,BUILD_OPTS.attack,BUILD_OPTS.aim,BUILD_ARC[id]||"",rivenOf(id).text,rivenOf(id).drain,incOf(id).mode,incPerks(id)].join("|"); }
// arcane choices come with a build; keep the last list per weapon so the select stays up
var BUILD_ARC_OPTS={};
function buildPanel(r){
  var inv=!!DATA.meta.inventory;
  var h='<div class="buildbox"><h3>Suggested build</h3><div class="buildopts">'
    +'<label>Against <select data-bopt="target">'+BUILD_TARGETS.map(function(t){return '<option value="'+t[0]+'"'+(t[0]===BUILD_OPTS.target?' selected':'')+'>'+esc(t[1])+'</option>'}).join('')+'</select></label>'
    +'<label>Enemies <select data-bopt="level">'+BUILD_LEVELS.map(function(t){return '<option value="'+t[0]+'"'+(t[0]===BUILD_OPTS.level?' selected':'')+'>'+esc(t[1])+'</option>'}).join('')+'</select></label>'
    +'<label><input type="checkbox" data-bopt="stripped"'+(BUILD_OPTS.stripped?' checked':'')+'> Armor already stripped (abilities, squad)</label>'
    +(inv?'<label><input type="checkbox" data-bopt="owned"'+(BUILD_OPTS.owned?' checked':'')+'> Only mods I own</label>':'')
    +'<label>Aim <select data-bopt="aim">'+[["body","Body shots"],["head","Headshots"]].map(function(c){return '<option value="'+c[0]+'"'+(BUILD_OPTS.aim===c[0]?' selected':'')+'>'+c[1]+'</option>'}).join('')+'</select></label>'
    +(r.category==="Melee"?'<label>Attack <select data-bopt="attack">'+[["normal","Normal hits"],["heavy","Heavy attack"]].map(function(c){return '<option value="'+c[0]+'"'+(BUILD_OPTS.attack===c[0]?' selected':'')+'>'+c[1]+'</option>'}).join('')+'</select></label>':'')
    +(BUILD_ARC_OPTS[r.id]?'<label>Arcane <select data-barc="'+esc(r.id)+'"><option value="">Best one that can be scored</option><option value="none"'+(BUILD_ARC[r.id]==="none"?' selected':'')+'>None</option>'+BUILD_ARC_OPTS[r.id].map(function(o){return '<option value="'+esc(o.name)+'"'+(BUILD_ARC[r.id]===o.name?' selected':'')+'>'+esc(o.label||o.name)+(o.scored?'':' (not scored)')+'</option>'}).join('')+'</select></label>':'')
    +(r.category==="Melee"?'<label>Combo <select data-bopt="combo">'+[["1","No combo (1x)"],["6","6x"],["12","12x, the cap"]].map(function(c){return '<option value="'+c[0]+'"'+(BUILD_OPTS.combo===c[0]?' selected':'')+'>'+c[1]+'</option>'}).join('')+'</select></label>':'')
      +'<label>Status types from other sources <select data-bopt="xstatus">'+["0","1","2","3","4","5"].map(function(n){return '<option'+(BUILD_OPTS.xstatus===n?' selected':'')+'>'+n+'</option>'}).join('')+'</select></label>'
    +'<label><input type="checkbox" data-bopt="stacks"'+(BUILD_OPTS.stacks?' checked':'')+'> Count on-kill stacks at their maximum</label>'
    +incPanel(r.id)
    +'<label class="rivenin">Your Riven, one stat per line as shown on the maxed mod <textarea rows="4" data-briven="'+esc(r.id)+'" placeholder="+152.3% Critical Chance&#10;+98.1% Multishot&#10;+120% Toxin&#10;-45% Zoom">'+esc(rivenOf(r.id).text)+'</textarea></label>'
    +'<label>Riven drain <input type="number" min="8" max="26" step="1" data-brdrain="'+esc(r.id)+'" value="'+esc(rivenOf(r.id).drain)+'"></label>'
    +'<button class="btn" type="button" data-build="'+esc(r.id)+'">'+(BUILD[buildKey(r.id)]?'Build again':'Suggest a build')+'</button></div>';
  h+='<div class="buildout" data-buildout="'+esc(r.id)+'">'+(BUILD[buildKey(r.id)]?buildHtml(BUILD[buildKey(r.id)]):(inv?'':'<p class="muted">Without an inventory the build may use mods you don\'t have; load your inventory to limit it to yours.</p>'))+'</div></div>';
  return h;
}
// Incarnon controls: known once a build of this weapon has come back
function incPanel(id){
  var o=BUILD_INC_OPTS[id]; if(!o) return '';
  var cur=incOf(id), mode=cur.mode||o.mode;
  var modes=[];
  if(o.genesis) modes.push(["off","Not installed"]);
  modes.push(["normal","Evolutions, normal attack"]);
  if(o.can_form) modes.push(["form","Incarnon form"]);
  var h='<label>Incarnon <select data-binc="'+esc(id)+'">'+modes.map(function(m){return '<option value="'+m[0]+'"'+(mode===m[0]?' selected':'')+'>'+m[1]+'</option>'}).join('')+'</select></label>';
  if(o.form_skip) h+='<span class="muted">Incarnon form not scored: '+esc(o.form_skip)+'</span>';
  if(mode!=="off") o.tiers.forEach(function(t){
    var want=cur.perks[t.tier]||"";
    h+='<label>Evolution '+["","I","II","III","IV","V"][t.tier]+' <select data-bperk="'+esc(id)+'" data-tier="'+t.tier+'"><option value="">Best one that can be scored</option>'
      +t.options.map(function(p){return '<option value="'+esc(p.name)+'"'+(want===p.name?' selected':'')+' title="'+esc((p.counts?p.counts+'. ':'')+p.text)+'">'+esc(p.name)+(p.counted?'':' (not counted)')+'</option>'}).join('')+'</select></label>';
  });
  return h;
}
function incHtml(b){
  var o=b.incarnon; if(!o||o.mode==="off") return '';
  var picked=o.tiers.filter(function(t){return t.chosen}).map(function(t){ var p=t.options.filter(function(x){return x.name===t.chosen})[0]||{};
    return '<li><b>'+["","I","II","III","IV","V"][t.tier]+': '+esc(t.chosen)+'</b>'+(p.counted?'':' <span class="muted">(not counted)</span>')+'<div class="muted">'+(p.counts?'Counted: '+esc(p.counts)+'. ':'')+esc(p.text||'')+'</div></li>'; }).join('');
  return '<p><span class="pill p-violet">Incarnon</span> <b>'+(o.mode==="form"?'Incarnon form':'Evolutions on the normal attack')+'</b></p>'+(picked?'<ul class="buildmods">'+picked+'</ul>':'');
}
function pct(v){ return Math.round(v*100)+'%'; }
function num(v){ return v>=100?Math.round(v).toLocaleString():(Math.round(v*10)/10).toLocaleString(); }
function buildHtml(b){
  if(b.error) return '<p class="muted">'+esc(b.error)+'</p>';
  var s=b.stats, h='';
  h+='<ol class="buildmods">'+b.mods.map(function(m){ return '<li>'+(m.exilus?'<span class="pill p-violet">Exilus</span> ':'')+'<b>'+esc(m.name)+'</b> <span class="muted">'+(m.id==="riven"?'yours, drain '+m.drain:'rank '+m.rank+'/'+m.max_rank)+(m.owned===false?' · you don\'t have it':'')+'</span><div class="muted">'+esc(m.why)+'</div></li>'; }).join('')+'</ol>';
  h+=incHtml(b);
  if(b.arcane) h+='<p><span class="pill p-violet">Arcane</span> <b>'+esc(b.arcane.label||b.arcane.name)+'</b>'+(b.arcane.counted?'':' <span class="muted">(not counted)</span>')+'<span class="muted"> · '+esc(b.arcane.text.replace(/\n/g," "))+'</span></p>';
  if(s.heavy){
    if(s.time_to_kill) h+='<div class="buildstats"><span>Heavy attacks to kill <b>'+Math.max(1,Math.ceil(s.time_to_kill-1e-9))+'</b></span></div>';
    h+='<div class="buildstats"><span>One heavy attack to health <b>'+num(s.total_dps)+'</b></span><span>Hit <b>'+num(s.direct_dps)+'</b></span><span>Status damage over time <b>'+num(s.status_dps)+'</b></span></div>';
    h+='<div class="buildstats"><span>Heavy attack <b>'+num(s.per_shot)+'</b> before armor</span><span>Crit <b>'+pct(s.crit_chance)+'</b> × '+num(s.crit_multiplier)+'</span><span>Status <b>'+pct(s.status_chance)+'</b></span><span>Wind-up <b>'+num(s.windup)+' s</b></span></div>';
  } else {
  if(s.time_to_kill) h+='<div class="buildstats"><span>Time to kill <b>'+(s.time_to_kill<1?(Math.round(s.time_to_kill*100)/100).toLocaleString():num(s.time_to_kill))+' s</b></span>'+(s.shield_dps?'<span>To shields <b>'+num(s.shield_dps)+'</b>/s</span>':'')+'</div>';
  h+='<div class="buildstats"><span>Damage per second to health <b>'+num(s.total_dps)+'</b></span><span>Direct hits <b>'+num(s.direct_dps)+'</b></span><span>Status damage over time <b>'+num(s.status_dps)+'</b></span></div>';
  var isMelee=b.slot==="MELEE";
  h+='<div class="buildstats"><span>Per '+(isMelee?'hit':'shot')+' <b>'+num(s.per_shot)+'</b> before armor</span><span>Crit <b>'+pct(s.crit_chance)+'</b> × '+num(s.crit_multiplier)+'</span><span>Status <b>'+pct(s.status_chance)+'</b> ('+num(s.procs_per_second)+' procs/s)</span>'+(isMelee?'':'<span>Multishot <b>'+num(s.multishot)+'</b></span>')+'<span>'+(isMelee?'Attack speed':'Fire rate')+' <b>'+num(s.fire_rate)+'</b></span></div>';
  }
  var fx=[];
  if(s.armor_reduction) fx.push('armor '+Math.round(s.armor).toLocaleString()+' stops '+pct(s.armor_reduction));
  if(s.corrosive_stacks>=0.5) fx.push(num(s.corrosive_stacks)+' Corrosive stacks');
  if(s.heat_uptime>=0.05) fx.push('Heat strip '+pct(s.heat_uptime)+' of the time');
  if(s.viral_stacks>=0.5) fx.push(num(s.viral_stacks)+' Viral stacks');
  if(s.magnetic_stacks>=0.5) fx.push(num(s.magnetic_stacks)+' Magnetic stacks');
  if(s.cold_stacks>=0.5) fx.push(num(s.cold_stacks)+' Cold stacks');
  if(s.headshot) fx.unshift('headshots x'+num(s.location_mult));
  else if(s.location_mult<1) fx.unshift('body shots x'+num(s.location_mult));
  if(fx.length) h+='<p class="muted">On the enemy: '+esc(fx.join(' · '))+'</p>';
  h+='<p class="muted">Damage: '+b.elements.map(function(e){return esc(e[0])+' '+num(e[1])}).join(' · ')+'</p>';
  if(b.upgrade) h+='<p>Best mod you don\'t have: <b>'+esc(b.upgrade.name)+'</b> <span class="muted">('+esc(b.upgrade.gain)+(s.heavy?' more damage per heavy attack)':' more damage per second)')+'</span></p>';
  if(b.notes&&b.notes.length) h+='<ul class="muted buildnotes">'+b.notes.map(function(n){return '<li>'+esc(n)+'</li>'}).join('')+'</ul>';
  return h;
}
function runBuild(id){
  var k=buildKey(id);
  [].forEach.call(document.querySelectorAll("[data-buildout]"), function(el){ if(el.getAttribute("data-buildout")===id) el.innerHTML='<p class="muted">Working out the best mods…</p>'; });
  var q="/api/build?id="+encodeURIComponent(id)+"&target="+encodeURIComponent(BUILD_OPTS.target)+"&owned="+(BUILD_OPTS.owned&&DATA.meta.inventory?1:0)+"&stacks="+(BUILD_OPTS.stacks?1:0)+"&level="+encodeURIComponent(BUILD_OPTS.level)+"&stripped="+(BUILD_OPTS.stripped?1:0)+"&combo="+encodeURIComponent(BUILD_OPTS.combo)+"&xstatus="+encodeURIComponent(BUILD_OPTS.xstatus)+"&attack="+encodeURIComponent(BUILD_OPTS.attack)+"&arcane="+encodeURIComponent(BUILD_ARC[id]||"")+"&aim="+encodeURIComponent(BUILD_OPTS.aim)+"&riven="+encodeURIComponent(rivenOf(id).text)+"&rdrain="+encodeURIComponent(rivenOf(id).drain)+"&incarnon="+encodeURIComponent(incOf(id).mode)+"&perks="+encodeURIComponent(incPerks(id));
  api(q).then(function(b){ BUILD[k]=b; if(b.arcane_options) BUILD_ARC_OPTS[id]=b.arcane_options; if(b.incarnon) BUILD_INC_OPTS[id]=b.incarnon; redrawTable(); }).catch(function(){ BUILD[k]={error:"Could not work that out. Is OpenWarframe still running?"}; redrawTable(); });
}
function onBuildEvent(e){
  var t=e.target; if(!t.closest) return;
  var opt=t.closest("[data-bopt]");
  if(opt && e.type==="change"){ var k=opt.dataset.bopt; BUILD_OPTS[k]=opt.type==="checkbox"?opt.checked:opt.value; return; }
  var arc=t.closest("[data-barc]");
  if(arc && e.type==="change"){ BUILD_ARC[arc.dataset.barc]=arc.value; return; }
  var im=t.closest("[data-binc]");
  if(im && e.type==="change"){ var iid=im.dataset.binc, cur0=incOf(iid); BUILD_INC[iid]={mode:im.value, perks:cur0.perks}; redrawTable(); return; }
  var ip=t.closest("[data-bperk]");
  if(ip && e.type==="change"){ var pid=ip.dataset.bperk, cur1=incOf(pid); cur1.perks[ip.dataset.tier]=ip.value; BUILD_INC[pid]=cur1; return; }
  var rv=t.closest("[data-briven]"), rd=t.closest("[data-brdrain]");
  if((rv||rd) && (e.type==="change"||e.type==="input")){ var rid=(rv||rd).getAttribute(rv?"data-briven":"data-brdrain"), cur=rivenOf(rid);
    BUILD_RIVEN[rid]={text:rv?rv.value:cur.text, drain:rd?rd.value:cur.drain}; if(!BUILD_RIVEN[rid].text.trim()) delete BUILD_RIVEN[rid]; saveRivens(); return; }
  var b=t.closest("[data-build]"); if(b && e.type==="click"){ e.stopPropagation(); runBuild(b.dataset.build); }
}
$("view").addEventListener("click", onBuildEvent, true);
$("view").addEventListener("change", onBuildEvent);
$("view").addEventListener("input", onBuildEvent);
// ---- Warframe builds: balance the stats the abilities you use scale with -----------------------
var FBUILD={}, FOPTS={surv:"some", abilities:{}, augments:{}, shards:"none", arcanes:{}};
function isFrame(r){ return r.category==="Warframe"; }
// abilities ticked for a frame: every one from the last build unless you untick it
function fChosen(id){
  var last=FBUILD["last:"+id], sel=FOPTS.abilities[id]||{};
  if(!last||!last.abilities) return [];
  return last.abilities.filter(function(a){ return sel[a.key]!==false; }).map(function(a){ return String(a.key); });
}
function fAugments(id){ var a=FOPTS.augments[id]||{}; return Object.keys(a).filter(function(k){return a[k]}).sort(); }
function fArcanes(id){ return (FOPTS.arcanes[id]||[]).filter(function(x){return x}); }
function fKey(id){ return [id,FOPTS.surv,fChosen(id).join(",")||"all",BUILD_OPTS.owned&&DATA.meta.inventory?1:0,fAugments(id).join(","),FOPTS.shards,fArcanes(id).join(",")].join("|"); }
function frameBuildPanel(r){
  var inv=!!DATA.meta.inventory, last=FBUILD["last:"+r.id], b=FBUILD[fKey(r.id)]||FBUILD["shown:"+r.id];
  var h='<div class="buildbox"><h3>Suggested build</h3><div class="buildopts">';
  if(last&&last.abilities) h+='<span>Abilities I use:</span>'+last.abilities.map(function(a){ var on=(FOPTS.abilities[r.id]||{})[a.key]; on=on==null?true:on;
    return '<label><input type="checkbox" data-fab="'+esc(r.id)+'" value="'+a.key+'"'+(on?' checked':'')+'> '+esc(a.name)+'</label>'; }).join('');
  if(last&&last.augments&&last.augments.length){
    var used={}; last.abilities.forEach(function(a){ if((FOPTS.abilities[r.id]||{})[a.key]!==false) used[a.name]=true; });
    var augs=last.augments.filter(function(a){ return used[a.ability]; });
    if(augs.length) h+='<div class="augs"><span>Augments to include:</span>'+augs.map(function(a){ var on=!!(FOPTS.augments[r.id]||{})[a.id];
      return '<label title="'+esc(a.text)+'"><input type="checkbox" data-faug="'+esc(r.id)+'" value="'+esc(a.id)+'"'+(on?' checked':'')+'> '+esc(a.name)+' <span class="muted">('+esc(a.ability)+(a.owned===false?', not owned':'')+')</span></label>'; }).join('')+'</div>';
  }
  if(last&&last.arcane_options){ var cur=FOPTS.arcanes[r.id]||[];
    var opts=function(i){ return '<option value="">Best scored</option>'+last.arcane_options.map(function(a){ return '<option value="'+esc(a.id)+'"'+(cur[i]===a.id?' selected':'')+' title="'+esc(a.text)+'">'+esc(a.name)+(a.scored?' (scored)':'')+(a.owned===false?' (not owned)':'')+'</option>'; }).join(''); };
    h+='<label>Arcane 1 <select data-farc="'+esc(r.id)+'" data-slot="0">'+opts(0)+'</select></label><label>Arcane 2 <select data-farc="'+esc(r.id)+'" data-slot="1">'+opts(1)+'</select></label>';
  }
  h+='<label>Archon Shards <select data-fopt="shards"><option value="none"'+(FOPTS.shards==="none"?' selected':'')+'>None</option><option value="regular"'+(FOPTS.shards==="regular"?' selected':'')+'>5 shards</option><option value="tauforged"'+(FOPTS.shards==="tauforged"?' selected':'')+'>5 Tauforged</option></select></label>';
  h+='<label>Survivability <select data-fopt="surv"><option value="none"'+(FOPTS.surv==="none"?' selected':'')+'>Not needed</option><option value="some"'+(FOPTS.surv==="some"?' selected':'')+'>Some</option><option value="tanky"'+(FOPTS.surv==="tanky"?' selected':'')+'>A lot</option></select></label>'
    +(inv?'<label><input type="checkbox" data-bopt="owned"'+(BUILD_OPTS.owned?' checked':'')+'> Only mods I own</label>':'')
    +'<button class="btn" type="button" data-fbuild="'+esc(r.id)+'">'+(b?'Build again':'Suggest a build')+'</button></div>';
  h+='<div class="buildout">'+(b?frameBuildHtml(b):'')+'</div></div>';
  return h;
}
function frameBuildHtml(b){
  if(b.error) return '<p class="muted">'+esc(b.error)+'</p>';
  var s=b.stats, h='';
  if(b.aura) h+='<p><span class="muted">Aura:</span> <b>'+esc(b.aura.name)+'</b> <span class="muted">rank '+b.aura.rank+'/'+b.aura.max_rank+' · +'+b.aura.capacity+' capacity with a matching polarity'+(b.aura.counts?' · '+esc(b.aura.why):'')+'</span></p>';
  h+='<ol class="buildmods">'+b.mods.map(function(m){ return '<li>'+(m.exilus?'<span class="pill p-violet">Exilus</span> ':'')+(m.augment?'<span class="pill p-owned">Augment</span> ':'')+'<b>'+esc(m.name)+'</b> <span class="muted">rank '+m.rank+'/'+m.max_rank+'</span><div class="muted">'+esc(m.why)+'</div></li>'; }).join('')+'</ol>';
  if(b.arcanes&&b.arcanes.length) h+='<p><span class="muted">Arcanes:</span> '+b.arcanes.map(function(a){ var e=a.effect||{}, bits=[];
      if(e.strength) bits.push('+'+Math.round(e.strength*100)+'% strength'); if(e.health_flat) bits.push('+'+num(e.health_flat)+' health');
      return '<b>'+esc(a.name)+'</b> <span class="muted">rank '+a.rank+'/'+a.max_rank+(bits.length?' · '+esc(bits.join(', ')):a.scored?'':' · your choice, not scored')+(a.owned===false?' · not owned':'')+'</span>'; }).join(' · ')+'</p>';
  if(b.shards&&b.shards.length){ var shl={strength:"Ability Strength",duration:"Ability Duration",health:"Health",shields:"Shields",armor:"Armor"};
    h+='<p><span class="muted">Archon Shards:</span> '+b.shards.map(function(x){ return esc((x.tauforged?'Tauforged ':'')+x.color)+' '+esc(shl[x.stat]||x.stat)+' <span class="muted">+'+(x.value<1?Math.round(x.value*100)+'%':num(x.value))+'</span>'; }).join(' · ')+'</p>'; }
  else if(FOPTS.shards!=="none"&&b.mods) h+='<p class="muted">No Archon Shards you own fit this build.</p>';
  h+='<div class="buildstats"><span>Strength <b>'+pct(s.strength)+'</b></span><span>Duration <b>'+pct(s.duration)+'</b></span><span>Range <b>'+pct(s.range)+'</b></span><span>Efficiency <b>'+pct(s.efficiency)+'</b></span></div>';
  h+='<div class="buildstats"><span>Health <b>'+num(s.health)+'</b></span><span>Shields <b>'+num(s.shields)+'</b></span><span>Armor <b>'+num(s.armor)+'</b> ('+pct(s.damage_reduction)+' less damage)</span><span>Effective health <b>'+num(s.effective_health)+'</b></span><span>Energy <b>'+num(s.energy)+'</b></span></div>';
  h+='<p class="muted">Uses: '+b.abilities.filter(function(a){return a.used}).map(function(a){ var u=[]; if(a.strength) u.push("Strength"); if(a.duration) u.push("Duration"); if(a.range) u.push("Range"); return esc(a.name)+' ('+(u.join(", ")||"no scaling")+(a.channeled?", channeled":"")+')'; }).join(' · ')+'</p>';
  if(b.upgrade) h+='<p>Best mod you don\'t have: <b>'+esc(b.upgrade.name)+'</b></p>';
  h+='<ul class="muted buildnotes">'+b.notes.map(function(n){return '<li>'+esc(n)+'</li>'}).join('')+'</ul>';
  return h;
}
function runFrameBuild(id){
  var keys=fChosen(id);
  if(FBUILD["last:"+id] && !keys.length){ toast("Tick at least one ability you use."); return; }
  var augs=fAugments(id), arcs=fArcanes(id);
  var q=(arcs.length?"&arcanes="+arcs.map(encodeURIComponent).join(","):"");
  q="/api/frame-build?id="+encodeURIComponent(id)+q+"&surv="+encodeURIComponent(FOPTS.surv)+"&shards="+encodeURIComponent(FOPTS.shards)+"&owned="+(BUILD_OPTS.owned&&DATA.meta.inventory?1:0)+(keys.length?"&abilities="+keys.join(","):"")+(augs.length?"&augments="+augs.map(encodeURIComponent).join(","):"");
  var k=fKey(id);
  api(q).then(function(b){ FBUILD[k]=b; FBUILD["shown:"+id]=b; if(!b.error) FBUILD["last:"+id]=b; redrawTable(); }).catch(function(){ FBUILD[k]={error:"Could not work that out. Is OpenWarframe still running?"}; redrawTable(); });
}
function onFrameBuildEvent(e){
  var t=e.target; if(!t.closest) return;
  var fo=t.closest("[data-fopt]"); if(fo&&e.type==="change"){ FOPTS[fo.dataset.fopt]=fo.value; return; }
  var fa=t.closest("[data-farc]"); if(fa&&e.type==="change"){ var aid=fa.dataset.farc; FOPTS.arcanes[aid]=FOPTS.arcanes[aid]||["",""]; FOPTS.arcanes[aid][+fa.dataset.slot]=fa.value; return; }
  var au=t.closest("[data-faug]"); if(au&&e.type==="change"){ var fid=au.dataset.faug; FOPTS.augments[fid]=FOPTS.augments[fid]||{}; FOPTS.augments[fid][au.value]=au.checked; return; }
  var ab=t.closest("[data-fab]"); if(ab&&e.type==="change"){ var id=ab.dataset.fab; FOPTS.abilities[id]=FOPTS.abilities[id]||{}; FOPTS.abilities[id][ab.value]=ab.checked; return; }
  var b=t.closest("[data-fbuild]"); if(b&&e.type==="click"){ e.stopPropagation(); runFrameBuild(b.dataset.fbuild); }
}
$("view").addEventListener("click", onFrameBuildEvent, true);
$("view").addEventListener("change", onFrameBuildEvent);

