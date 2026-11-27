"use strict";
var REWARD=null, REWARD_POLL=null;
var PREFS={goals:[],checks:{},settings:{},skipped:{}}, SESSION=null, SESSION_TICKS={}, EASY=false;
// What this computer and account can do comes from the server (caps). Before the first data
// load, fall back to a guess from the browser.
var MAC=/Macintosh|Mac OS X/.test(navigator.userAgent);
function caps(d){ var src=d||DATA; return (src&&src.meta&&src.meta.caps)||(src&&src.caps)||{game_here:true, grab:!MAC, ocr:true, platform_label:"PC", os:MAC?"mac":"windows"}; }
// One sentence on how to get the inventory, for this computer and account.
function invHint(lead){
  var c=caps();
  if(c.grab) return lead+" With Warframe running and you in your Orbiter, click Get inventory from game.";
  if(!c.game_here) return lead+" Your account plays on "+c.platform_label+", so OpenWarframe works from your public profile; the inventory needs the PC game on this computer.";
  return lead+" Reading it from the running game only works on Windows. If you have an inventory file saved on a Windows PC (openwarframe inventory grab writes one), click Load inventory file.";
}
var DATA=null, LIVE=null, LIVE_AT=0, VIEW="overview", SORT={relics:{k:"count",dir:-1}}, Q="", F={}, OPEN={};
var $=function(id){return document.getElementById(id)};
var esc=function(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})};
// numbers from files and third-party sites: show them only if they really are numbers
var amt=function(v){var n=Number(v);return v==null||v===""||!isFinite(n)?0:n};
function toast(msg, ms, action){
  var t=$("toast"); t.textContent=msg; t.hidden=false; clearTimeout(t._h);
  if(action){  // e.g. {label:"Undo", run:fn}: a way back for one-click actions
    var b=document.createElement("button"); b.type="button"; b.className="btn"; b.textContent=action.label;
    b.onclick=function(){ t.hidden=true; action.run(); }; t.appendChild(b);
  }
  t._h=setTimeout(function(){t.hidden=true}, ms||(action?8000:4000));
}

// ab: the short label shown when the sidebar is narrow
var VIEWS=[
  {id:"focus", label:"Focus", ab:"Focus"},
  {id:"overview", label:"Overview", ab:"Home"},
  {id:"farm", label:"What to farm", ab:"Farm"},
  {id:"live", label:"Live", ab:"Live"},
  {id:"rewards", label:"Reward helper", ab:"Pick"},
  {id:"Warframes", label:"Warframes", group:"Warframes", ab:"Frame"},
  {id:"Weapons", label:"Weapons", group:"Weapons", ab:"Guns"},
  {id:"Companions", label:"Companions & more", group:"Companions & more", ab:"Pets"},
  {id:"relics", label:"Relics", ab:"Relic"},
  {id:"blueprints", label:"Blueprints", ab:"BPs"},
  {id:"foundry", label:"Foundry", ab:"Fndry"},
  {id:"resources", label:"Resources", ab:"Res"},
  {id:"earn", label:"Earnings", ab:"Earn"},
  {id:"sell", label:"Sell list", ab:"Sell"},
  {id:"mods", label:"Mods & arcanes", ab:"Mods"},
  {id:"locked", label:"Can't get yet", ab:"Lock"},
  {id:"all", label:"All items", ab:"All"}
];

function pill(state){
  var cls={"Mastered":"p-mastered","Owned, mastered":"p-mastered","Leveling":"p-leveling","Owned, not mastered":"p-leveling","Mastered, not owned":"p-violet","Never leveled":"p-never","Not owned":"p-never"}[state]||"p-never";
  return '<span class="pill '+cls+'">'+esc(state)+'</span>';
}
function accessPill(a){
  if(a==="Available") return '<span class="pill p-owned">Available</span>';
  if(a==="Leveled before") return '<span class="muted">—</span>';
  if(a&&a.indexOf("Needs MR")===0) return '<span class="pill p-bad">'+esc(a)+'</span>';
  return '<span class="pill p-warn">'+esc(a)+'</span>';
}

