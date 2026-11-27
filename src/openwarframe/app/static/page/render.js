// Re-rendering replaces the HTML, which drops keyboard focus to the page. Remember what had
// focus (by id or by its data- attribute) and put focus back on the same control afterwards.
function focusKey(el){
  if(!el||el===document.body||!document.contains(el)) return null;
  if(el.id) return "#"+CSS.escape(el.id);
  for(var i=0;i<el.attributes.length;i++){ var a=el.attributes[i];
    if(a.name.indexOf("data-")===0) return el.tagName.toLowerCase()+"["+a.name+'="'+CSS.escape(a.value)+'"]'; }
  return null;
}
function keepFocus(fn){
  var key=focusKey(document.activeElement), out=fn();
  if(key){ var el=document.querySelector(key); if(el&&el!==document.activeElement) el.focus({preventScroll:true}); }
  return out;
}
function renderAll(){ var out=keepFocus(renderAllNow); rememberView(); return out; }
// Filters and sort are kept per view, so coming back (or restarting) shows the list as you left it.
var VIEW_STATE_SAVED="";
function rememberView(){
  if(!DATA) return;
  PREFS.views=PREFS.views||{};
  var keep=Object.assign({},F); delete keep.id;  // "Show me" one item is for this visit only
  PREFS.views[VIEW]={F:keep, sort:SORT[VIEW]||null};
  var now=JSON.stringify(PREFS.views);
  if(now!==VIEW_STATE_SAVED){ VIEW_STATE_SAVED=now; clearTimeout(rememberView.t); rememberView.t=setTimeout(savePrefs, 800); }
}
function goView(v){ VIEW=v; OPEN={}; var st=(PREFS.views||{})[v]; F=st&&st.F?JSON.parse(JSON.stringify(st.F)):{}; if(st&&st.sort) SORT[v]=st.sort; }
function renderAllNow(){
  if(!DATA) return;
  if(VIEW!=="rewards") rewardPoll(false);
  var v=VIEWS.find(function(x){return x.id===VIEW})||VIEWS[0];
  $("title").textContent=v.label; renderTabs(); renderFilters(); renderNotice(); renderFreshness(); renderFocusBar();
  if(VIEW==="focus"){ $("filters").hidden=true; $("csv").hidden=true; renderFocus(); $("foot").innerHTML='<span>Goals, ticks and settings are saved in your OpenWarframe folder.</span>'; return; }
  if(VIEW==="overview"){ renderOverview(); $("csv").hidden=true; footer(null, false); return; }
  $("csv").hidden=false;
  var rows, table=false;
  if(VIEW==="farm"&&farmSub()==="finish"){ rows=renderFinish(); }
  else if(VIEW==="earn"){ rows=renderEarnings(); $("csv").hidden=true; }
  else if(VIEW==="rewards"){ rows=renderRewards(); $("csv").hidden=true; }
  else if(VIEW==="live"){ loadLive(false); rows=renderTable(); table=true; $("view").insertAdjacentHTML("afterbegin", liveHeader()); }
  else { rows=renderTable(); table=true; if(VIEW==="farm") $("view").insertAdjacentHTML("afterbegin", nowCard()); }
  footer(table||rows.length?rows:null, table&&rows.length>0);
}
// The row hint only where there is a table to click (not Earnings, Reward helper, Finish an item, Focus, Overview).
function footer(rows, isTable){
  $("foot").innerHTML=(rows?'<span>'+rows.length+' shown</span>':'')+'<span>Profile '+new Date(DATA.meta.snapshot).toLocaleString()+'</span><span>'+(DATA.meta.inventory?"Inventory loaded "+new Date(DATA.meta.inventory.loaded).toLocaleString():"No inventory loaded")+'</span>'
    +(isTable?'<span>Click a row for details. Click a column to sort.</span>':'')
    +'<span class="fan">Fan project, not affiliated with Digital Extremes. Warframe is a trademark of Digital Extremes Ltd.</span>';
}
function load(data){
  if(data.error&&data.setup){ renderSetup(data); return; }
  if(data.error){
    $("view").innerHTML='<div class="empty"><p>'+esc(data.error)+'</p><p>'+(data.can_update?'<button class="btn primary" type="button" id="err-update">Update game data</button> ':'')+'<button class="btn" type="button" id="err-retry">Try again</button></p></div>';
    $("who").textContent="";
    if(data.can_update) $("err-update").onclick=function(){ $("view").innerHTML='<div class="empty">Updating the game database. This can take a minute…</div>'; api("/api/codex/update",{method:"POST"}).then(load).catch(function(){ $("view").innerHTML='<div class="empty">The update failed. Check your internet connection and try again.</div>'; }); };
    $("err-retry").onclick=function(){ $("view").innerHTML='<div class="empty">Loading…</div>'; api("/api/data").then(load); };
    return;
  }
  DATA=data;
  setupMode(false);
  $("grab").hidden=!caps().grab;
  // the gold button is for the one thing to do next: loading the inventory, until it is loaded
  $("grab").classList.toggle("primary", !data.meta.inventory);
  $("who").innerHTML='<b>'+esc((data.meta.player||"Your account").replace(/[-]/g,""))+'</b><br>MR '+data.meta.mr+' · '+esc((data.meta.platform||"").toUpperCase());
  renderAll();
}
function checkPrices(){
  var spec=currentSpec();
  var rows=sorted(filtered()).filter(function(r){return r.slug && r.price==null && (spec.key==="relics"||r.spare>0)}).slice(0,80);
  var noun={relics:"relics", sell:"items", mods:"mods"}[spec.key]||"items";
  if(!rows.length){ toast("Prices are already shown for these "+noun+"."); return; }
  toast("Checking warframe.market for "+rows.length+" "+noun+". This takes up to a minute.", 60000);
  api("/api/prices",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:spec.key, ids:rows.map(function(r){return r.id})})})
    .then(function(p){
      (DATA[spec.key]||[]).forEach(function(r){ if(p[r.id]) r.price=p[r.id].typical; });
      SORT[VIEW]={k:"price",dir:-1}; renderAll();
      toast("Prices loaded for "+Object.keys(p).length+" "+noun+". Sorted by market value. Filter or sort, then check again for more.");
    }).catch(function(){ toast("Could not reach warframe.market."); });
}
// Before there is an account, the controls that need one are hidden; a normal load shows them again.
var SETUP_HIDE=["q","csv","refresh","grab","loadinv","export","updatedata","filters","fbar"];
function setupMode(on){
  SETUP_HIDE.forEach(function(id){ var el=$(id); if(el) el.hidden=on; });
  ["fresh","notice"].forEach(function(c){ var el=document.querySelector("."+c); if(el&&on) el.remove(); });
}
function renderSetup(d){
  setupMode(true);
  if(!d.switching) $("who").textContent="";
  $("title").textContent=d.switching?"Change account":"Get started"; $("csv").hidden=true;
  var h='<div class="setup"><h1>'+(d.switching?'Change account':'Welcome to OpenWarframe')+'</h1><p class="muted">'+esc(d.error)+'</p>';
  if(d.has_account){
    h+='<div class="box"><p>Your account is set. Fetch your public profile to fill the app.</p><div class="row"><button class="btn primary" type="button" id="setup-refresh">Fetch my profile</button></div></div>';
  } else {
    if(d.switching) h+='<div class="row"><button class="btn" type="button" id="setup-back">Keep the current account</button></div>';
    h+=(!caps(d).grab||d.switching?'':'<div class="box"><h2>From the running game (Windows only)</h2><p>Start Warframe, log in and wait until you are in your Orbiter. Then click the button. OpenWarframe finds your account and loads your full inventory (relics, blueprints, resources) in one go.</p><div class="row"><button class="btn primary" type="button" id="setup-grab">Find my account in the game</button></div></div>')
      +'<div class="box"><h2>'+(!caps(d).grab||d.switching?'Type your account ID':'Or type your account ID')+'</h2><ol><li>Log in at warframe.com in your browser.</li><li>Press F12 and open the Application tab (Storage in Firefox).</li><li>Under Cookies, pick www.warframe.com and copy the value of <b>gid</b>.</li></ol>'
      +'<p class="muted">It works like a user name, not a password: it only opens the same read-only profile anyone can view in the game.</p>'
      +'<div class="row"><label for="setup-id" class="muted">Account ID</label><input id="setup-id" autocomplete="off" spellcheck="false" maxlength="40" placeholder="24 characters, 0-9 and a-f"><select id="setup-plat" aria-label="Platform"><option value="pc">PC</option><option value="ps4">PlayStation</option><option value="xb1">Xbox</option><option value="swi">Nintendo Switch</option><option value="mob">iOS</option><option value="and">Android</option></select><button class="btn" type="button" id="setup-save">Save and fetch</button></div></div>';
  }
  $("view").innerHTML=h+'</div>';
  if(d.has_account){ $("setup-refresh").onclick=function(){ $("refresh").click(); }; return; }
  if($("setup-grab")) $("setup-grab").onclick=function(){ grab(false); };
  if($("setup-back")) $("setup-back").onclick=function(){ load(DATA); };
  $("setup-save").onclick=function(){
    var id=$("setup-id").value.trim();
    if(!id){ $("setup-id").focus(); return; }
    toast("Fetching your profile…", 20000);
    api("/api/account",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:id, platform:$("setup-plat").value})})
      .then(function(r){ if(r.error&&!r.setup){ toast(r.error,10000); return; } load(r); if(!r.error) toast("Profile loaded"); })
      .catch(function(){ toast("Could not reach OpenWarframe. Is the app still running?",10000); });
  };
}
