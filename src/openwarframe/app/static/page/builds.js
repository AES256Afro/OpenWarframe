// ---- suggested builds for guns: computed from the game data on request -----------------
var BUILD={}, BUILD_OPTS={target:"none", owned:true, stacks:true, level:"sp", stripped:false};
var BUILD_LEVELS=[["none","No armor (damage test)"],["normal","Normal missions"],["sp","Steel Path"]];
var BUILD_TARGETS=[["none","Any enemy"],["Grineer","Grineer"],["Corpus","Corpus"],["Infested","Infested"],["Orokin","Corrupted (Orokin)"],["Murmur","The Murmur"],["Sentient","Sentient"],["Scaldra","Scaldra"],["Techrot","Techrot"]];
function isGun(r){ return r.category==="Primary"||r.category==="Secondary"; }
function buildKey(id){ return [id,BUILD_OPTS.target,BUILD_OPTS.owned&&DATA.meta.inventory?1:0,BUILD_OPTS.stacks?1:0,BUILD_OPTS.level,BUILD_OPTS.stripped?1:0].join("|"); }
function buildPanel(r){
  var inv=!!DATA.meta.inventory;
  var h='<div class="buildbox"><h3>Suggested build</h3><div class="buildopts">'
    +'<label>Against <select data-bopt="target">'+BUILD_TARGETS.map(function(t){return '<option value="'+t[0]+'"'+(t[0]===BUILD_OPTS.target?' selected':'')+'>'+esc(t[1])+'</option>'}).join('')+'</select></label>'
    +'<label>Enemies <select data-bopt="level">'+BUILD_LEVELS.map(function(t){return '<option value="'+t[0]+'"'+(t[0]===BUILD_OPTS.level?' selected':'')+'>'+esc(t[1])+'</option>'}).join('')+'</select></label>'
    +'<label><input type="checkbox" data-bopt="stripped"'+(BUILD_OPTS.stripped?' checked':'')+'> Armor already stripped (abilities, squad)</label>'
    +(inv?'<label><input type="checkbox" data-bopt="owned"'+(BUILD_OPTS.owned?' checked':'')+'> Only mods I own</label>':'')
    +'<label><input type="checkbox" data-bopt="stacks"'+(BUILD_OPTS.stacks?' checked':'')+'> Count on-kill stacks at their maximum</label>'
    +'<button class="btn" type="button" data-build="'+esc(r.id)+'">'+(BUILD[buildKey(r.id)]?'Build again':'Suggest a build')+'</button></div>';
  h+='<div class="buildout" data-buildout="'+esc(r.id)+'">'+(BUILD[buildKey(r.id)]?buildHtml(BUILD[buildKey(r.id)]):(inv?'':'<p class="muted">Without an inventory the build may use mods you don\'t have; load your inventory to limit it to yours.</p>'))+'</div></div>';
  return h;
}
function pct(v){ return Math.round(v*100)+'%'; }
function num(v){ return v>=100?Math.round(v).toLocaleString():(Math.round(v*10)/10).toLocaleString(); }
function buildHtml(b){
  if(b.error) return '<p class="muted">'+esc(b.error)+'</p>';
  var s=b.stats, h='';
  h+='<ol class="buildmods">'+b.mods.map(function(m){ return '<li><b>'+esc(m.name)+'</b> <span class="muted">rank '+m.rank+'/'+m.max_rank+(m.owned===false?' · you don\'t have it':'')+'</span><div class="muted">'+esc(m.why)+'</div></li>'; }).join('')+'</ol>';
  if(s.time_to_kill) h+='<div class="buildstats"><span>Time to kill <b>'+num(s.time_to_kill)+' s</b></span>'+(s.shield_dps?'<span>To shields <b>'+num(s.shield_dps)+'</b>/s</span>':'')+'</div>';
  h+='<div class="buildstats"><span>Damage per second to health <b>'+num(s.total_dps)+'</b></span><span>Direct hits <b>'+num(s.direct_dps)+'</b></span><span>Status damage over time <b>'+num(s.status_dps)+'</b></span></div>';
  h+='<div class="buildstats"><span>Per shot <b>'+num(s.per_shot)+'</b> before armor</span><span>Crit <b>'+pct(s.crit_chance)+'</b> × '+num(s.crit_multiplier)+'</span><span>Status <b>'+pct(s.status_chance)+'</b> ('+num(s.procs_per_second)+' procs/s)</span><span>Multishot <b>'+num(s.multishot)+'</b></span><span>Fire rate <b>'+num(s.fire_rate)+'</b></span></div>';
  var fx=[];
  if(s.armor_reduction) fx.push('armor '+Math.round(s.armor).toLocaleString()+' stops '+pct(s.armor_reduction));
  if(s.corrosive_stacks>=0.5) fx.push(num(s.corrosive_stacks)+' Corrosive stacks');
  if(s.heat_uptime>=0.05) fx.push('Heat strip '+pct(s.heat_uptime)+' of the time');
  if(s.viral_stacks>=0.5) fx.push(num(s.viral_stacks)+' Viral stacks');
  if(s.magnetic_stacks>=0.5) fx.push(num(s.magnetic_stacks)+' Magnetic stacks');
  if(s.cold_stacks>=0.5) fx.push(num(s.cold_stacks)+' Cold stacks');
  if(fx.length) h+='<p class="muted">On the enemy: '+esc(fx.join(' · '))+'</p>';
  h+='<p class="muted">Damage: '+b.elements.map(function(e){return esc(e[0])+' '+num(e[1])}).join(' · ')+'</p>';
  if(b.upgrade) h+='<p>Best mod you don\'t have: <b>'+esc(b.upgrade.name)+'</b> <span class="muted">('+esc(b.upgrade.gain)+' more damage per second)</span></p>';
  if(b.notes&&b.notes.length) h+='<ul class="muted buildnotes">'+b.notes.map(function(n){return '<li>'+esc(n)+'</li>'}).join('')+'</ul>';
  return h;
}
function runBuild(id){
  var k=buildKey(id);
  [].forEach.call(document.querySelectorAll("[data-buildout]"), function(el){ if(el.getAttribute("data-buildout")===id) el.innerHTML='<p class="muted">Working out the best mods…</p>'; });
  var q="/api/build?id="+encodeURIComponent(id)+"&target="+encodeURIComponent(BUILD_OPTS.target)+"&owned="+(BUILD_OPTS.owned&&DATA.meta.inventory?1:0)+"&stacks="+(BUILD_OPTS.stacks?1:0)+"&level="+encodeURIComponent(BUILD_OPTS.level)+"&stripped="+(BUILD_OPTS.stripped?1:0);
  api(q).then(function(b){ BUILD[k]=b; redrawTable(); }).catch(function(){ BUILD[k]={error:"Could not work that out. Is OpenWarframe still running?"}; redrawTable(); });
}
function onBuildEvent(e){
  var t=e.target; if(!t.closest) return;
  var opt=t.closest("[data-bopt]");
  if(opt && e.type==="change"){ var k=opt.dataset.bopt; BUILD_OPTS[k]=opt.type==="checkbox"?opt.checked:opt.value; return; }
  var b=t.closest("[data-build]"); if(b && e.type==="click"){ e.stopPropagation(); runBuild(b.dataset.build); }
}
$("view").addEventListener("click", onBuildEvent, true);
$("view").addEventListener("change", onBuildEvent);
// ---- Warframe builds: balance the stats the abilities you use scale with -----------------------
var FBUILD={}, FOPTS={surv:"some", abilities:{}, augments:{}, shards:"none"};
function isFrame(r){ return r.category==="Warframe"; }
// abilities ticked for a frame: every one from the last build unless you untick it
function fChosen(id){
  var last=FBUILD["last:"+id], sel=FOPTS.abilities[id]||{};
  if(!last||!last.abilities) return [];
  return last.abilities.filter(function(a){ return sel[a.key]!==false; }).map(function(a){ return String(a.key); });
}
function fAugments(id){ var a=FOPTS.augments[id]||{}; return Object.keys(a).filter(function(k){return a[k]}).sort(); }
function fKey(id){ return [id,FOPTS.surv,fChosen(id).join(",")||"all",BUILD_OPTS.owned&&DATA.meta.inventory?1:0,fAugments(id).join(","),FOPTS.shards].join("|"); }
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
  var augs=fAugments(id);
  var q="/api/frame-build?id="+encodeURIComponent(id)+"&surv="+encodeURIComponent(FOPTS.surv)+"&shards="+encodeURIComponent(FOPTS.shards)+"&owned="+(BUILD_OPTS.owned&&DATA.meta.inventory?1:0)+(keys.length?"&abilities="+keys.join(","):"")+(augs.length?"&augments="+augs.map(encodeURIComponent).join(","):"");
  var k=fKey(id);
  api(q).then(function(b){ FBUILD[k]=b; FBUILD["shown:"+id]=b; if(!b.error) FBUILD["last:"+id]=b; redrawTable(); }).catch(function(){ FBUILD[k]={error:"Could not work that out. Is OpenWarframe still running?"}; redrawTable(); });
}
function onFrameBuildEvent(e){
  var t=e.target; if(!t.closest) return;
  var fo=t.closest("[data-fopt]"); if(fo&&e.type==="change"){ FOPTS[fo.dataset.fopt]=fo.value; return; }
  var au=t.closest("[data-faug]"); if(au&&e.type==="change"){ var fid=au.dataset.faug; FOPTS.augments[fid]=FOPTS.augments[fid]||{}; FOPTS.augments[fid][au.value]=au.checked; return; }
  var ab=t.closest("[data-fab]"); if(ab&&e.type==="change"){ var id=ab.dataset.fab; FOPTS.abilities[id]=FOPTS.abilities[id]||{}; FOPTS.abilities[id][ab.value]=ab.checked; return; }
  var b=t.closest("[data-fbuild]"); if(b&&e.type==="click"){ e.stopPropagation(); runFrameBuild(b.dataset.fbuild); }
}
$("view").addEventListener("click", onFrameBuildEvent, true);
$("view").addEventListener("change", onFrameBuildEvent);

