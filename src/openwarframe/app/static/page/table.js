// ---- table --------------------------------------------------------------------
var tradeName=function(slug){ return 'Trade name on warframe.market: '+marketLink(slug); };
function detailHtml(spec, r){
  if(spec.key==="relics"||spec.key==="crack"){  // Relics to crack shows the same drop list
    var dr=r.drops||[];
    return (dr.length?'<div class="drops">'+dr.map(function(d){
      var cls=d.needed?"need":"";
      return '<div class="'+cls+'">'+esc(d.part)+' <span class="muted">· '+esc(d.rarity)+' '+esc(d.intact)+'% → '+esc(d.radiant)+'%</span>'+(d.vaulted?' <span class="pill p-violet">vaulted</span>':"")+(d.needed?' <span class="pill p-owned">you need this</span>':"")+'</div>';
    }).join("")+'</div>':'<span class="muted">No drops recorded.</span>')+(r.slug?'<p class="muted">'+tradeName(r.slug)+'</p>':'');
  }
  if(spec.key==="blueprints"){
    return '<div class="drops">'+r.parts.map(function(p){
      var rel=p.relics.length?'<br><span class="muted">'+p.relics.slice(0,6).map(function(x){return esc(x.relic)+(x.owned?" (you have "+x.owned+")":"")+(x.vaulted?" vaulted":"")}).join(", ")+'</span>':"";
      return '<div class="'+(p.short?"need":"done")+'">'+esc(p.name)+' <span class="muted">'+p.have+' / '+p.need+'</span>'+rel+'</div>';
    }).join("")+'</div>';
  }
  if(spec.key==="weekly") return '<span>'+esc(r.detail||'')+'</span>'+(r.note?'<p class="muted">'+esc(r.note)+'</p>':'');
  if(spec.key==="varzia") return '<span class="muted">Prime Resurgence at Varzia (Maroo\'s Bazaar, Mars). '+(r.why?esc(r.why)+'.':'')+'</span>';
  if(["fissures","storms","invasions","baro"].indexOf(spec.key)>=0) return '<span class="muted">'+esc(r.faction||'')+(r.level?' · level '+esc(r.level):'')+'</span>';
  if(spec.key==="missions") return '<div class="drops">'+r.gives.map(function(g){return '<div>'+esc(g)+'</div>'}).join('')+'</div>'+(r.popular_why?'<p class="muted">Popular farm: '+esc(r.popular_why)+'</p>':'');
  if(spec.key==="resources") return '<span class="muted">Needed by: '+esc((r.used_by||[]).join(", "))+'</span>';
  if(spec.key!=="items") return '<span class="muted">'+(r.slug?tradeName(r.slug):'Not tradeable')+'</span>';
  var goal=r.mastery==="Mastered"?'':'<p><button class="btn" type="button" data-goal="'+esc(r.id)+'">'+(isGoal(r.id)?'Goal ✓ (remove)':'Add to goals')+'</button></p>';
  var lead=r.mastery!=="Never leveled"?'<p class="muted">You leveled this before. Here is how to get it again.</p>':'';
  return lead+'<div class="howto" data-howto="'+esc(r.id)+'">'+(HOWTO[r.id]?howtoHtml(HOWTO[r.id]):'<span class="muted">Looking up how to get this…</span>')+'</div>'+goal;
}
// ---- how to get an item: asked when its details open, then kept for the session ----
var HOWTO={}, HOWTO_ASKED={};
function loadHowto(id){
  if(HOWTO[id]||HOWTO_ASKED[id]) return; HOWTO_ASKED[id]=true;
  api("/api/howto?id="+encodeURIComponent(id)).then(function(h){ HOWTO[id]=h; fillHowto(id); })
    .catch(function(){ delete HOWTO_ASKED[id]; fillHowto(id, {error:"Could not look that up. Is OpenWarframe still running?"}); });
}
function fillHowto(id, h){
  [].forEach.call(document.querySelectorAll(".howto"), function(el){ if(el.getAttribute("data-howto")===id) el.innerHTML=howtoHtml(h||HOWTO[id]); });
}
function howtoSource(x){
  if(x.kind==="relic"){
    return '<div class="'+(x.vaulted?"":"need")+'">'+esc(x.where)+' relic <span class="muted">· '+esc(x.rarity)+' · '+esc(x.intact)+'% intact → '+esc(x.radiant)+'% radiant</span>'
      +(x.vaulted?' <span class="pill p-violet">vaulted</span>':' <span class="pill p-owned">farmable</span>')
      +(x.owned?' <span class="pill p-owned">you have '+esc(x.owned)+'</span>':'')+'</div>';
  }
  var label={node:"Mission",bounty:"Bounty",transient:"Reward",enemy:"Enemy",vendor:"Vendor",syndicate:"Syndicate"}[x.kind]||"";
  return '<div>'+(label?'<span class="muted">'+label+':</span> ':'')+esc(x.where)+' <span class="muted">· '+esc(x.detail)+'</span></div>';
}
function howtoList(list, more){
  return '<div class="drops">'+list.map(howtoSource).join("")+(more?'<div class="muted">and '+esc(more)+' more</div>':'')+'</div>';
}
function howtoHtml(h){
  if(!h) return '';
  if(h.error) return '<span class="muted">'+esc(h.error)+'</span>';
  var out='';
  (h.notes||[]).forEach(function(n){ out+='<p>'+esc(n)+'</p>'; });
  if((h.sources||[]).length) out+='<h4 class="howto-h">Get it or its blueprint from</h4>'+howtoList(h.sources, h.more);
  var parts=(h.parts||[]).filter(function(p){return p.component});
  var res=(h.parts||[]).filter(function(p){return !p.component});
  if(parts.length){
    out+='<h4 class="howto-h">Parts</h4>';
    parts.forEach(function(p){
      out+='<p class="howto-part"><b>'+esc(p.name)+(p.count>1?' ×'+esc(p.count):'')+'</b></p>'
        +(p.sources.length?howtoList(p.sources, p.more):'<p class="muted">Not in any drop table: build or buy it first.</p>');
    });
  }
  if(res.length) out+='<p class="muted">Also needs: '+res.map(function(p){
    var top=p.sources[0]; return esc(p.name)+' ×'+esc(p.count)+(top?' (e.g. '+esc(top.where)+')':'');
  }).join(", ")+'</p>';
  if(!out) out='<span class="muted">No way to get this is recorded in the game data.</span>';
  if(h.slug) out+='<p class="muted">Or trade for it: '+marketLink(h.slug)+'</p>';
  return out;
}
function renderTable(){
  var spec=currentSpec(), rows=sorted(filtered()), s=SORT[VIEW]||{};
  if(!rows.length){ $("view").innerHTML='<div class="empty">'+emptyText(spec)+'</div>'; return rows; }
  var h='<table class="grid"><thead><tr>'+spec.cols.map(function(c){ var srt=s.k===c.k?(s.dir>0?"ascending":"descending"):"none";
    return '<th aria-sort="'+srt+'"'+(c.cls==="num"?' class="num"':'')+'><button type="button" data-k="'+c.k+'"'+(c.tip?' title="'+esc(c.tip)+'"':'')+'>'+esc(c.l)+'</button></th>'; }).join("")+'</tr></thead><tbody>';
  var max=Math.min(rows.length, ROW_CAP);
  for(var i=0;i<max;i++){
    var r=rows[i];
    h+='<tr data-i="'+esc(r.id)+'" tabindex="0" aria-expanded="'+(!!OPEN[r.id])+'">'+spec.cols.map(function(c){ var v=r[c.k]; return '<td class="'+(c.cls||"")+'">'+(c.fmt?c.fmt(v,r):esc(v==null?"":v))+'</td>'; }).join("")+'</tr>';
    if(OPEN[r.id]) h+='<tr class="detail"><td colspan="'+spec.cols.length+'">'+detailHtml(spec,r)+'</td></tr>';
    if(OPEN[r.id]&&spec.key==="items") setTimeout(loadHowto.bind(null, r.id), 0);
  }
  h+='</tbody></table>';
  // a long list is cut for speed: say so, so nothing looks missing
  if(rows.length>ROW_CAP) h+='<p class="capnote" role="status">Showing first '+ROW_CAP.toLocaleString()+' of '+rows.length.toLocaleString()+' — refine your search or filters to see the rest.</p>';
  $("view").innerHTML=h;
  return rows;
}
var ROW_CAP=1500;
// One click and one key handler for every table, set once: sort headers, open rows, row buttons.
function redrawTable(){ keepFocus(function(){ var rows=renderTable(); if(VIEW==="live") $("view").insertAdjacentHTML("afterbegin", liveHeader()); else if(VIEW==="farm") $("view").insertAdjacentHTML("afterbegin", nowCard()); return rows; }); }
function toggleRow(tr){ var id=tr.dataset.i; OPEN[id]=!OPEN[id]; redrawTable(); }
function onTableClick(e){
  var t=e.target; if(!t.closest||!t.closest("table.grid")) return;
  if(t.closest("a")) return;  // the warframe.market link opens by itself
  var g=t.closest("[data-goal]"); if(g){ toggleGoal(g.dataset.goal); return; }
  var th=t.closest("th button[data-k]");
  if(th){ var k=th.dataset.k, cur=SORT[VIEW]; SORT[VIEW]={k:k, dir:cur&&cur.k===k?-cur.dir:1}; redrawTable(); rememberView(); return; }
  var tr=t.closest("tbody tr[data-i]"); if(tr) toggleRow(tr);
}
function onTableKey(e){
  var tr=e.target; if(!tr.matches||!tr.matches("table.grid tbody tr[data-i]")) return;
  if(e.key==="Enter"||e.key===" "){ e.preventDefault(); toggleRow(tr); }
}
$("view").addEventListener("click", onTableClick);
$("view").addEventListener("keydown", onTableKey);
function emptyText(spec){
  if(["foundry","resources","sell","mods"].indexOf(spec.key)>=0&&!DATA.meta.inventory) return invHint("This view comes from your inventory.");
  if(spec.key==="blueprints"&&!DATA.meta.inventory) return "Owned blueprints come from your inventory. Load an inventory file to see what each blueprint still needs.";
  if(VIEW==="live"&&!LIVE) return "Loading the world state…";
  if(spec.key==="weekly") return "Nothing this week from the world state yet.";
  if(spec.key==="varzia") return "Varzia's Prime Resurgence stock isn't in the world state right now.";
  if(spec.key==="baro") return LIVE&&LIVE.baro&&!LIVE.baro.here?"Baro is not here yet. His stock appears when he arrives.":"No stock listed.";
  if(spec.key==="crack"&&!DATA.meta.inventory) return invHint("Relics to crack come from your inventory.");
  if(spec.key==="relics"&&!DATA.meta.inventory&&!spec.rows.length) return "No relics found.";
  // an empty list is only a filter problem when there was something to filter
  if(!spec.rows.length) return {foundry:"Nothing is building in your Foundry right now.", resources:"Your blueprints don't need any resources you're short of.", sell:"No spare Prime parts or blueprints to sell.", mods:"No mods or arcanes in your inventory."}[spec.key]||"Nothing here yet.";
  return "Nothing matches these filters.";
}

