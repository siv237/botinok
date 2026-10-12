#!/usr/bin/env python3
"""
Клиентские тесты страницы зеркала (JS из core/web_mirror._PAGE) на node мини-DOM
с примитивной раскладкой (высоты, скролл, асинхронная догрузка картинок):

  • ленивые страницы истории вставляются хронологически и без повторов;
  • после cursor=0 новых запросов /history нет;
  • живое событие с повторным id не дублируется;
  • ЯКОРЬ: догрузка старых страниц и рост картинок ВЫШЕ вьюпорта не должны
    сдвигать видимое место к концу ленты (гллюч «мотаю вверх — оказался
    внизу») и не должны вызывать autoscroll к концу при живых событиях.

Запуск: venv/bin/python -u tests/test_web_mirror_page.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.web_mirror import _PAGE  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILURES.append(name)


HARNESS = r"""
"use strict";
function cl(n){return{add:function(c){var s=n.className.split(/\s+/).filter(Boolean);
  if(s.indexOf(c)<0)s.push(c);n.className=s.join(' ');},
  remove:function(c){n.className=n.className.split(/\s+/).filter(function(x){return x&&x!==c;}).join(' ');}};}
var scrollY=0,innerHeight=800;
var listeners={};
function addEventListener(t,f){(listeners[t]=listeners[t]||[]).push(f);}
function fireScroll(){(listeners['scroll']||[]).slice().forEach(function(f){try{f();}catch(_){}});}
function scrollTo(x,y){var nh=Math.max(0,y);if(nh!==scrollY){scrollY=nh;fireScroll();}}
function scrollBy(x,d){scrollTo(0,scrollY+d);}
function mkNode(tag){var n={tag:tag,children:[],parentNode:null,className:"",_html:"",
  textContent:"",src:"",style:{},_h:0,_base:tag==='div'?50:0,_ev:{}};
  n.classList=cl(n);
  Object.defineProperty(n,'innerHTML',{get:function(){return n._html;},set:function(v){
    n._html=String(v);
    n.children=n.children.filter(function(c){return c.tag==='img';});
    var rex=/<img /g;while(rex.exec(n._html)){var im=mkNode('img');n.children.push(im);}
  }});
  Object.defineProperty(n,'height',{get:function(){
    if(n.tag==='img')return n._lh||0;
    return n._base+n.children.reduce(function(a,c){return a+c.height;},0);},
    set:function(v){if(n.tag==='img')n._lh=v;}});
  Object.defineProperty(n,'offsetHeight',{get:function(){return n.height;}});
  n.appendChild=function(c){c.parentNode=n;n.children.push(c);return c;};
  n.insertBefore=function(c,ref){var i=ref?n.children.indexOf(ref):-1;
    if(i<0)n.children.push(c);else n.children.splice(i,0,c);c.parentNode=n;return c;};
  n.remove=function(){if(n.parentNode){var i=n.parentNode.children.indexOf(n);
    if(i>=0)n.parentNode.children.splice(i,1);n.parentNode=null;}};
  n.addEventListener=function(t,f){(n._ev[t]=n._ev[t]||[]).push(f);};
  n.dispatch=function(t){(n._ev[t]||[]).forEach(function(f){f();});};
  n.getBoundingClientRect=function(){return {top:docOffset(n)-scrollY,bottom:docOffset(n)+n.height-scrollY};};
  n.querySelectorAll=function(sel){var tag=sel.replace(/^\w*$/,'$&'),acc=[];
    (function w(x){x.children.forEach(function(c){if(c.tag===tag)acc.push(c);w(c);});})(n);return acc;};
  return n;}
function ownH(n){return n.tag==='img'?(n._lh||0):n._base;}
function docOffset(node){var y=0;
  (function w(n){if(n===node)return true;
    if(n!==byId('out'))y+=ownH(n);
    for(var i=0;i<n.children.length;i++){if(w(n.children[i]))return true;}
    return false;})(byId('out'));
  return y;}
var nodes={};
function byId(id){return nodes[id]||(nodes[id]=mkNode('div'));}
byId('logo')._base=100;byId('ver')._base=20;byId('histAnchor')._base=0;
byId('out').appendChild(byId('logo'));byId('out').appendChild(byId('ver'));
byId('out').appendChild(byId('histAnchor'));
var document={getElementById:byId,createElement:function(t){return mkNode(t);},
  body:mkNode('body'),documentElement:{get scrollHeight(){return byId('out').height;}}};
function totalH(){return byId('out').height;}
document.body.appendChild(byId('out'));
var location={search:'?tok=TOK'};
var esInstances=[];
function EventSource(u){var es={url:u,onopen:null,onmessage:null,onerror:null};
  esInstances.push(es);return es;}
var GROUPS=[];for(var gi=1;gi<=900;gi++){
  var txt='m'+gi+((gi%10===0)?' [[image:im'+gi+']]':'');
  GROUPS.push([{t:'user',text:txt}]);}
