// ---- shell ----------------------------------------------------------------------
function counts(){
  var c={overview:"", relics:DATA.relics.length, blueprints:DATA.meta.inventory?DATA.blueprints.length:"-", all:DATA.items.length};
  c.Warframes=DATA.items.filter(function(r){return r.group==="Warframes"}).length;
  c.Weapons=DATA.items.filter(function(r){return r.group==="Weapons"}).length;
  c.Companions=DATA.items.filter(function(r){return r.group==="Companions & more"}).length;
  c.farm=((DATA.farm||{}).finish||[]).filter(function(x){return x.missing<=1}).length+' close';
  c.live=LIVE&&LIVE.fissures?(LIVE.fissures.filter(function(f){return f.useful_relics}).length+' for you'):'';
  c.earn=DATA.meta.inventory?((DATA.sell||[]).filter(function(r){return r.spare}).reduce(function(a,r){return a+r.ducats_total},0).toLocaleString()+' d'):'-';
  c.focus=""; c.rewards=REWARD&&(REWARD.state==="watching"||REWARD.state==="reading")?"on":"";
  var inv=!!DATA.meta.inventory;
  c.foundry=inv?(DATA.foundry||[]).filter(function(f){return f.ready}).length+' ready':'-';
  c.resources=inv?(DATA.resources||[]).filter(function(r){return r.short}).length:'-';
  c.sell=inv?(DATA.sell||[]).filter(function(r){return r.spare}).length:'-';
  c.mods=inv?(DATA.mods||[]).length:'-';
  c.locked=DATA.items.filter(function(r){return r.access!=="Available"&&r.access!=="Leveled before"}).length;
  return c;
}
function renderTabs(){
  var c=counts();
  $("tabs").setAttribute("aria-orientation","vertical");
  $("tabs").innerHTML=VIEWS.map(function(v){ var on=VIEW===v.id, n=c[v.id];
    var name=v.label+(n!=null&&n!==''?', '+n:'');  // the full name stays when the sidebar is narrow
    return '<button class="tab" role="tab" type="button" data-v="'+v.id+'" aria-selected="'+on+'" aria-controls="view" tabindex="'+(on?0:-1)+'"'
      +' aria-label="'+esc(name)+'" title="'+esc(name)+'"><span class="lbl">'+esc(v.label)+'</span><span class="ab" aria-hidden="true">'+esc(v.ab||v.label.charAt(0))+'</span><span class="n" aria-hidden="true">'+(n==null?'':n)+'</span></button>'; }).join("");
  var tabs=[].slice.call($("tabs").querySelectorAll(".tab"));
  var open=function(b){ openView(b.dataset.v); };
  tabs.forEach(function(b,i){
    b.onclick=function(){ open(b); };
    // the view list works like tabs: arrows move and open, Home and End jump to the ends
    b.onkeydown=function(e){ var j={ArrowDown:i+1, ArrowUp:i-1, Home:0, End:tabs.length-1}[e.key]; if(j==null) return; e.preventDefault(); open(tabs[(j+tabs.length)%tabs.length]); };
  });
}
function setHash(h, push){ try{ if(location.hash==="#"+h) return; history[push?"pushState":"replaceState"](null,"","#"+h); }catch(e){} }
// Switch views as a new history step (Back returns to where you were); filter tweaks don't add steps.
function openView(v, extra, reset){
  goView(v); if(reset) F={}; if(extra) Object.keys(extra).forEach(function(k){ F[k]=extra[k]; });
  try{ localStorage.setItem("owf-view",VIEW); }catch(e){}
  setHash(VIEW+(F.sub?"/"+F.sub:""), true);
  renderAll(); var t=$("tabs").querySelector('[data-v="'+VIEW+'"]'); if(t) t.focus();
}
// How fresh the data is: an old profile, old game data, or an update that failed offline.
function renderFreshness(){
  var old=document.querySelector(".fresh"); if(old) old.remove();
  if(!DATA||!(VIEW==="focus"||VIEW==="overview")) return;
  var m=DATA.meta, days=function(iso){ return iso?Math.floor((Date.now()-Date.parse(iso))/86400000):null; };
  var msg=null, btn=null, act=null;
  var gd=days(m.game_data), pd=days(m.profile_checked||m.snapshot);  // an unchanged profile is still fresh
  if(m.codex_warning){ msg=m.codex_warning; btn="Try again"; act=updateGameData; }
  else if(m.unknown_blueprints>0){ msg=m.unknown_blueprints+" of your blueprints are newer than the game data, so they are left out."; btn="Update game data"; act=updateGameData; }
  else if(gd!=null&&gd>14){ msg="The game data is "+gd+" days old, so recent items and drop changes may be missing."; btn="Update game data"; act=updateGameData; }
  else if(pd!=null&&pd>7){ msg="Your profile is from "+pd+" days ago."; btn="Refresh profile"; act=function(){ $("refresh").click(); }; }
  if(!msg) return;
  var n=document.createElement("div"); n.className="fresh";
  n.innerHTML='<p>'+esc(msg)+'</p><button class="btn" type="button">'+esc(btn)+'</button>';
  n.querySelector("button").onclick=act;
  $("filters").after(n);
}
function updateGameData(){
  toast("Updating the game data. This takes about a minute…", 120000);
  api("/api/codex/update",{method:"POST"}).then(function(d){ load(d); toast(d.error?d.error:"Game data updated."); }).catch(unreachable);
}
function exportAccount(){
  toast("Writing your workbook, dashboard and guide…", 120000);
  api("/api/export",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}).then(function(d){
    if(d.error){ toast(d.error, 10000); return; }
    var warn=(d.files||[]).filter(function(f){return f.format==="warning"});
    toast("Saved to "+d.folder+(warn.length?" ("+warn.length+" warning"+(warn.length===1?"":"s")+")":""), 15000, {label:"Open folder", run:function(){
      api("/api/open-folder",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({folder:d.folder})}).catch(unreachable); }});
  }).catch(unreachable);
}
function checkUpdate(){
  api("/api/update").then(function(u){
    var a=$("newversion"), b=$("updatenow");
    if(u&&u.newer){
      a.href=u.url; a.hidden=false;
      a.textContent=u.can_install?"What's new in "+u.latest:"Version "+u.latest+" is out: see what's new";
      b.hidden=!u.can_install; b.disabled=false; b.textContent="Update to "+u.latest+" now";
      b.onclick=function(){ installUpdate(u); };
    } else { a.hidden=true; b.hidden=true; }
  }).catch(function(){});
}
// Download, check and install the new version; the app closes and the new one opens by itself.
function installUpdate(u){
  var b=$("updatenow"); b.disabled=true; b.textContent="Downloading "+u.latest+"…";
  api("/api/update/install",{method:"POST"}).then(function(r){
    if(r&&r.ok){
      $("view").innerHTML='<div class="empty" role="status"><p><b>Installing OpenWarframe '+esc(r.latest)+'.</b></p><p>'
        +(u.kind==="installer"?'The installer window shows its progress. ':'')+'OpenWarframe closes now and opens again by itself when the update is done.</p></div>';
      return;
    }
    b.disabled=false; b.textContent="Update to "+u.latest+" now";
    toast((r&&r.error)||"The update failed.", 9000);
  }).catch(function(){ b.disabled=false; b.textContent="Update to "+u.latest+" now"; unreachable(); });
}
function renderNotice(){
  var old=document.querySelector(".notice"); if(old) old.remove();
  // Foundry, Resources, Sell and Mods say this in their own empty state; don't say it twice
  if(DATA.meta.inventory||!(["relics","blueprints","overview"].indexOf(VIEW)>=0)) return;
  var n=document.createElement("div"); n.className="notice";
  var c=caps();
  n.innerHTML='<p><b>Your public profile shows what you have leveled, not what you own.</b> '+esc(invHint("").trim())+'</p>'
    +(c.grab?'<button class="btn primary" type="button">Get inventory from game</button>':c.game_here?'<button class="btn" type="button">Load inventory file</button>':'');
  var b=n.querySelector("button"); if(b) b.onclick=c.grab?function(){ grab(false); }:function(){ $("invfile").click(); };
  $("filters").after(n);
}
function nowCard(){
  var f=DATA.farm||{}, m=(f.missions||[])[0], c=(f.crack||[])[0];
  var one=(f.finish||[]).filter(function(x){return x.missing===1}).length;
  if(!m) return "";
  var pop=(f.missions||[]).filter(function(x){return x.popular})[0];
  var h='<div class="now"><div class="eyebrow">Do this now</div>';
  h+='<div class="what">Run '+esc(m.place)+' · '+esc(m.mission)+', rotation '+esc(m.best_rotation)+'</div>';
  h+='<div class="why">It drops the most of what you need: '+esc((m.gives[0]||"").split(" · ")[0])+(m.gives[1]?' and '+(m.needed_count-1)+' more':'')+'.</div>';
  h+='<div class="also">';
  if(c) h+='<span>Then crack <b>'+esc(c.name)+'</b>: you have '+c.count+', and it holds '+c.needed+' part'+(c.needed===1?'':'s')+' you need.</span>';
  if(pop&&pop!==m) h+='<span>Prefer a well-known farm? <b>'+esc(pop.place)+'</b> ('+esc(pop.mission)+').</span>';
  if(one) h+='<span><b>'+one+'</b> items are one piece away. Open Finish an item.</span>';
  h+='</div></div>';
  return h;
}
function renderFinish(){
  var rows=sorted(filtered());
  if(!rows.length){ $("view").innerHTML=nowCard()+'<div class="empty">Nothing matches.</div>'; return rows; }
  var h=nowCard()+'<div class="cards">';
  rows.slice(0,200).forEach(function(c){
    var left=c.missing===0?'<span class="pill p-owned">Ready to build</span>':'<span class="pill p-warn">'+c.missing+' of '+c.total+' missing</span>';
    h+='<div class="fcard"><h3>'+esc(c.name)+left+'</h3><button class="btn" type="button" data-goal="'+esc(c.id)+'">'+(isGoal(c.id)?'Remove goal':'Make this my goal')+'</button><span class="muted">'+esc(c.category)+' · '+esc(c.access)+'</span><ul>';
    c.pieces.forEach(function(p){
      var done=p.short===0;
      var have=p.have==null?'':' <span class="muted">('+p.have+'/'+p.need+')</span>';
      var route='';
      if(!done && p.crack){
        if(p.crack.length) route='<div class="route">Crack '+esc(p.crack[0].relic)+': you have '+p.crack[0].have+(p.crack.length>1?' (and '+(p.crack.length-1)+' other relic'+(p.crack.length>2?'s':'')+' you own)':'')+'</div>';
        else if(p.relic_only) route='<div class="route no">You have none of the relics that hold it.'+(p.farm_relic?' Farm '+esc(p.farm_relic.relic)+' on '+esc(p.farm_relic.where)+' first.':' Only vaulted relics hold it.')+'</div>';
      }
      h+='<li class="'+(done?'ok':'')+'">'+esc(p.name)+have+route+(done?'':'<div class="src">'+p.sources.map(esc).join('<br>')+'</div>')+'</li>';
    });
    h+='</ul>';
    var cost=c.cost||{credits:0,resources:[]};
    var shortRes=cost.resources.filter(function(x){return x.short});
    h+='<div class="src"><b>To build:</b> '+(cost.credits||0).toLocaleString()+' credits'+(cost.resources.length?' · '+cost.resources.slice(0,4).map(function(x){return x.need.toLocaleString()+'× '+esc(x.name)+(x.short?' <b>(short '+x.short.toLocaleString()+')</b>':'')}).join(', '):'')+'</div>';
    var buyable=c.pieces.filter(function(p){return p.short!==0 && p.slug});
    if(buyable.length){
      var priced=buyable.filter(function(p){return p.price!=null});
      if(priced.length===buyable.length){
        var tot=priced.reduce(function(a,p){return a+p.price*(p.short||1)},0);
        h+='<div class="src"><b>Buy instead:</b> about '+tot+' platinum on warframe.market ('+priced.map(function(p){return esc(p.name)+' '+esc(p.price)+'p'}).join(', ')+')</div>';
      } else {
        h+='<button class="btn" type="button" data-buy="'+esc(c.id)+'">Price the missing pieces</button>';
      }
    }
    h+='</div>';
  });
  $("view").innerHTML=h+'</div>';
  $("view").querySelectorAll("[data-goal]").forEach(function(b){ b.onclick=function(){ toggleGoal(b.dataset.goal); }; });
  $("view").querySelectorAll("[data-buy]").forEach(function(b){ b.onclick=function(){
    var card=(DATA.farm.finish||[]).find(function(x){return x.id===b.dataset.buy});
    var ids=card.pieces.filter(function(p){return p.short!==0 && p.slug}).map(function(p){return p.id});
    b.textContent="Checking…"; b.disabled=true;
    api("/api/prices",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:"pieces",ids:ids})}).then(function(p){
      (DATA.farm.finish||[]).forEach(function(c){ c.pieces.forEach(function(x){ if(p[x.id]) x.price=p[x.id].typical; }); });
      renderAll();
    }).catch(function(){ toast("Could not reach warframe.market."); b.disabled=false; });
  }; });
  return rows;
}
function renderEarnings(){
  var inv=DATA.meta.inventory;
  if(!inv){ $("view").innerHTML='<div class="empty">'+esc(invHint("Earnings come from your inventory."))+'</div>'; return []; }
  var sell=(DATA.sell||[]).filter(function(r){return r.spare});
  var relics=(DATA.relics||[]).filter(function(r){return r.count>0});
  var mods=(DATA.mods||[]).filter(function(r){return r.spare && (r.rarity==="Rare"||r.rarity==="Legendary") && r.slug});
  var sum=function(rows,q){ var priced=rows.filter(function(r){return r.price!=null}); return {plat:priced.reduce(function(a,r){return a+r.price*q(r)},0), priced:priced.length, total:rows.length}; };
  var s=sum(sell,function(r){return r.spare}), rl=sum(relics.filter(function(r){return r.slug}),function(r){return r.count}), md=sum(mods,function(r){return r.spare});
  var duc=sell.reduce(function(a,r){return a+r.ducats_total},0);
  var card=function(k,v,sub){ return '<div class="card"><div class="k">'+esc(k)+'</div><div class="v">'+v+'</div><div class="muted">'+sub+'</div></div>'; };
  // one price times every copy you hold: an upper bound, not what a sale brings in
  var pl=function(x,upTo){ return x.priced?((upTo?'up to ':'about ')+x.plat.toLocaleString()+' p'):'?'; };
  var cov=function(x){ return x.priced+' of '+x.total+' priced'; };
  var h='<div class="now"><div class="eyebrow">What you can make</div><div class="what">'+duc.toLocaleString()+' ducats from spare Prime parts'+(s.priced?', or about '+s.plat.toLocaleString()+' platinum on the market':'')+'</div>';
  h+='<div class="why">Prices come from warframe.market sell orders today and change often. Selling takes time; ducats are instant at Baro.</div>';
  h+='<div class="why">These are estimates: one price times how many you hold. Refined relics are priced as intact and ranked mods as unranked, and selling many at once usually brings less.</div>';
  h+='<div class="also"><button class="btn primary" type="button" id="estimate">Estimate platinum value</button><span class="muted">Checks up to 80 items per list. Takes a few minutes the first time.</span></div></div>';
  h+='<div class="overview">';
  h+=card("Spare Prime parts", duc.toLocaleString()+' ducats', pl(s)+' · '+cov(s));
  h+=card("Relics you own", relics.reduce(function(a,r){return a+r.count},0).toLocaleString()+' relics', pl(rl,true)+' · '+cov(rl)+' · priced as intact');
  h+=card("Spare rare mods", mods.reduce(function(a,r){return a+r.spare},0).toLocaleString()+' spare', pl(md,true)+' · '+cov(md)+' · priced unranked');
  h+=card("Wallet now", amt(inv.platinum).toLocaleString()+' p', amt(inv.ducats).toLocaleString()+' ducats · '+amt(inv.credits).toLocaleString()+' credits');
  h+='</div>';
  var top=[].concat(sell.map(function(r){return {name:r.name, what:'spare part ×'+r.spare, n:r.spare, p:r.price!=null?r.price*r.spare:null, d:r.ducats_total}}),
    relics.map(function(r){return {name:r.name, what:'relic ×'+r.count, n:r.count, p:r.price!=null?r.price*r.count:null, d:null}}),
    mods.map(function(r){return {name:r.name, what:'mod ×'+r.spare, n:r.spare, p:r.price!=null?r.price*r.spare:null, d:null}})).filter(function(x){return x.p!=null}).sort(function(a,b){return b.p-a.p}).slice(0,15);
  if(top.length){ h+='<div class="cards"><div class="fcard" style="grid-column:1/-1"><h3>Your 15 most valuable sells <span class="muted">estimates</span></h3><ul>'+top.map(function(x){return '<li><b>'+esc(x.name)+'</b> <span class="muted">'+esc(x.what)+'</span> · '+(x.n>1?'up to ':'about ')+x.p+' p'+(x.d?' or '+x.d+' ducats':'')+'</li>'}).join('')+'</ul></div></div>'; }
  $("view").innerHTML=h;
  $("estimate").onclick=function(){
    var lists=[["sell",sell.filter(function(r){return r.slug&&r.price==null}).sort(function(a,b){return b.ducats_total-a.ducats_total})],
               ["relics",relics.filter(function(r){return r.slug&&r.price==null}).sort(function(a,b){return (b.vaulted_parts-a.vaulted_parts)||(b.count-a.count)})],
               ["mods",mods.filter(function(r){return r.price==null})]];
    toast("Checking warframe.market. This can take a few minutes.", 300000);
    var chain=Promise.resolve();
    lists.forEach(function(l){ var rows=l[1].slice(0,80); if(!rows.length) return; chain=chain.then(function(){
      return api("/api/prices",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:l[0],ids:rows.map(function(r){return r.id})})}).then(function(p){
        (DATA[l[0]]||[]).forEach(function(r){ if(p[r.id]) r.price=p[r.id].typical; }); if(VIEW==="earn") renderEarnings();
      }); }); });
    chain.then(function(){ toast("Estimates updated."); }).catch(function(){ toast("Could not reach warframe.market."); });
  };
  return [];
}
