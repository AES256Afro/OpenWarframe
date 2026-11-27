function api(path, opts){ return fetch(path, opts).then(function(r){ return r.json(); }); }
// for things the player clicked: say so when the app can't be reached instead of doing nothing
function unreachable(){ toast("Could not reach OpenWarframe. Is the app still running?", 10000); }

// typing on a view without a list opens All items (and says so) instead of doing nothing
var NO_SEARCH={focus:1, overview:1, earn:1, rewards:1};
var searchTimer=null;
$("q").oninput=function(){
  var v=this.value;
  clearTimeout(searchTimer);
  searchTimer=setTimeout(function(){  // wait for a pause in typing: every render rebuilds the list
    Q=v.trim().toLowerCase();
    if(Q && NO_SEARCH[VIEW]){ goView("all"); setHash("all", true); toast("Searching All items."); }
    renderAll();
  }, 150);
};
$("refresh").onclick=function(){ toast("Fetching your profile…", 20000); api("/api/sync",{method:"POST"}).then(function(d){
  // a failed refresh keeps what is on screen: only the very first load has nothing to keep
  if(d.error&&!d.setup&&DATA&&!DATA.error){ toast(d.error, 10000); return; }
  load(d); toast(d.error?d.error:"Profile refreshed"); }).catch(unreachable); };
$("loadinv").onclick=function(){ $("invfile").click(); };
$("export").onclick=exportAccount;
$("updatedata").onclick=updateGameData;
function grab(accept){
  toast("Reading the game session and downloading your inventory…", 60000);
  api("/api/inventory/grab",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({accept:accept===true})})
    .then(function(d){
      if(d.needs_consent){ $("toast").hidden=true; $("risktext").textContent=d.risk; $("consent").showModal(); return; }
      if(d.error){ toast(d.error,10000); return; }
      load(d); toast("Inventory loaded from the game");
    }).catch(unreachable);
}
$("grab").onclick=function(){ grab(false); };
if(MAC) $("grab").hidden=true;  // until the server says what works here (see load)
$("consent-yes").onclick=function(){ $("consent").close(); grab(true); };
$("consent-no").onclick=function(){ $("consent").close(); };  // Escape closes it too (native dialog)
function sendInventory(file){
  file.text().then(function(txt){ toast("Reading inventory…",20000); return api("/api/inventory",{method:"POST",headers:{"Content-Type":"application/json"},body:txt}); })
    .then(function(d){ if(d.error){ toast(d.error,8000); return; } load(d); toast("Inventory loaded"); })
    .catch(unreachable);
}
$("invfile").onchange=function(){ if(this.files[0]) sendInventory(this.files[0]); this.value=""; };
// Drop an inventory file anywhere. The overlay shows only while a file is dragged over the
// window, and hides itself once dragover stops arriving (drag ended, cancelled or left),
// so selecting and dragging text never leaves it stuck.
var dz=$("dropzone"), dzTimer=null;
function hideDrop(){ dz.hidden=true; clearTimeout(dzTimer); }
function dragHasFile(e){ var t=e.dataTransfer&&e.dataTransfer.types; return !!t && Array.prototype.indexOf.call(t,"Files")>=0; }
window.addEventListener("dragover",function(e){
  if(!dragHasFile(e)) return;
  e.preventDefault(); dz.hidden=false;
  clearTimeout(dzTimer); dzTimer=setTimeout(hideDrop, 400);
});
window.addEventListener("dragleave",function(e){ if(!e.relatedTarget) hideDrop(); });
window.addEventListener("dragend",hideDrop);
window.addEventListener("keydown",function(e){ if(e.key==="Escape"&&!dz.hidden) hideDrop(); });
dz.addEventListener("click",hideDrop);
window.addEventListener("drop",function(e){
  hideDrop();
  if(!dragHasFile(e)) return;
  e.preventDefault();
  var f=e.dataTransfer.files[0]; if(f) sendInventory(f);
});
$("csv").onclick=function(){
  var spec=currentSpec(), rows=sorted(filtered());
  var cols=spec.cols.map(function(c){return c.k});
  var cell=function(v){ v=v==null?"":(typeof v==="object"?JSON.stringify(v):String(v)); return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v; };
  var csv=[spec.cols.map(function(c){return c.l}).join(",")].concat(rows.map(function(r){ return cols.map(function(k){return cell(r[k])}).join(","); })).join("\r\n");
  var a=document.createElement("a"); a.href=URL.createObjectURL(new Blob(["﻿"+csv],{type:"text/csv"})); a.download="openwarframe-"+VIEW.toLowerCase()+".csv"; a.click();
};
setInterval(function(){ fetch("/api/ping").catch(function(){}); }, 10000);
// the world state feeds Live, Focus and the Next bar on every screen: keep it current everywhere
setInterval(function(){ if(DATA) loadLive(true); }, 60000);
// Foundry timers and the session countdown move with the clock
setInterval(function(){ if(DATA&&(VIEW==="foundry"||VIEW==="focus")) renderAll(); sessionTimeCheck(); }, 60000);
var DATA_VERSION=null;
setInterval(function(){
  api("/api/version").then(function(v){
    if(DATA_VERSION===null){ DATA_VERSION=v.version; return; }
    if(v.version!==DATA_VERSION){ DATA_VERSION=v.version; api("/api/data").then(function(d){ load(d); toast("New profile or inventory data loaded."); }); }
  }).catch(function(){});
}, 30000);
try{ VIEW=localStorage.getItem("owf-view")||"focus"; }catch(e){}
// deep links: http://127.0.0.1:<port>/#relics opens that tab
// #farm/finish also opens a sub-tab (What to farm and Live)
function hashView(){ var parts=decodeURIComponent((location.hash||"").slice(1)).toLowerCase().split("/"), hit=null; VIEWS.forEach(function(v){ if(v.id.toLowerCase()===parts[0]) hit=v.id; }); if(hit&&parts[1]) F={sub:parts[1]}; return hit; }
// Back and Forward (pushState entries fire popstate; typed links fire hashchange): follow the address
function fromHash(){ var keepF=F; F={}; var hv=hashView(); if(!hv){ F=keepF; return; } var sub=F.sub;
  if(hv===VIEW && (sub||null)===(keepF.sub||null)){ F=keepF; return; }  // already showing it
  goView(hv); if(sub) F.sub=sub; try{ localStorage.setItem("owf-view",VIEW); }catch(e){} if(DATA) renderAll(); }