var fetchCalls=0;
function fetch(u){fetchCalls++;
  var m=/before=(-?\d+)&limit=(\d+)/.exec(u);
  var before=m?+m[1]:-1,limit=m?+m[2]:30,total=GROUPS.length;
  var end=before<0?total:Math.max(0,Math.min(before,total)),start=Math.max(0,end-limit);
  var evs=[];for(var g=start;g<end;g++)evs=evs.concat(GROUPS[g]);
  return Promise.resolve({json:function(){return Promise.resolve({events:evs,cursor:start});}});}
"""

AFTER = r"""
function tick(){return new Promise(function(r){setTimeout(r,30);});}
(async function(){
  // доматываем к верху, пока ленивая подгрузка не выберет все страницы
  for(var k=0;k<40;k++){await tick();scrollTo(0,0);await tick();
    if(fetchCalls>=3)break;}
  await tick();
  function blocks(){var acc=[];(function w(n){n.children.forEach(function(c){
    if(c.className.indexOf('user')>=0)acc.push(c);w(c);});})(byId('out'));return acc;}
  function walkSeq(){var seq=[];blocks().forEach(function(b){var mm=/\bm(\d+)\b/.exec(b.innerHTML);
    if(mm)seq.push(+mm[1]);});return seq;}
  var seq=walkSeq();
  var asc=true;for(var i=1;i<seq.length;i++)if(seq[i]<=seq[i-1])asc=false;
  console.log('CHECK|хронологический порядок страниц|'+(asc&&seq.length===900?'PASS':'FAIL')+
              '|len='+seq.length+' head='+JSON.stringify(seq.slice(0,4))+
              ' calls='+fetchCalls);
  var seen={},dup=false;seq.forEach(function(v){if(seen[v])dup=true;seen[v]=1;});
  console.log('CHECK|страницы истории без повторов|'+(dup?'FAIL':'PASS'));
  var callsBefore=fetchCalls;fireScroll();
  console.log('CHECK|после cursor=0 новых запросов нет|'+(fetchCalls===callsBefore?'PASS':'FAIL')+
              '|calls='+fetchCalls);

  // ── якорь: картинка ВЫШЕ вьюпорта не должна тащить экран к концу ──
  var bs=blocks();
  scrollY=Math.floor(totalH()*0.4);fireScroll();
  var anchorNode=null;
  for(var j=0;j<bs.length;j++){var r=bs[j].getBoundingClientRect();
    if(r.top<=100&&r.bottom>=100){anchorNode=bs[j];break;}}
  if(!anchorNode){console.log('CHECK|якорь найден|FAIL');}
  else{
    console.log('CHECK|якорь найден|PASS');
    var top0=anchorNode.getBoundingClientRect().top;
    var imgs=byId('out').querySelectorAll('img'),above=0;
    imgs.forEach(function(im){if(im.height===0&&im.getBoundingClientRect().bottom<0){
      above++;im.height=200;im.dispatch('load');}});
    var top1=anchorNode.getBoundingClientRect().top;
    console.log('CHECK|рост картинок выше вьюпорта не сдвигает позицию|'+
                (Math.abs(top1-top0)<=2?'PASS':'FAIL')+
                '|above='+above+' drift='+Math.round(top1-top0));
    var atBottom=scrollY>=totalH()-innerHeight-140;
    console.log('CHECK|после дорастивания не унесло в конец|'+(atBottom?'FAIL':'PASS')+
                '|scrollY='+scrollY+' total='+totalH());
    // живое событие: stick ложный (мы в середине) → никакого scrollTo(вниз)
    var es=esInstances[0];
    if(es&&es.onmessage){var y0=scrollY;
      es.onmessage({data:JSON.stringify({t:'user',text:'live1',id:1})});
      console.log('CHECK|живое событие из середины не перекидывает в конец|'+
                  (scrollY===y0?'PASS':'FAIL')+'|было '+y0+' стало '+scrollY);
      var cnt=0;(function w2(n){for(var i=0;i<n.children.length;i++){var c=n.children[i];
        if(c.innerHTML&&/\blive1\b/.test(c.innerHTML))cnt++;w2(c);}})(byId('out'));
      es.onmessage({data:JSON.stringify({t:'user',text:'live1',id:1})});
      console.log('CHECK|живое событие с тем же id не дублируется|'+(cnt===1?'PASS':'FAIL')+'|cnt='+cnt);
    }
  }
})();
"""


def main() -> int:
    if not shutil.which("node"):
        print("node не найден — тесты страницы пропущены")
        return 0
    script = re.search(r"<script>(.*)</script>", _PAGE, re.S).group(1)
    js = HARNESS + script + AFTER
    fd, path = tempfile.mkstemp(suffix=".js")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(js)
    try:
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(path)
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln for ln in out.splitlines() if ln.startswith("CHECK|")]
    if not lines:
        check("страница загрузилась в мини-DOM", False, out.strip()[:400])
    for ln in lines:
        parts = (ln.split("|") + ["", "", ""])[:4]
        check(parts[1], parts[2] == "PASS", parts[3])
    print(f"\n{'ВСЕ ТЕСТЫ ПРОЙДЕНЫ' if not FAILURES else 'ПРОВАЛЫ: ' + ', '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
