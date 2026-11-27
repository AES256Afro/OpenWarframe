// ===== focus mode =====================================================================
var GLOSSARY=[
  ["Relic, Intact to Radiant","Void relics open in fissure missions. Refining one with Void Traces (Intact, Exceptional, Flawless, Radiant) raises the chance of its rare reward."],
  ["Fissure","A mission with a Void tear where you open a relic. The tier (Lith, Meso, Neo, Axi, Requiem, Omnia) says which relics it takes; Omnia takes any."],
  ["Vaulted","A Prime item whose relics no longer drop anywhere. Its parts come from relics you already own or from other players."],
  ["Rotation A, B, C","In endless missions the reward table changes every few rounds or minutes: A, A, B, C, then C again."],
  ["Steel Path","A harder copy of the star chart that opens once you finish every normal node. It gives mastery again."],
  ["Ducats","What Baro Ki'Teer takes. Sell spare Prime parts for ducats at a Relay kiosk."],
  ["Score (What to farm)","How much of what you still need one run can drop. Each drop you need adds its drop chance, and a relic counts once for every part you need inside it. Higher is better. It does not count how long the mission takes."],
  ["Invasion sides","Each invasion is a fight between two factions. Side with one and you get that side's reward after three missions."],
  ["Mastery, rank 30 and 40","Leveling a frame or weapon to 30 gives mastery once. Kuva, Tenet, Coda, Paracesis and Necramechs go to 40 for more."]
];
var DAILY=[
  {id:"sortie", t:"Sortie", m:20, why:"Three missions for a riven, Kuva or Endo roll", needs:"The War Within quest"},
  {id:"incursions", t:"Steel Path incursions", m:25, why:"5 marked Steel Path nodes, 5 Steel Essence each", needs:"the whole star chart (Steel Path)"},
  {id:"standing", t:"Syndicate standing cap", m:20, why:"Standing resets daily; unused standing is lost"},
  {id:"nightwave_d", t:"Nightwave daily", m:5, why:"Quick Nightwave standing"},
  {id:"foundry_d", t:"Claim and queue the Foundry", m:2, why:"Keep builds running while you play"}
];
var WEEKLY=[
  {id:"archon", t:"Archon Hunt", m:30, why:"An Archon Shard every week", needs:"The New War quest"},
  {id:"nightwave_w", t:"Nightwave weeklies", m:30, why:"Most of the week's Nightwave standing"},
  {id:"circuit", t:"The Circuit (Duviri)", m:30, why:"Incarnon adapters and Warframe choices rotate weekly", needs:"The Duviri Paradox quest"},
  {id:"netracells", t:"Netracells", m:25, why:"Five runs a week for archon shards and arcanes", needs:"Whispers in the Walls quest"},
  {id:"archimedea", t:"Deep Archimedea", m:40, why:"Weekly arcane and shard chances", needs:"Whispers in the Walls quest"},
  {id:"kahl", t:"Kahl's Garrison", m:15, why:"Stock for Kahl's shop", needs:"Veilbreaker quest"},
  {id:"maroo", t:"Maroo's Ayatan treasure hunt", m:10, why:"A free Ayatan sculpture"},
  {id:"iron_wake", t:"Paladino at Iron Wake", m:5, why:"Weekly Riven slot or Kuva trades"}
];
function dayKey(){ return new Date().toISOString().slice(0,10); }
function weekKey(){ var d=new Date(); var day=(d.getUTCDay()+6)%7; var mon=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate()-day)); return "w"+mon.toISOString().slice(0,10); }
function untilReset(weekly){ var n=new Date(); var next=new Date(Date.UTC(n.getUTCFullYear(),n.getUTCMonth(),n.getUTCDate()+1)); if(weekly){ var day=(n.getUTCDay()+6)%7; next=new Date(Date.UTC(n.getUTCFullYear(),n.getUTCMonth(),n.getUTCDate()+7-day)); } var h=Math.floor((next-n)/3600000); return h>=24?Math.floor(h/24)+"d "+(h%24)+"h":h+"h "+Math.floor(((next-n)%3600000)/60000)+"m"; }
function checked(list,id){ var k=list==="d"?dayKey():weekKey(); return !!((PREFS.checks||{})[k]||{})[id]; }
function setCheck(list,id,on){ var k=list==="d"?dayKey():weekKey(); PREFS.checks=PREFS.checks||{}; PREFS.checks[k]=PREFS.checks[k]||{}; PREFS.checks[k][id]=on; savePrefs(); }
function hiddenRoutine(id){ return ((PREFS.settings||{}).hide||[]).indexOf(id)>=0; }
// Late-game routines need a story quest (or the whole star chart). The profile can't say
// which quests are done, so until Steel Path is open they wait in "Unlocks later" instead
// of nagging a new player every day.
// Steel Path missions only make sense once the star chart is done (the Steel Path is open).
function spOk(f){
  if(steelPathOnly()) return !!f.steel_path;  // the player only runs Steel Path
  return !f.steel_path || !!(DATA&&DATA.meta.steel_path_unlocked);
}
// "Steel Path only" on Live also steers the Right now pick and the fissure suggestions
function steelPathOnly(){ var lf=VIEW==="live"?F:((PREFS.views||{}).live||{}).F; return !!(lf&&lf._sponly===true); }
function lockedRoutine(x){ return !!x.needs && !(DATA&&DATA.meta.steel_path_unlocked); }
function savePrefs(){
  if(!PREFS_LOADED) return;  // a save before /api/prefs answers would wipe goals and ticks
  // keep only this and last period's ticks
  var keep={}; var dk=dayKey(), wk=weekKey(); Object.keys(PREFS.checks||{}).forEach(function(k){ if(k===dk||k===wk) keep[k]=PREFS.checks[k]; }); PREFS.checks=keep;
  api("/api/prefs",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(PREFS)}).catch(function(){ toast("Could not save. Is OpenWarframe still running?"); });
}
// Goals: PREFS.goals is the ordered list of item ids (as before). Finished ones move to
// PREFS.settings.goals_done, so older versions still read the list.
function goalsDone(){ var st=PREFS.settings||{}; return Array.isArray(st.goals_done)?st.goals_done:[]; }
function activeGoals(){ var dn=goalsDone(); return (PREFS.goals||[]).filter(function(g){return dn.indexOf(g)<0}); }
function isGoal(id){ return activeGoals().indexOf(id)>=0; }
function toggleGoal(id){ PREFS.goals=PREFS.goals||[]; var i=PREFS.goals.indexOf(id); if(i>=0) PREFS.goals.splice(i,1); else PREFS.goals.push(id);
  PREFS.settings=PREFS.settings||{}; PREFS.settings.goals_done=goalsDone().filter(function(g){return g!==id});
  savePrefs(); renderAll(); toast(i>=0?"Goal removed":"Added to your goals. It shows on the Focus screen."); }
