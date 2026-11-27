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
  h+='<div class="buildstats"><span>Damage per second <b>'+num(s.total_dps)+'</b></span><span>Direct hits <b>'+num(s.direct_dps)+'</b></span><span>Status damage over time <b>'+num(s.status_dps)+'</b></span></div>';
  h+='<div class="buildstats"><span>Per shot <b>'+num(s.per_shot)+'</b> before armor</span><span>Crit <b>'+pct(s.crit_chance)+'</b> × '+num(s.crit_multiplier)+'</span><span>Status <b>'+pct(s.status_chance)+'</b> ('+num(s.procs_per_second)+' procs/s)</span><span>Multishot <b>'+num(s.multishot)+'</b></span><span>Fire rate <b>'+num(s.fire_rate)+'</b></span></div>';
  var fx=[];
  if(s.armor_reduction) fx.push('armor '+Math.round(s.armor).toLocaleString()+' stops '+pct(s.armor_reduction));
  if(s.corrosive_stacks>=0.5) fx.push(num(s.corrosive_stacks)+' Corrosive stacks');
  if(s.heat_uptime>=0.05) fx.push('Heat strip '+pct(s.heat_uptime)+' of the time');
  if(s.viral_stacks>=0.5) fx.push(num(s.viral_stacks)+' Viral stacks');
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
