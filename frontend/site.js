/* shared by landing, architecture and how-it-works: spotlight, reveal-on-scroll, card glow, guest session, api helper */
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
addEventListener("pointermove",e=>{const s=document.getElementById("spot");if(s){s.style.setProperty("--x",e.clientX+"px");s.style.setProperty("--y",e.clientY+"px")}
  const c=e.target.closest&&e.target.closest(".card");if(c){const r=c.getBoundingClientRect();c.style.setProperty("--mx",e.clientX-r.left+"px");c.style.setProperty("--my",e.clientY-r.top+"px")}},{passive:true});
const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("in");io.unobserve(e.target)}}),{threshold:.12,rootMargin:"0px 0px -6% 0px"});
function reveal(root=document){$$(".rv:not(.in)",root).forEach(el=>io.observe(el))}
document.addEventListener("DOMContentLoaded",()=>reveal());
let TOKEN=null;
async function guest(){if(TOKEN)return TOKEN;try{TOKEN=sessionStorage.getItem("sm_guest")}catch{}
  if(!TOKEN){const r=await fetch("/api/workspace/guest",{method:"POST"});if(!r.ok)throw new Error("The demo workspace could not be opened.");TOKEN=(await r.json()).token;try{sessionStorage.setItem("sm_guest",TOKEN)}catch{}}
  return TOKEN}
async function post(path,body){const t=await guest();const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json",Authorization:"Bearer "+t},body:JSON.stringify(body)});
  if(!r.ok){let m=r.statusText;try{const j=await r.json();m=j.detail||m}catch{}throw new Error(typeof m==="string"?m:JSON.stringify(m))}return r.json()}
function nav(active){return `<div class="nav"><div class="wrap"><a class="brand" href="/"><img src="/static/logo.svg" alt="" width="30" height="30">Cognify</a><nav>
  <a href="/architecture" class="${active==="a"?"on":""}">Architecture</a><a href="/how-it-works" class="${active==="h"?"on":""}">How it works</a><a href="/memory" class="${active==="m"?"on":""}">Memory ON/OFF</a><a href="/dispatch" class="${active==="d"?"on":""}">Dispatch</a><a href="/how-matching-works" class="${active==="x"?"on":""}">Matching</a><a href="/chat">Demo</a></nav><span class="sp"></span>
  <a class="btn sm" href="/chat">Ask Cognify →</a></div></div>`}
function foot(){return `<footer><div class="wrap"><span><b style="color:#fff">Cognify</b> · Ask Cognify. It remembers what your organization has learned.</span><span><a href="/learning" style="margin-right:16px">Watch it learn</a><a href="/phone" style="margin-right:16px">Technician phone</a><a href="/evaluation" style="margin-right:16px">Evaluation</a>All records in the demo are sample data, clearly labelled.</span></div></footer>`}
/* model output may still contain markdown; show it as readable plain text */
function plain(t){return String(t||"").replace(/<br\s*\/?>/gi,"\n").replace(/\*\*/g,"").replace(/^\s*[*-]\s+/gm,"• ").replace(/^#{1,4}\s*/gm,"").replace(/^\s*\|?[-:| ]{3,}\|?\s*$/gm,"").replace(/^\|\s*/gm,"").replace(/\s*\|\s*/g," · ").replace(/\n{3,}/g,"\n\n").trim()}
/* typewriter */
function type(el,text,{speed=14,done}={}){let i=0;el.textContent="";const t=()=>{i+=2;el.textContent=text.slice(0,i);if(i<text.length)setTimeout(t,speed);else done&&done()};t()}