function moveGoal(id, by){ var g=PREFS.goals||[], i=g.indexOf(id), j=i+by; if(i<0||j<0||j>=g.length) return; g[i]=g[j]; g[j]=id; savePrefs(); renderAll(); }
function goalDone(id){ PREFS.goals=(PREFS.goals||[]).filter(function(g){return g!==id}); PREFS.settings=PREFS.settings||{};
  PREFS.settings.goals_done=goalsDone().filter(function(g){return g!==id}).concat([id]); savePrefs(); renderAll();
  toast("Goal done. Nice work.", 0, {label:"Undo", run:function(){ PREFS.settings.goals_done=goalsDone().filter(function(g){return g!==id}); PREFS.goals.push(id); savePrefs(); renderAll(); }}); }
function forgetDone(id){ PREFS.settings=PREFS.settings||{}; PREFS.settings.goals_done=goalsDone().filter(function(g){return g!==id}); savePrefs(); renderAll(); }
// "Show me" on a goal or a one-piece-away idea opens that item's card in Finish an item
function showMe(s){ if(s.item) openView("farm", {sub:"finish", id:s.item}, true); else openView(s.go); }
// Display names for goal ids that are no longer in Finish an item: from the list, then the server
var NAMES={}, NAMES_ASKED={};
function splitCamel(id){ return String(id).split("/").pop().replace(/([a-z0-9])([A-Z])/g,"$1 $2"); }
function goalName(id){
  if(NAMES[id]) return NAMES[id];
  var it=(DATA&&DATA.items||[]).find(function(x){return x.id===id}); if(it) return it.name;
  return splitCamel(id);
}
function askNames(ids){
  ids=ids.filter(function(id){ return !NAMES[id] && !NAMES_ASKED[id] && !(DATA.items||[]).some(function(x){return x.id===id}); });
  if(!ids.length) return;
  ids=ids.slice(0,500); ids.forEach(function(id){ NAMES_ASKED[id]=1; });
  api("/api/names?ids="+ids.map(encodeURIComponent).join(",")).then(function(d){
    if(!d||typeof d!=="object") return;
    ids.forEach(function(id){ if(typeof d[id]==="string"&&d[id]) NAMES[id]=d[id]; });
    if(VIEW==="focus") renderAll();
  }).catch(function(){});  // the CamelCase fallback stays
}
function skippedToday(id){ return (PREFS.skipped||{})[id]===dayKey(); }
function skip(id, quiet){ PREFS.skipped=PREFS.skipped||{}; PREFS.skipped[id]=dayKey(); var keep={}; Object.keys(PREFS.skipped).forEach(function(k){ if(PREFS.skipped[k]===dayKey()) keep[k]=PREFS.skipped[k]; }); PREFS.skipped=keep; savePrefs(); renderAll();
  if(!quiet) toast("Hidden until tomorrow.", 0, {label:"Undo", run:function(){ unskip(id); }}); }
