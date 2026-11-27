// ---- overview -----------------------------------------------------------------
function renderOverview(){
  var m=DATA.meta, it=DATA.items;
  var by=function(g){ var rows=it.filter(function(r){return r.group===g}); var done=rows.filter(function(r){return r.mastery==="Mastered"}).length; return {done:done, total:rows.length}; };
  // a card with a view opens it: a real button, so it works from the keyboard too
  var card=function(k,v,sub,pct,go){ var inner='<span class="k">'+esc(k)+'</span><span class="v">'+v+'</span>'+(sub?'<span class="muted">'+sub+'</span>':"")+(pct!=null?'<span class="bar"><i style="width:'+pct+'%"></i></span>':"");
    return go?'<button type="button" class="card" data-go="'+esc(go)+'">'+inner+'</button>':'<div class="card">'+inner+'</div>'; };
  var h='<div class="overview">';
  h+=card("Mastery rank", m.mr, "≈"+(m.estimate||0).toLocaleString()+" of "+(m.next||0).toLocaleString()+" for MR "+(m.mr+1), m.next?Math.min(100,Math.round(100*m.estimate/m.next)):null, "focus");
  [["Warframes","Warframes"],["Weapons","Weapons"],["Companions & more","Companions"]].forEach(function(g){ var x=by(g[0]); h+=card(g[0]+" mastered", x.done+" / "+x.total, null, x.total?Math.round(100*x.done/x.total):0, g[1]); });
  var lev=it.filter(function(r){return r.mastery==="Leveling"}).length;
  h+=card("Started, not finished", lev, "Owned at some point and below max rank", null, "all");
  var avail=it.filter(function(r){return r.access==="Available"}).length, locked=it.filter(function(r){return r.access!=="Available"&&r.access!=="Leveled before"}).length;
  h+=card("Never leveled, can get now", avail, "Plus "+locked+" you can't get yet", null, "all");
  h+=card("Relics with parts you need", DATA.relics.filter(function(r){return r.needed>0}).length, m.inventory?"From your inventory":"Load your inventory to see which you own", null, "relics");
  if(m.inventory){
    var ready=(DATA.foundry||[]).filter(function(f){return foundryReady(f)}).length;
    h+=card("Foundry", ready+" ready", (DATA.foundry||[]).length+" items building or done", null, "foundry");
    var duc=(DATA.sell||[]).filter(function(r){return r.spare}).reduce(function(a,r){return a+r.ducats_total},0);
    h+=card("Spare Prime parts", duc.toLocaleString()+" ducats", "You hold "+amt(m.inventory.ducats).toLocaleString()+" ducats now", null, "sell");
    h+=card("Wallet", amt(m.inventory.credits).toLocaleString()+" cr", amt(m.inventory.platinum).toLocaleString()+" platinum · "+amt(m.inventory.endo).toLocaleString()+" endo", null, "earn");
    h+=card("Blueprints ready to build", DATA.blueprints.filter(function(b){return b.ready}).length, DATA.blueprints.length+" blueprints owned", null, "blueprints");
  }
  h+='</div>';
  $("view").innerHTML=h;
  $("view").querySelectorAll("[data-go]").forEach(function(b){ b.onclick=function(){ openView(b.dataset.go); }; });
}