window.addEventListener("hashchange", fromHash);
window.addEventListener("popstate", fromHash);
// "/" searches, "?" lists the shortcuts; not while typing or while a dialog is open
function typing(el){ return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)); }
window.addEventListener("keydown", function(e){
  if(e.ctrlKey||e.metaKey||e.altKey||typing(e.target)||document.querySelector("dialog[open]")) return;
  if(e.key==="/"){ if($("q").hidden) return; e.preventDefault(); $("q").focus(); $("q").select(); }
  else if(e.key==="?"){ e.preventDefault(); $("keys").showModal(); }
});
$("keys-close").onclick=function(){ $("keys").close(); };  // Escape closes it too (native dialog)
// Narrow sidebar: the button pins it on or off; with no choice made it narrows by itself under 1000 px
var NARROW=window.matchMedia?window.matchMedia("(max-width:1000px)"):null;
function applyCompact(){ var pick=(PREFS.settings||{}).compact; var on=pick==null?!!(NARROW&&NARROW.matches):!!pick;
  document.body.classList.toggle("compact", on);
  var b=$("compact"); b.setAttribute("aria-pressed", String(on)); b.querySelector(".ab").innerHTML=on?"&raquo;":"&laquo;"; }
if(NARROW){ if(NARROW.addEventListener) NARROW.addEventListener("change", applyCompact); else if(NARROW.addListener) NARROW.addListener(applyCompact); }
$("compact").onclick=function(){ PREFS.settings=PREFS.settings||{}; PREFS.settings.compact=!document.body.classList.contains("compact"); savePrefs(); applyCompact(); };
applyCompact();
$("view").innerHTML='<div class="empty" id="boot">Loading your account…</div>';
var bootTimer=setInterval(function(){ if(DATA||!$("boot")){ clearInterval(bootTimer); return; } api("/api/status").then(function(s){ var b=$("boot"); if(b&&s.status) b.textContent=s.status; }).catch(function(){}); }, 1500);
var PREFS_LOADED=false;
api("/api/prefs").then(function(p){ PREFS_LOADED=true; PREFS=Object.assign({goals:[],checks:{},settings:{},skipped:{}}, p||{});
  if((PREFS.settings||{}).start!=="last") VIEW="focus";
  var sub=null, hv=hashView(); if(hv){ sub=F.sub; VIEW=hv; }
  goView(VIEW); if(sub) F.sub=sub;  // filters and sort as you left them
  setHash(VIEW+(F.sub?"/"+F.sub:""), false);  // so Back can return to the first view too
  Object.keys(PREFS.views||{}).forEach(function(v){ if(PREFS.views[v]&&PREFS.views[v].sort) SORT[v]=PREFS.views[v].sort; });
  VIEW_STATE_SAVED=JSON.stringify(PREFS.views||{});
  restoreSession(); applySettings(); applyCompact(); }).catch(function(){})
.then(function(){ return api("/api/data"); }).then(function(d){ load(d); checkUpdate(); }).catch(function(e){
  var net=e&&e.name==="TypeError"&&/fetch/i.test(e.message||"");
  $("view").innerHTML='<div class="empty">'+(net?"Could not reach the OpenWarframe server. Close this window and open OpenWarframe again.":"Something went wrong showing your data: "+esc(String((e&&e.message)||e)))+'</div>';
});