function unskip(id){ if(PREFS.skipped) delete PREFS.skipped[id]; savePrefs(); renderAll(); }

function cap(s){ return s.charAt(0).toUpperCase()+s.slice(1); }
// How to get one missing piece, honest about which relics you own.
function pieceRoute(p){
  var src=(p.sources||[])[0]||"";
  if(p.crack==null) return {can:true, chance:0, what:"get the "+p.name, where:src.split(":")[0], why:src||"No drop source recorded."};
  if(p.crack.length){ var r=p.crack[0];
    return {can:true, chance:r.intact||0, what:"crack "+r.relic+" for the "+p.name, where:"Any "+r.tier+" fissure",
      why:"You have "+r.have+" "+r.relic+" ("+r.rarity.toLowerCase()+": "+r.intact+"% intact, "+r.radiant+"% radiant)."}; }
  if(p.relic_only){ var fr=p.farm_relic;
    if(fr) return {can:false, chance:0, what:"farm "+fr.relic+" relics, then crack one for the "+p.name, where:fr.where,
      why:"You have none of the relics that hold it. "+fr.relic+" drops on "+fr.where+(fr.mission?" ("+fr.mission+", rotation "+fr.rotation+")":"")+"."};
    return {can:false, chance:0, what:"trade for the "+p.name, where:"Trade chat or warframe.market", why:"Only vaulted relics hold it, and you have none of them."}; }
  return {can:true, chance:0, what:"get the "+p.name, where:src.split(":")[0], why:src};
}
function suggestions(){
  var out=[], f=DATA.farm||{}, inv=DATA.meta.inventory;
  // console accounts can't load an inventory at all: don't make it a daily task they can't do
  if(!inv && caps().game_here) out.push({id:"inventory", what:"Load your inventory so ideas match what you own", where:caps().grab?"Warframe running, you in your Orbiter":"An inventory file from a Windows PC", why:invHint(DATA.meta.inventory_error||"Right now relic, blueprint and Foundry ideas are guesses, because the app cannot see what you own."), m:1, action:"grab"});
  var ready=(DATA.foundry||[]).filter(function(x){return x.ready});
  if(ready.length) out.push({id:"foundry", what:"Claim "+ready.length+" finished item"+(ready.length===1?"":"s")+" in your Foundry", where:"Your Orbiter, Foundry", why:ready.map(function(x){return x.name}).slice(0,4).join(", "), m:2, go:"foundry", routine:"d", rid:"foundry_d"});
  activeGoals().forEach(function(gid){
    var c=(f.finish||[]).find(function(x){return x.id===gid}); if(!c) return;
    var p=c.pieces.find(function(x){return x.short!==0}); if(!p){ out.push({id:"goal-build:"+gid, what:"Build "+c.name, where:"Your Orbiter, Foundry", why:"Every piece is in your inventory. Your goal is one build away.", m:2, go:"farm", item:gid}); return; }
    var gr=pieceRoute(p);
    out.push({id:"goal:"+gid+":"+p.name, what:cap(gr.what)+" ("+c.name+" goal)", where:gr.where, why:"Your goal. "+gr.why, m:gr.can?10:20, go:"farm", item:gid});
  });
  if(LIVE&&LIVE.fissures){ var fz=LIVE.fissures.filter(function(x){return x.useful_relics && x.best_relic && (!inv || x.best_relic_count) && spOk(x)})[0];
    if(fz){
      var why=inv?("Bring "+fz.best_relic+": you have "+fz.best_relic_count+", and it holds "+fz.best_relic_needed+" part"+(fz.best_relic_needed===1?"":"s")+" you need. "+fz.minutes_left+" min left.")
                 :(fz.useful_relics+" "+fz.tier+" relics hold parts you need, "+fz.best_relic+" most of all, if you have it. "+fz.minutes_left+" min left. Load your inventory to see which you own.");
      out.push({id:"fissure:"+fz.id, what:inv?("Run the "+fz.tier+" "+fz.mission+" fissure on "+fz.where):("If you have "+fz.tier+" relics: run the "+fz.mission+" fissure on "+fz.where), where:fz.where+(fz.steel_path?" (Steel Path)":""), why:why, m:fz.fast?5:10, go:"live"}); } }
  if(LIVE&&LIVE.baro&&LIVE.baro.here){ var duc=(DATA.sell||[]).filter(function(r){return r.spare}).reduce(function(a,r){return a+r.ducats_total},0);
    if(duc) out.push({id:"baro", what:"Turn spare Prime parts into ducats, then visit Baro", where:LIVE.baro.where, why:duc+" ducats from spares. Baro leaves in "+LIVE.baro.hours_left+" h.", m:10, go:"sell"}); }
  var inc=((LIVE&&LIVE.weekly)||[]).filter(function(r){return r.kind==="Circuit, Steel Path" && r.for_you})[0];
  if(inc && (DATA.meta.steel_path_unlocked)) out.push({id:"circuit:"+inc.id, what:"Take the "+inc.what+" from the Steel Path Circuit", where:"Duviri, the Circuit (Steel Path)", why:inc.note+"."+(inc.hours_left!=null?" This week's choice changes in "+Math.max(1,Math.round(inc.hours_left/24))+" d.":""), m:30, go:"live"});
  var hm=DATA.helminth;
  if(hm && hm.candidates.length) out.push({id:"helminth:"+hm.candidates[0], what:"Feed "+hm.candidates[0]+" to the Helminth", where:"Your Orbiter, Helminth room", why:"You've mastered it and its ability isn't subsumed yet; every frame can then use it. "+(hm.candidates.length>1?(hm.candidates.length-1)+" more mastered frames could go next.":"It's the last one you own."), m:5});
  var ownedOnly=(PREFS.settings||{}).ownedonly!==false;
  var one=(f.finish||[]).filter(function(x){return x.missing===1 && !isGoal(x.id)})
    .map(function(c){ var p=c.pieces.find(function(x){return x.short!==0}); return p?{c:c,p:p,r:pieceRoute(p)}:null; })
    .filter(function(x){ return x && (x.r.can || !ownedOnly); });
  one.sort(function(a,b){ return (b.r.can-a.r.can) || (b.r.chance-a.r.chance); });
  one.slice(0,3).forEach(function(x){ out.push({id:"one:"+x.c.id, what:"Finish "+x.c.name+": "+x.r.what, where:x.r.where, why:"One piece away. "+x.r.why, m:x.r.can?10:20, go:"farm", item:x.c.id}); });
  var mis=(f.missions||[])[0]; if(mis) out.push({id:"mission:"+mis.id, what:"Run "+mis.place+" · "+mis.mission+", rotation "+mis.best_rotation, where:mis.place, why:"Drops the most of what you need: "+(mis.gives[0]||"").split(" · ")[0]+".", m:5, go:"farm"});
  var ck=(f.crack||[])[0]; if(ck) out.push({id:"crack:"+ck.id, what:"Crack "+ck.name+" in any "+ck.name.split(" ")[0]+" fissure", where:"Void Fissures", why:"You have "+ck.count+"; it holds "+ck.needed+" part"+(ck.needed===1?"":"s")+" you need.", m:5, go:"live"});
  DAILY.forEach(function(x){ if(x.id==="foundry_d" && ready.length) return; if(!checked("d",x.id) && !hiddenRoutine(x.id) && !lockedRoutine(x)) out.push({id:"daily:"+x.id, what:x.t, where:"Daily", why:x.why+". Resets in "+untilReset(false)+".", m:x.m, routine:"d", rid:x.id}); });
  WEEKLY.forEach(function(x){ if(!checked("w",x.id) && !hiddenRoutine(x.id) && !lockedRoutine(x)) out.push({id:"weekly:"+x.id, what:x.t, where:"Weekly", why:x.why+". Resets in "+untilReset(true)+".", m:x.m, routine:"w", rid:x.id}); });
  out=out.filter(function(s){ return !skippedToday(s.id); });
  if(EASY) out=out.map(function(s,i){return [s,i]}).sort(function(a,b){return (a[0].m-b[0].m)||(a[1]-b[1])}).map(function(x){return x[0]});
  return out;
}
function doneSuggestion(s){ if(s.action==="grab"){ if(caps().grab){ grab(false); } else { $("invfile").click(); } return; }
  var k=null; if(s.routine){ k=s.routine==="d"?dayKey():weekKey(); PREFS.checks=PREFS.checks||{}; PREFS.checks[k]=PREFS.checks[k]||{}; PREFS.checks[k][s.rid]=true; }
  skip(s.id, true);
  // Done sits on every screen, so a misclick is easy: offer the way back
  toast("Nice. Next one is up.", 0, {label:"Undo", run:function(){ if(k&&PREFS.checks[k]) delete PREFS.checks[k][s.rid]; unskip(s.id); }}); }
