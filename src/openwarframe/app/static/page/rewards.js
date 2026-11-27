// ===== reward helper ====================================================================
function rewardPoll(on){
  if(on && !REWARD_POLL){ REWARD_POLL=setInterval(function(){ api("/api/reward").then(function(d){ var changed=JSON.stringify(d)!==JSON.stringify(REWARD); REWARD=d; if(changed&&VIEW==="rewards") renderAll(); }); }, 1500); }
  if(!on && REWARD_POLL){ clearInterval(REWARD_POLL); REWARD_POLL=null; }
}
function rewardSlots(r){
  return '<ol style="margin:0;padding-left:1.3em;display:grid;gap:6px">'+r.ranked.map(function(x,i){
    var slot=r.slots[x.slot]||{};
    var conf=slot.score!=null?Math.round(slot.score*100)+'% match':'';
    return '<li><b>'+esc(x.name)+'</b> <span class="muted">· '+esc(x.why)+'</span><div class="muted" style="font-size:12px">Read as "'+esc(slot.raw||'')+'" '+(conf?'('+conf+')':'')+(slot["for"]?' · part of '+esc(slot["for"]):'')+'</div></li>';
  }).join('')+'</ol>';
}
function renderRewards(){
  if(!caps().game_here){
    $("view").innerHTML='<div class="empty"><p><b>The reward helper reads the game on this computer.</b></p><p>Your account plays on '+esc(caps().platform_label)+', so there is no game window or game log here to read. Everything else in OpenWarframe works from your public profile.</p></div>';
    return [];
  }
  rewardPoll(true);
  if(!REWARD){ api("/api/reward").then(function(d){ REWARD=d; renderAll(); }); $("view").innerHTML='<div class="empty">Loading…</div>'; return []; }
  var d=REWARD, on=d.state==="watching"||d.state==="reading"||d.state==="starting";
  var h='<div class="focus">';
  h+='<div class="big"><div class="eyebrow" style="font:600 11px var(--mono);letter-spacing:.14em;color:var(--gold)">RELIC REWARD HELPER</div>';
  h+='<div class="what">'+(on?'Watching for fissure reward screens':'Not watching')+'</div><div class="why">'+esc(d.message||'When the reward screen opens, the helper reads the four names off your screen and picks the best one for your account.')+'</div>';
  h+='<div class="acts"><button class="btn primary" type="button" id="rw-toggle">'+(on?'Stop watching':'Start watching')+'</button><button class="btn" type="button" id="rw-pop">Open pop-out window</button><button class="btn" type="button" id="rw-demo">Try with a sample screen</button></div>';
  if(!d.ocr) h+='<div class="why"><b>Text recognition is not available here.</b> The helper needs Windows 10 or 11 with an English OCR language pack, or macOS 10.15 or newer.</div>';
  h+='</div>';
  if(d.last){
    var r=d.last, p=r.pick;
    h+='<div class="big" style="border-color:var(--ok)"><div class="eyebrow" style="font:600 11px var(--mono);letter-spacing:.14em;color:var(--ok)">'+(r.source==="sample"?'SAMPLE SCREEN':'LAST REWARD SCREEN')+' · '+new Date(r.time).toLocaleTimeString()+' · '+r.players+' player'+(r.players===1?'':'s')+'</div>';
    if(p) h+='<div class="what">Pick: '+esc(p.name)+'</div><div class="why">'+esc(p.why)+'</div>';
    h+=rewardSlots(r);
    if(r.sample_names) h+='<div class="why">Drawn names: '+esc(r.sample_names.join(", "))+'. If they match the list above, reading works on this PC.</div>';
    if(r.saved_to) h+='<div class="why">Screenshot saved for tuning: '+esc(r.saved_to)+'</div>';
    h+='</div>';
  }
  h+='<div class="row2"><div class="box"><h2>How it works</h2><ul style="margin:0;padding-left:1.1em;display:grid;gap:6px;font-size:13px">'+
     '<li>Start watching before you load into a fissure. The Next bar keeps working as usual.</li>'+
     '<li>Run Warframe in <b>borderless</b> or windowed mode. Exclusive fullscreen can make screenshots come back black.</li>'+
     '<li>The pick order: parts you need for something you have not mastered, then vaulted parts, then market price, then ducats.</li>'+
     '<li>The pop-out window stays on top of the game, so you can see the pick without alt-tabbing.</li>'+
     '<li>It only reads the game log and the screen, never game memory.</li>'+
     '<li><b>Still being tuned.</b> If it misreads names, turn on saving screens below and send a few of them along with a bug report.</li></ul>'+
     '<label class="tick opt" style="margin-top:10px"><input type="checkbox" id="rw-save"'+(d.save_recordings?' checked':'')+'><span class="t">Save each reward screen to help fix misreads<small>Keeps the newest 30 in your data folder (live/recordings). A saved screen shows your squadmates\' names, so look at it before you share it.</small></span><span></span></label></div>';
  h+='<div class="box"><h2>Recent screens <span class="muted">'+(d.history||[]).length+'</span></h2>'+((d.history||[]).length?(d.history||[]).map(function(r){return '<div class="goal"><b>'+esc(r.pick?r.pick.name:'(unreadable)')+'</b><span class="muted">'+new Date(r.time).toLocaleTimeString()+' · '+esc(r.source)+' · '+r.ranked.map(function(x){return esc(x.name)}).join(', ')+'</span></div>'}).join(''):'<p class="muted">Nothing yet.</p>')+'</div></div>';
  h+='</div>';
  $("view").innerHTML=h;
  $("rw-toggle").onclick=function(){ api("/api/reward/watch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({on:!on})}).then(function(x){ REWARD=x; PREFS.settings=PREFS.settings||{}; PREFS.settings.reward_watch=!on; renderAll(); toast(on?"Stopped watching.":"Watching. Load into a fissure and the pick appears here and in the pop-out."); }).catch(unreachable); };
  $("rw-save").onchange=function(){ var on=this.checked; api("/api/reward/recordings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({on:on})}).then(function(x){ REWARD=x; PREFS.settings=PREFS.settings||{}; PREFS.settings.save_recordings=on; renderAll(); toast(on?"Reward screens will be saved (newest 30 kept).":"Reward screens will not be saved."); }).catch(function(){ toast("Could not reach OpenWarframe. Is the app still running?"); }); };
  $("rw-pop").onclick=function(){ api("/api/reward/popout",{method:"POST"}).then(function(){ toast("Pop-out window opening. It stays on top of the game."); }).catch(unreachable); };
  $("rw-demo").onclick=function(){ toast("Drawing a sample reward screen and reading it…",20000); api("/api/reward/demo",{method:"POST"}).then(function(x){ if(x.error){ toast(x.error,8000); return; } api("/api/reward").then(function(dd){ REWARD=dd; renderAll(); toast("Sample read. Compare the names."); }); }).catch(unreachable); };
  return [];
}

