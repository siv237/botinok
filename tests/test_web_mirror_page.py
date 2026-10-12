#!/usr/bin/env python3
"""
Клиентские тесты страницы зеркала (JS из core/web_mirror._PAGE) на node мини-DOM:
ленивые страницы истории должны вставляться строго хронологически (старшие —
выше) и без повторов; живые события с одинаковым id не должны дублироваться;
после достижения cursor=0 новых запросов /history быть не должно.

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
function mkNode(tag){var n={tag:tag,children:[],parentNode:null,className:"",innerHTML:"",
  textContent:"",src:"",style:{},offsetHeight:100,onerror:null};
  n.classList=cl(n);
  n.appendChild=function(c){c.parentNode=n;n.children.push(c);return c;};
  n.insertBefore=function(c,ref){var i=ref?n.children.indexOf(ref):-1;
    if(i<0)n.children.push(c);else n.children.splice(i,0,c);c.parentNode=n;return c;};
  n.remove=function(){if(n.parentNode){var i=n.parentNode.children.indexOf(n);
    if(i>=0)n.parentNode.children.splice(i,1);n.parentNode=null;}};
  return n;}
var nodes={};
function byId(id){return nodes[id]||(nodes[id]=mkNode('div'));}
byId('out').appendChild(byId('logo'));byId('out').appendChild(byId('ver'));
byId('out').appendChild(byId('histAnchor'));
var document={getElementById:byId,createElement:function(t){return mkNode(t);},
  body:mkNode('body'),documentElement:{scrollHeight:1000}};
var listeners={};
function addEventListener(t,f){(listeners[t]=listeners[t]||[]).push(f);}
function fireScroll(){(listeners['scroll']||[]).forEach(function(f){f();});}
var innerHeight=800,scrollY=0;
function scrollTo(){}
function scrollBy(){}
var location={search:'?tok=TOK'};
var esInstances=[];
function EventSource(u){var es={url:u,onopen:null,onmessage:null,onerror:null};
  esInstances.push(es);return es;}
var GROUPS=[];for(var gi=1;gi<=700;gi++)GROUPS.push([{t:'user',text:'m'+gi}]);
var fetchCalls=0;
function fetch(u){fetchCalls++;
  var m=/before=(-?\d+)&limit=(\d+)/.exec(u);
  var before=m?+m[1]:-1,limit=m?+m[2]:30,total=GROUPS.length;
  var end=before<0?total:Math.max(0,Math.min(before,total)),start=Math.max(0,end-limit);
  var evs=[];for(var g=start;g<end;g++)evs=evs.concat(GROUPS[g]);
  return Promise.resolve({json:function(){return Promise.resolve({events:evs,cursor:start});}});}
"""

AFTER = r"""
setTimeout(function(){
  var seq=[];
  (function walk(n){for(var i=0;i<n.children.length;i++){var c=n.children[i];
    if(c.className.indexOf('user')>=0){var mm=/\bm(\d+)\b/.exec(c.innerHTML);if(mm)seq.push(+mm[1]);}
    walk(c);}})(byId('out'));
  var asc=true;for(var i=1;i<seq.length;i++)if(seq[i]<=seq[i-1])asc=false;
  console.log('CHECK|хронологический порядок страниц|'+(asc&&seq.length===700?'PASS':'FAIL')+
              '|len='+seq.length+' head='+JSON.stringify(seq.slice(0,4))+
              ' mid='+JSON.stringify(seq.slice(300,303)));
  var seen={},dup=false;seq.forEach(function(v){if(seen[v])dup=true;seen[v]=1;});
  console.log('CHECK|страницы истории без повторов|'+(dup?'FAIL':'PASS'));
  var callsBefore=fetchCalls;fireScroll();
  console.log('CHECK|после cursor=0 новых запросов нет|'+(fetchCalls===callsBefore?'PASS':'FAIL')+
              '|calls='+fetchCalls);
  var es=esInstances[0];
  if(!es){console.log('CHECK|SSE подключён|FAIL|нет EventSource');}
  else{
    console.log('CHECK|SSE подключён|PASS');
    es.onmessage({data:JSON.stringify({t:'user',text:'live1',id:1})});
    es.onmessage({data:JSON.stringify({t:'user',text:'live1',id:1})});
    var cnt=0;(function w2(n){for(var i=0;i<n.children.length;i++){var c=n.children[i];
      if(c.innerHTML&&/\blive1\b/.test(c.innerHTML))cnt++;w2(c);}})(byId('out'));
    console.log('CHECK|живое событие с тем же id не дублируется|'+(cnt===1?'PASS':'FAIL')+'|cnt='+cnt);
  }
},400);
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
        check("страница загрузилась в мини-DOM", False, out.strip()[:300])
    for ln in lines:
        _, name, verdict, extra = (ln.split("|") + ["", "", ""])[:4]
        check(name, verdict == "PASS", extra)
    print(f"\n{'ВСЕ ТЕСТЫ ПРОЙДЕНЫ' if not FAILURES else 'ПРОВАЛЫ: ' + ', '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