function renderFocusBar(){
  var el=$("fbar");
  // one next action per screen: Focus, Live and What to farm have their own headline card
  if(!DATA||VIEW==="focus"||VIEW==="live"||VIEW==="farm"||(PREFS.settings||{}).bar===false){ el.hidden=true; return; }
  var s=suggestions()[0]; if(!s){ el.hidden=true; return; }
  el.hidden=false;
  el.innerHTML='<span class="lbl">Next</span><span class="what">'+esc(s.what)+' <span class="why">· '+esc(s.why)+'</span></span>'+
    '<button class="btn primary" type="button" id="fb-done">Done</button><button class="btn" type="button" id="fb-skip">Not now</button><button class="btn" type="button" id="fb-focus">Open Focus</button>';
  $("fb-done").onclick=function(){ doneSuggestion(s); };
  $("fb-skip").onclick=function(){ skip(s.id); };
  $("fb-focus").onclick=function(){ openView("focus"); };
}
function planSession(minutes){
  var picked=[], used=0, seen={};
  suggestions().forEach(function(s){ var key=s.go||s.id; if(s.m+used<=minutes && !seen[s.id]){ picked.push(s); used+=s.m; seen[s.id]=1; } });
  SESSION={minutes:minutes, items:picked, used:used, day:dayKey(), started:Date.now()}; SESSION_TICKS={}; saveSession(); renderAll();
}
// the plan survives a reload or a restart on the same day
function saveSession(){ PREFS.session=SESSION?{plan:SESSION, ticks:SESSION_TICKS}:null; savePrefs(); }
function restoreSession(){ var p=PREFS.session; if(p&&p.plan&&p.plan.day===dayKey()){ SESSION=p.plan; SESSION_TICKS=p.ticks||{}; } }
function sessionLeft(){ return SESSION&&SESSION.started?Math.ceil((SESSION.started+SESSION.minutes*60000-Date.now())/60000):null; }
function sessionTimeCheck(){
  var left=sessionLeft();
  if(left!=null && left<=0 && !SESSION.ended){ SESSION.ended=true; saveSession(); toast("Your "+SESSION.minutes+" minutes are up. A good moment to stop or plan another session.", 10000); }
}
function applySettings(){
  var s=PREFS.settings||{}, root=document.documentElement;
  document.body.style.zoom=s.zoom||1;
  document.body.classList.toggle("big-text", (s.zoom||1)>=1.5);  // zoom doubles the sidebar too
  root.classList.toggle("hc", !!s.contrast);
  root.classList.toggle("calm", !!s.calm);
}
function setSetting(k,v){ PREFS.settings=PREFS.settings||{}; PREFS.settings[k]=v; savePrefs(); applySettings(); renderAll(); }
function renderFocus(){
  loadLive(false);
  var list=suggestions(), s=list[0], f=DATA.farm||{};
  var h='<div class="focus">';
  if(s){
    h+='<div class="big"><div class="eyebrow" style="font:600 11px var(--mono);letter-spacing:.14em;color:var(--gold)">DO THIS NOW</div><div class="what">'+esc(s.what)+'</div>';
    h+='<div class="why">'+esc(s.why)+'</div><div class="meta"><span>Where: <b>'+esc(s.where||"-")+'</b></span><span>About '+s.m+' min</span><span>'+(list.length-1)+' more ideas after this</span></div>';
    h+='<div class="acts"><button class="btn primary" type="button" id="fx-done">Done, next</button><button class="btn" type="button" id="fx-skip">Not now</button><button class="btn" type="button" id="fx-tired">'+(EASY?'Back to the usual order':'I\'m tired, give me something easy')+'</button>'+(s.go?'<button class="btn" type="button" id="fx-go">Show me</button>':'')+'</div></div>';
  } else h+='<div class="big"><div class="what">You are all caught up for today.</div><div class="why">Pick a goal below, or open What to farm for more ideas.</div></div>';

  h+='<div class="row2">';
  // session planner
  h+='<div class="box"><h2>Plan a session <span class="muted">Picks things that fit your time</span></h2><div class="seg">'+[15,30,60,90].map(function(m){return '<button type="button" data-plan="'+m+'" aria-pressed="'+(SESSION&&SESSION.minutes===m)+'">'+m+' min</button>'}).join('')+'</div>';
  if(SESSION){
    var doneN=Object.keys(SESSION_TICKS).filter(function(k){return SESSION_TICKS[k]}).length;
    var left=sessionLeft();
    h+='<div class="muted">'+SESSION.items.length+' steps, about '+SESSION.used+' min. '+doneN+' done.'+(left!=null?(left>0?' <b>'+left+' min left.</b>':' <b>Time is up.</b>'):'')+'</div>';
    h+=SESSION.items.map(function(x,i){return '<label class="tick"><input type="checkbox" data-st="'+i+'"'+(SESSION_TICKS[i]?' checked':'')+'><span class="t">'+esc(x.what)+'<small>'+esc(x.why)+'</small></span><span class="m">'+x.m+' min</span></label>'}).join('');
    if(SESSION.items.length && doneN===SESSION.items.length) h+='<p><b>Session done.</b></p>';
  } else h+='<p class="muted">How long do you want to play? Pick a time and you get a short list to work through.</p>';
  h+='</div>';
  // goals
  var mr=DATA.meta, mrPct=mr.next?Math.min(100,Math.round(100*mr.estimate/mr.next)):0;
  h+='<div class="box"><h2>Goals <span class="muted">Add more from Finish an item or any item\'s details</span></h2>';
  h+='<div class="goal"><b>Reach MR '+(mr.mr+1)+'</b><div class="bar"><i style="width:'+mrPct+'%"></i></div><span class="muted">≈'+(mr.estimate||0).toLocaleString()+' of '+(mr.next||0).toLocaleString()+' mastery</span></div>';
  var goals=activeGoals(), done=goalsDone();
  askNames(goals.concat(done).filter(function(g){ return !(f.finish||[]).some(function(x){return x.id===g}); }));
  goals.forEach(function(gid,i){ var c=(f.finish||[]).find(function(x){return x.id===gid});
    var nm=c?c.name:goalName(gid);
    var acts='<span class="acts"><button class="btn" type="button" data-gup="'+esc(gid)+'" aria-label="Move '+esc(nm)+' up"'+(i===0?' disabled':'')+'>Up</button><button class="btn" type="button" data-gdown="'+esc(gid)+'" aria-label="Move '+esc(nm)+' down"'+(i===goals.length-1?' disabled':'')+'>Down</button>'
      +'<button class="btn" type="button" data-gdone="'+esc(gid)+'">Done</button><button class="btn" type="button" data-ungoal="'+esc(gid)+'">Remove</button></span>';
    if(!c){ h+='<div class="goal"><b>'+esc(nm)+'</b><span class="muted">Not in Finish an item: built, owned, or no parts to track.</span>'+acts+'</div>'; return; }
    var have=c.total-c.missing, pct=c.total?Math.round(100*have/c.total):0;
    h+='<div class="goal"><b>Build '+esc(c.name)+'</b><div class="bar"><i style="width:'+pct+'%"></i></div><span class="muted">'+have+' of '+c.total+' pieces'+(c.missing?'':' · ready to build')+'</span>'+acts+'</div>'; });
  if(!goals.length) h+='<p class="muted">No item goals yet. On any card in Finish an item, click Make this my goal, or open an item in All items and click Add to goals.</p>';
  if(done.length) h+='<details><summary class="muted">Done <span>'+done.length+'</span></summary>'+done.map(function(gid){ return '<div class="goal done"><b>'+esc(goalName(gid))+'</b><span class="acts"><button class="btn" type="button" data-gforget="'+esc(gid)+'">Remove</button></span></div>'; }).join('')+'</details>';
  h+='</div>';
  // checklists
  var lst=function(title,items,key,weekly){ var vis=items.filter(function(x){return !hiddenRoutine(x.id) && !lockedRoutine(x)}); var done=vis.filter(function(x){return checked(key,x.id)}).length;
    var o='<div class="box"><h2>'+title+' <span class="muted">'+done+' of '+vis.length+' · resets in '+untilReset(weekly)+'</span></h2>';
    o+=vis.map(function(x){return '<label class="tick"><input type="checkbox" data-ck="'+key+':'+x.id+'"'+(checked(key,x.id)?' checked':'')+'><span class="t">'+esc(x.t)+'<small>'+esc(x.why)+'</small></span><span class="m">'+x.m+' min</span></label>'}).join('');
    return o+'</div>'; };
  h+=lst("Today",DAILY,"d",false)+lst("This week",WEEKLY,"w",true);
  var later=DAILY.concat(WEEKLY).filter(function(x){return lockedRoutine(x) && !hiddenRoutine(x.id)});
  if(later.length) h+='<details class="box"><summary><b>Unlocks later</b> <span class="muted">'+later.length+' routines that open with story quests</span></summary>'+later.map(function(x){return '<div class="tick opt"><span></span><span class="t">'+esc(x.t)+'<small>'+esc(x.why)+'. Needs '+esc(x.needs)+'.</small></span><span></span></div>'}).join('')+'</details>';
  h+='<details class="box"><summary><b>What do these words mean?</b></summary><dl class="gloss">'+GLOSSARY.map(function(g){return '<dt>'+esc(g[0])+'</dt><dd>'+esc(g[1])+'</dd>'}).join('')+'</dl></details>';
  // comfort
  var st=PREFS.settings||{};
  h+='<div class="box"><h2>Comfort</h2>';
  h+='<div>Text size <span class="seg">'+[[1,"100%"],[1.15,"115%"],[1.3,"130%"],[1.5,"150%"],[1.75,"175%"],[2,"200%"]].map(function(z){return '<button type="button" data-zoom="'+z[0]+'" aria-pressed="'+((st.zoom||1)===z[0])+'">'+z[1]+'</button>'}).join('')+'</span></div>';
  h+='<label class="tick opt"><input type="checkbox" id="st-contrast"'+(st.contrast?' checked':'')+'><span class="t">Higher contrast</span><span></span></label>';
  h+='<label class="tick opt"><input type="checkbox" id="st-calm"'+(st.calm?' checked':'')+'><span class="t">No motion</span><span></span></label>';
  h+='<label class="tick opt"><input type="checkbox" id="st-bar"'+(st.bar!==false?' checked':'')+'><span class="t">Show the Next bar on every screen</span><span></span></label>';
  h+='<label class="tick opt"><input type="checkbox" id="st-owned"'+(st.ownedonly!==false?' checked':'')+'><span class="t">Only suggest relics I already have<small>Off: also suggests farming a relic first</small></span><span></span></label>';
  var langs=DATA.meta.languages||[["en","English"]], nl=DATA.meta.names_lang||"en";
  h+='<div class="tick opt"><span class="t"><label>Item names <select id="st-names">'+langs.map(function(l){return '<option value="'+esc(l[0])+'"'+(l[0]===nl?' selected':'')+'>'+esc(l[1])+'</option>'}).join('')+'</select></label><small>Names of items, parts and relics in the app and exports, as the game shows them. The app\'s own text stays English; search finds both names.</small></span><span></span></div>';
  h+='<label class="tick opt"><input type="checkbox" id="st-updates"'+(st.check_updates!==false?' checked':'')+'><span class="t">Tell me when a new version is out<small>Asks GitHub once a day. Nothing about you is sent.</small></span><span></span></label>';
  h+='<label class="tick opt"><input type="checkbox" id="st-start"'+(st.start!=="last"?' checked':'')+'><span class="t">Open on this Focus screen</span><span></span></label>';
  h+='<div class="tick opt"><span class="t">Account: '+esc(DATA.meta.player||"not named")+' ('+esc((DATA.meta.platform||"pc").toUpperCase())+')<small>Switch to another account. Each account keeps its own profile history and inventory, so you can switch back.</small></span><button class="btn" type="button" id="st-account">Change account</button></div>';
  if(DATA.meta.session_ok) h+='<div class="tick"><span class="t">You allowed reading the game session<small>Get inventory from game reads the running game. Take this back and the app will ask again next time.</small></span><button class="btn" type="button" id="st-consent">Take back permission</button></div>';
  h+='<details><summary class="muted">Hide routine items I never do</summary>'+DAILY.concat(WEEKLY).map(function(x){return '<label class="tick opt"><input type="checkbox" data-hide="'+x.id+'"'+(hiddenRoutine(x.id)?' checked':'')+'><span class="t">Hide '+esc(x.t)+'</span><span></span></label>'}).join('')+'</details>';
  h+='</div>';
  h+='</div></div>';
  $("view").innerHTML=h;
  if(s){
    $("fx-done").onclick=function(){ doneSuggestion(s); };
    if(s.action==="grab") $("fx-done").textContent=caps().grab?"Get inventory from game":"Load inventory file";
    $("fx-skip").onclick=function(){ skip(s.id); };
    $("fx-tired").onclick=function(){ EASY=!EASY; renderAll(); toast(EASY?"Quickest things first. Click again to switch back.":"Back to the usual order."); };
    if($("fx-go")) $("fx-go").onclick=function(){ showMe(s); };
  }
  $("view").querySelectorAll("[data-plan]").forEach(function(b){ b.onclick=function(){ planSession(+b.dataset.plan); }; });
  $("view").querySelectorAll("[data-st]").forEach(function(b){ b.onchange=function(){ SESSION_TICKS[b.dataset.st]=b.checked; var it=SESSION.items[+b.dataset.st];
    if(b.checked && it.routine) setCheck(it.routine,it.rid,true);
    else if(b.checked) skip(it.id, true);  // ticked here: the big card moves on too
    saveSession(); renderAll(); }; });
  $("view").querySelectorAll("[data-ck]").forEach(function(b){ b.onchange=function(){ var p=b.dataset.ck.split(":"); setCheck(p[0],p[1],b.checked); renderAll(); }; });
  $("view").querySelectorAll("[data-ungoal]").forEach(function(b){ b.onclick=function(){ toggleGoal(b.dataset.ungoal); }; });
  $("view").querySelectorAll("[data-gup]").forEach(function(b){ b.onclick=function(){ moveGoal(b.dataset.gup,-1); }; });
  $("view").querySelectorAll("[data-gdown]").forEach(function(b){ b.onclick=function(){ moveGoal(b.dataset.gdown,1); }; });
  $("view").querySelectorAll("[data-gdone]").forEach(function(b){ b.onclick=function(){ goalDone(b.dataset.gdone); }; });
  $("view").querySelectorAll("[data-gforget]").forEach(function(b){ b.onclick=function(){ forgetDone(b.dataset.gforget); }; });
  $("view").querySelectorAll("[data-zoom]").forEach(function(b){ b.onclick=function(){ setSetting("zoom", +b.dataset.zoom); }; });
  $("view").querySelectorAll("[data-hide]").forEach(function(b){ b.onchange=function(){ var hd=((PREFS.settings||{}).hide||[]).filter(function(x){return x!==b.dataset.hide}); if(b.checked) hd.push(b.dataset.hide); setSetting("hide",hd); }; });
  if($("st-account")) $("st-account").onclick=function(){ renderSetup({error:"Type the account ID to switch to. Your current account stays saved, so you can switch back the same way.", setup:true, has_account:false, switching:true}); };
  if($("st-consent")) $("st-consent").onclick=function(){ api("/api/consent/forget",{method:"POST"}).then(function(){ DATA.meta.session_ok=false; renderAll(); toast("Permission taken back. The app will ask before reading the game again."); }).catch(function(){ toast("Could not reach OpenWarframe. Is the app still running?"); }); };
  var bind2=function(id,k,fn){ var e=$(id); if(e) e.onchange=function(){ setSetting(k, fn(e.checked)); }; };
  bind2("st-contrast","contrast",function(v){return v}); bind2("st-calm","calm",function(v){return v});
  var sn=$("st-names"); if(sn) sn.onchange=function(){ var lang=this.value; toast("Getting item names…", 60000);
    api("/api/names",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({lang:lang})}).then(function(d){ if(d.error&&!d.meta){ toast(d.error,9000); renderAll(); return; } HOWTO={}; HOWTO_ASKED={}; load(d); LIVE=null; loadLive(true); toast("Item names: "+sn.options[sn.selectedIndex].text+"."); }).catch(unreachable); };
  bind2("st-bar","bar",function(v){return v}); bind2("st-updates","check_updates",function(v){ setTimeout(checkUpdate, 300); return v; }); bind2("st-owned","ownedonly",function(v){return v}); bind2("st-start","start",function(v){return v?"focus":"last"});
  return [];
}

