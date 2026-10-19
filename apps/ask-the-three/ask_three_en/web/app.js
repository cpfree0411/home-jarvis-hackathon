(function(){'use strict';
/* Ask the Three — paper desk edition (English).
   One sheet of paper on a desk: taped notes, a ruled pad, three sealed slips that
   peel open together. All requests are relative, so the app also works behind a
   path-prefix proxy (e.g. /ask/). Demo-fixture seats are always labelled as such. */
const root=document.getElementById('app');
const API='api/';
const STRENGTH={CLOSE:'By a hair',LEAN:'Leaning',STRONG:'Clearly'};
const SLIP=['card','note','stub'];
const ERRORS={
  organizer_not_configured:'This server has no Nebius key, so only the sample stories can be summarised. Add NEBIUS_API_KEY to tell your own story.',
  nebius_key_unavailable:'The Nebius key is missing on the server.',
  story_too_long:'That story is too long to send. Please shorten it a little.',
  too_short:'That was a bit short. Please tell me a little more.',
  speech_failed:'I couldn’t process the audio. Please try again.',
  busy:'The judges are busy with another story. Please try again in a moment.',
  state:'This story has already moved on. Please start a new one.',
  service_restarted:'The server restarted while working on this story. Please start again.'};
let cfg={seats:[{member:'nemotron',name:'Nemotron',live:true},{member:'gpt',name:'GPT',live:true},{member:'claude',name:'Claude',live:true}],samples:[],stt:false,limits:{min_text:20,max_text:6000}};
let page='home',story=null,poller=null,ticker=null,ws=null,stream=null,context=null,processor=null,source=null,lease=false,transcript='',fromArchive=false,freshReveal=false;
const embedded=window.parent!==window;
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function seat(m){return cfg.seats.find(s=>s.member===m)||{member:m,name:String(m||''),live:true};}
function name(m){return seat(m).name;}
function members(){return cfg.seats.map(s=>s.member);}
function demoTag(live){return live?'':'<em class="demo-tag">demo</em>';}
function shell(content,back){
  const close=embedded||cfg.kiosk_lease?'<button class="tab exit" id="exit">Close</button>':'';
  root.innerHTML=`<div class="shell"><header class="top"><span class="brand tape t-cream">Ask the Three</span><div class="top-actions">${back?'<button class="tab" id="back">← Back</button>':''}${close}</div></header><main class="main ${page}">${content}</main></div>`;
  const ex=document.getElementById('exit');if(ex)ex.onclick=closeApp;if(back)document.getElementById('back').onclick=back;
  requestAnimationFrame(()=>root.querySelectorAll('[data-scroll]').forEach(more));}
// A sheet with more text below shows a soft paper fade at its foot until read to the end.
function more(el){const set=()=>el.classList.toggle('has-more',el.scrollHeight-el.scrollTop-el.clientHeight>4);set();el.addEventListener('scroll',set,{passive:true});}
async function req(path,options){
  let r;try{r=await fetch(API+path,{...options,headers:{'Content-Type':'application/json',...(options?.headers||{})}});}catch(_){throw Error('I can’t reach the server right now.');}
  if(!r.ok){let detail='';try{detail=(await r.json()).detail||'';}catch(_){}
    if(r.status===429)throw Error(String(detail).includes('daily')?'Today’s live-AI limit on this server has been reached. Sample stories with demo seats still work.':ERRORS.busy);
    throw Error('I couldn’t complete that request.');}
  return r.json();}
function clearPoll(){if(poller){clearInterval(poller);poller=null;}if(ticker){clearInterval(ticker);ticker=null;}}
function setPage(p){page=p;clearPoll();root.ontouchstart=null;root.ontouchend=null;}
function roster(){return `<ul class="roster">${cfg.seats.map((s,i)=>`<li class="tape t-seat${i}">${esc(s.name)}${demoTag(s.live)}</li>`).join('')}</ul>`;}
function pencil(){return `<svg class="pencil" viewBox="0 0 240 24" aria-hidden="true"><path d="M4 15 C 40 6, 70 20, 110 12 S 190 6, 236 14"/></svg>`;}
function liveNote(){const demo=cfg.seats.filter(s=>!s.live);if(!demo.length)return '';return `<p class="fine demo-note">${demo.map(s=>esc(s.name)).join(' and ')} ${demo.length>1?'are':'is'} running as a labelled demo fixture: prepared answers, not live AI.</p>`;}
function home(){setPage('home');story=null;fromArchive=false;shell(`
  <section class="home-copy">
    <p class="kicker">A friendly second opinion</p>
    <h1 class="hand">Can’t agree?<br>Ask the three.</h1>
    <p class="lead">One person tells the story. It’s summed up neutrally, then three AIs each pick a side on their own, and you see all three at once.</p>
    ${roster()}${liveNote()}
  </section>
  <section class="home-actions">
    <button class="tile primary sheet ruled" id="new"><span class="tape t-blue corner"></span><strong class="hand">New story</strong><span class="tile-sub">Tell it → tidy it → ask the three</span></button>
    <button class="tile secondary folder" id="past"><strong class="hand">Past stories</strong><span class="tile-sub">Look back at earlier verdicts</span></button>
  </section>`,null);
  document.getElementById('new').onclick=setup;document.getElementById('past').onclick=archive;}
function setup(){setPage('setup');shell(`
  <section class="pad sheet ruled enter"><span class="tape t-butter top-center"></span>
    <p class="kicker">New story</p>
    <h1 class="hand">What happened?</h1>
    <p class="lead">Say who did what, and which two views you’d like weighed up. Plain words are fine.</p>
    <ul class="checks"><li>What happened</li><li>The two views</li><li>Each side’s reasons</li></ul>
  </section>
  <div class="bottom"><button class="btn" id="sample">Try a sample</button><button class="btn${cfg.stt?'':' primary'}" id="type">Type it</button>${cfg.stt?'<button class="btn primary" id="go">Start talking</button>':''}</div>`,home);
  document.getElementById('sample').onclick=samplePicker;document.getElementById('type').onclick=()=>typing();if(cfg.stt)document.getElementById('go').onclick=start;}
function samplePicker(){setPage('samples');shell(`
  <div class="review-head"><p class="kicker">Sample stories · fiction written for this demo</p><h1 class="hand">Pick one to try</h1></div>
  <div class="sample-list">${cfg.samples.map((s,i)=>`<button class="sample-card sheet pose${i}" data-sample="${esc(s.id)}"><span class="tape t-seat${i%3} file-tape"></span><strong class="hand">${esc(s.teaser)}</strong><span class="snippet">${esc(s.text)}</span></button>`).join('')}</div>`,setup);
  root.querySelectorAll('[data-sample]').forEach(el=>el.onclick=()=>sampleRead(cfg.samples.find(s=>s.id===el.dataset.sample)));}
function sampleRead(s){setPage('typing');shell(`
  <div class="review-head"><p class="kicker">Sample story · ${esc(s.teaser)}</p><h1 class="hand">Read it, then ask</h1></div>
  <div class="transcript small sheet lined enter" data-scroll>${esc(s.text)}</div>
  <div class="bottom"><button class="btn" id="edit">Edit as my own</button><button class="btn primary" id="use">Use this story</button></div>`,samplePicker);
  document.getElementById('edit').onclick=()=>typing(s.text);document.getElementById('use').onclick=()=>submitText(s.text,'sample',s.id);}
function typing(prefill){setPage('typing');const max=cfg.limits.max_text,min=cfg.limits.min_text;shell(`
  <div class="review-head"><p class="kicker">New story</p><h1 class="hand">Write it down</h1></div>
  <label class="write sheet lined enter"><span class="sr">Your story</span><textarea id="story" maxlength="${max}" placeholder="For example: My partner and I disagree about…">${esc(prefill||'')}</textarea></label>
  <div class="bottom"><p class="fine grow" id="count"></p><button class="btn primary" id="done" disabled>Done: tidy it up</button></div>`,setup);
  const box=document.getElementById('story'),count=document.getElementById('count'),done=document.getElementById('done');
  const upd=()=>{const n=box.value.trim().length;count.textContent=n<min?`At least ${min} characters, please (${n} so far)`:`${n} / ${max} characters`;done.disabled=n<min;};
  box.addEventListener('input',upd);upd();box.focus();done.onclick=()=>submitText(box.value,'text',null);}
async function submitText(text,source,sampleId){try{const made=await req('stories',{method:'POST',body:JSON.stringify({source,sample_id:sampleId})});story={id:made.id};transcript=text;await req('stories/'+made.id+'/text',{method:'POST',body:JSON.stringify({text})});organizing();}catch(e){error(e.message,setup);}}
async function kiosk(action){if(!cfg.kiosk_lease)return true;try{const r=await fetch(cfg.kiosk_lease,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action}),keepalive:action==='release'});return r.ok;}catch(_){return false;}}
async function acquire(){if(lease||!cfg.kiosk_lease)return;if(!await kiosk('acquire'))throw Error('The voice assistant is busy. Please try again shortly.');lease=true;}
async function release(){if(!lease)return;lease=false;await kiosk('release');}
function stopMic(){try{processor?.disconnect();source?.disconnect();context?.close();stream?.getTracks().forEach(t=>t.stop());}catch(_){}processor=source=context=stream=null;}
async function closeApp(){clearPoll();stopMic();if(ws&&ws.readyState<2)ws.close();await release();if(embedded)window.parent.postMessage({type:'ask-three-close'},window.location.origin);else home();}
function notice(title,body,tape,extra){return `<section class="notice sheet enter"><span class="tape ${tape} top-left"></span><h1 class="hand">${title}</h1>${body}${extra||''}</section>`;}
function error(message,back=home){setPage('status-center');shell(notice('Let’s pause there',`<p class="lead error">${esc(message)}</p>`,'t-red',`<div class="actions"><button class="btn primary" id="retry">Go back</button></div>`),back);document.getElementById('retry').onclick=back;}
function wsUrl(){if(cfg.ws_base)return cfg.ws_base;const u=new URL('ws/transcribe/',document.baseURI);u.protocol=u.protocol==='https:'?'wss:':'ws:';return u.href;}
async function start(){try{await acquire();const made=await req('stories',{method:'POST',body:JSON.stringify({source:'voice'})});story={id:made.id};transcript='';listen();}catch(e){await release();error(e.message,setup);}}
async function mic(){stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});context=new AudioContext();source=context.createMediaStreamSource(stream);processor=context.createScriptProcessor(4096,1,1);const silent=context.createGain();silent.gain.value=0;source.connect(processor);processor.connect(silent);silent.connect(context.destination);processor.onaudioprocess=e=>{if(!ws||ws.readyState!==1||page!=='recording')return;const input=e.inputBuffer.getChannelData(0),ratio=context.sampleRate/16000,len=Math.floor(input.length/ratio),pcm=new Int16Array(len);for(let i=0;i<len;i++){const v=Math.max(-1,Math.min(1,input[Math.floor(i*ratio)]));pcm[i]=v<0?v*32768:v*32767;}if(ws.bufferedAmount<256000)ws.send(pcm.buffer);};}
function listen(){setPage('recording');shell(`
  <div class="rec-head"><span class="tape t-red rec-label"><i class="rec-dot"></i>Listening <b class="hand" id="clock">0:00</b></span>
    <h1 class="hand">Go ahead, tell me</h1><p class="lead">Take your time. I keep listening through pauses.</p></div>
  <div class="transcript sheet lined empty enter" id="transcript">Your words will appear here.</div>
  <div class="bottom"><button class="btn red" id="done">I’m done</button></div>`,abortRecording);
  const began=Date.now();ticker=setInterval(()=>{const el=document.getElementById('clock');if(!el)return;const s=Math.floor((Date.now()-began)/1000);el.textContent=Math.floor(s/60)+':'+String(s%60).padStart(2,'0');},1000);
  document.getElementById('done').onclick=finishSpeech;ws=new WebSocket(wsUrl()+story.id);ws.binaryType='arraybuffer';
  ws.onmessage=async e=>{const data=JSON.parse(e.data);if(data.type==='ready'){try{await mic();}catch(_){stopMic();ws.close();error('I couldn’t open the microphone.',setup);}}
    else if(data.type==='interim'||data.type==='final_segment'){transcript=data.text;const el=document.getElementById('transcript');if(el){el.textContent=transcript;el.classList.remove('empty');el.scrollTop=el.scrollHeight;}}
    else if(data.type==='complete'){transcript=data.text;stopMic();organizing();}
    else if(data.type==='error'){stopMic();error(ERRORS[data.code]||ERRORS.speech_failed,setup);}};
  ws.onerror=()=>{stopMic();error('The transcription connection dropped.',setup);};}
function abortRecording(){stopMic();if(ws&&ws.readyState<2)ws.close();ws=null;setup();}
function finishSpeech(){if(page!=='recording')return;setPage('status-center');stopMic();shell(notice('Wrapping up what you said',`${pencil()}<p class="lead">Just a moment.</p>`,'t-butter'),null);if(ws?.readyState===1)ws.send('stop');else error('The transcription connection dropped.',setup);}
function summaryBy(s){return s?.organizer==='prepared-sample'?'prepared sample summary, not AI':(cfg.organizer||'Nemotron');}
function organizing(){setPage('status-center');shell(notice('Tidying up the story',`${pencil()}<p class="lead">Writing down both views as they are, briefly.</p><p class="fine">Summary · ${esc(cfg.organizer||'prepared sample')}</p>`,'t-sage'),null);
  poller=setInterval(async()=>{try{const s=await req('stories/'+story.id);if(s.status==='REVIEW'){story=s;review();}else if(s.status==='FAILED'){error(ERRORS[s.error]||'I couldn’t tidy up the story. Please try again.',setup);}}catch(e){error(e.message||'I couldn’t check the status.');}},1000);}
function side(o,key){return o[key];}
function review(){setPage('review');const o=story.organized,a=side(o,'side_a'),b=side(o,'side_b');shell(`
  <div class="review-head"><p class="kicker">Here’s how I understood it</p><h1 class="title">${esc(o.title)}</h1></div>
  <div class="review-intro slip" data-scroll><p><b>Situation</b> ${esc(o.context)}</p>${o.subject?`<p><b>To decide</b> ${esc(o.subject)}</p>`:''}</div>
  <div class="sides">
    <section class="side a sheet enter"><span class="tape t-blue side-tape hand">A</span><div class="side-scroll" data-scroll><h2>${esc(a.label)}</h2><p>${esc(a.position)}</p></div></section>
    <section class="side b sheet enter"><span class="tape t-apricot side-tape hand">B</span><div class="side-scroll" data-scroll><h2>${esc(b.label)}</h2><p>${esc(b.position)}</p></div></section>
  </div>
  <div class="bottom"><p class="fine grow">Summary · ${esc(summaryBy(story))}. Your words, no judgement added.</p><button class="btn" id="again">Start over</button><button class="btn primary" id="approve">Ask the three</button></div>`,home);
  document.getElementById('again').onclick=setup;document.getElementById('approve').onclick=approve;}
async function approve(){try{await req('stories/'+story.id+'/approve',{method:'POST'});waiting();}catch(e){error(e.message,review);}}
function waiting(){setPage('waiting');shell(`
  <h1 class="hand">Asking the three</h1>
  <div class="sealed-row">${cfg.seats.map((s,i)=>`<div class="sealed slip-${SLIP[i]} enter"><span class="seal tape t-seat${i} hand">${esc(s.name)}</span></div>`).join('')}</div>
  <p class="lead">Each one is thinking on its own.<br>When all three have picked, I’ll open them together.</p>${pencil()}`,null);
  poller=setInterval(async()=>{try{const s=await req('stories/'+story.id);if(s.panel?.status==='REVEALED'){story=s;freshReveal=true;reveal();}}catch(_){error('I couldn’t fetch the verdicts.');}},1200);}
function card(m,r,i,o){const seal=freshReveal?`<span class="seal tape t-seat${i} hand peel d${i}">${esc(name(m))}</span>`:'';const head=`<span class="tape t-seat${i} name-tape hand">${esc(name(m))}</span>`;const demo=r.live?'':'<span class="demo-stamp">Demo fixture</span>';
  if(r.status==='FAILED')return `<button class="result-card slip-${SLIP[i]} failed" data-member="${esc(m)}">${head}<span class="choice">No answer</span><span class="strength">Tap for details</span>${seal}</button>`;
  const pick=r.choice==='A'?o.side_a.label:o.side_b.label;
  return `<button class="result-card slip-${SLIP[i]}${r.live?'':' demo'}" data-member="${esc(m)}">${head}${demo}<span class="choice ${r.choice.toLowerCase()}">${r.choice}</span><span class="pick ${r.choice.toLowerCase()}">${esc(pick)}</span><span class="strength stamp">${STRENGTH[r.strength]}</span>${seal}</button>`;}
function liveCount(p){const all=Object.values(p.members),live=all.filter(r=>r.live&&r.status==='COMPLETED').length,demo=all.filter(r=>!r.live).length;return demo?`<p class="fine demo-note center">${live} live AI vote${live===1?'':'s'} · ${demo} demo fixture${demo===1?'':'s'} (prepared, not live AI)</p>`:'';}
function reveal(){setPage('reveal');const p=story.panel,a=p.aggregate,o=story.organized;shell(`
  <div class="reveal-head"><p class="kicker one-line">${esc(o.title)}</p><h1 class="hand">The verdicts</h1></div>
  <div class="result-cards">${p.order.map((m,i)=>card(m,p.members[m],i,o)).join('')}</div>
  <div class="score tape t-cream"><span><b class="hand a">A</b> ${esc(o.side_a.label)}</span><strong class="hand">${a.votes_a} : ${a.votes_b}</strong><span><b class="hand b">B</b> ${esc(o.side_b.label)}</span></div>
  ${liveCount(p)}
  <div class="bottom">${fromArchive?'<button class="btn quiet" id="delete">Delete</button>':''}<button class="btn" id="raw">Original words</button><button class="btn primary" id="home">Home</button></div>`,home);
  freshReveal=false;document.querySelectorAll('[data-member]').forEach(el=>el.onclick=()=>detail(el.dataset.member));document.querySelectorAll('.peel').forEach(el=>el.addEventListener('animationend',()=>el.remove(),{once:true}));
  document.getElementById('raw').onclick=raw;document.getElementById('home').onclick=home;if(fromArchive)document.getElementById('delete').onclick=confirmDelete;}
function detail(m){setPage('detail');const order=story.panel.order,i=Math.max(0,order.indexOf(m)),r=story.panel.members[m],failed=r.status==='FAILED',ink=failed?'':r.choice.toLowerCase();
  const by=r.live?`<p class="fine model">${esc(r.provider)} · ${esc(r.model)}</p>`:'<p class="fine model demo-line">Demo fixture: prepared in advance, not a live AI answer.</p>';
  shell(`
  <div class="detail-head"><span class="tape t-seat${i} name-tape hand">${esc(name(m))}</span><h1 class="${ink}">${failed?'No answer':`Side ${r.choice} · ${STRENGTH[r.strength]}`}</h1>${r.live?'':'<span class="demo-stamp inline">Demo fixture</span>'}</div>
  <div class="detail-body sheet slip-${SLIP[i]} enter" data-scroll>${failed?`<p>No answer came back this time.</p><p class="fine model">${esc(r.error||'')}</p>`:`<h3 class="hand">Why I see it this way</h3><p>${esc(r.reasoning)}</p><h3 class="hand">What the other side gets right</h3><p>${esc(r.other_side_credit)}</p><h3 class="hand">What I’d suggest</h3><p>${esc(r.suggestion)}</p>`}${by}</div>
  <div class="bottom"><button class="btn" id="prev">← Previous</button><span class="dots">${order.map(x=>`<i class="${x===m?'on':''}"></i>`).join('')}</span><button class="btn" id="next">Next →</button></div>`,reveal);
  document.getElementById('prev').onclick=()=>detail(order[(i+2)%3]);document.getElementById('next').onclick=()=>detail(order[(i+1)%3]);let x=0;root.ontouchstart=e=>{x=e.touches[0].clientX};root.ontouchend=e=>{const delta=e.changedTouches[0].clientX-x;if(Math.abs(delta)>65)detail(order[(i+(delta<0?1:2))%3]);};}
async function raw(){try{const t=await req('stories/'+story.id+'/transcript');setPage('detail');shell(`
  <div class="detail-head"><p class="kicker">Original words</p><h1 class="title">${esc(story.organized.title)}</h1></div>
  <div class="transcript small sheet lined enter" data-scroll>${esc(t.text)}</div>
  <div class="bottom"><button class="btn primary" id="result">Back to verdicts</button></div>`,reveal);document.getElementById('result').onclick=reveal;}catch(e){error(e.message,reveal);}}
function filed(s,i){const g=s.aggregate,w=g.winner?g.winner.toLowerCase():'tie',when=new Date(s.created_at).toLocaleString('en-US',{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
  const names=(s.members||members()).map(m=>esc(name(m))+(s.live&&s.live[m]===false?' (demo)':'')).join(' · ');
  return `<button class="archive-card pose${i%6} ai${Math.min(i,6)}" data-id="${esc(s.id)}"><span class="tape t-${w==='a'?'blue':w==='b'?'apricot':'cream'} file-tape"></span><strong>${esc(s.title)}</strong><span class="tally hand"><b class="a">A</b> ${g.votes_a} : ${g.votes_b} <b class="b">B</b></span><span class="meta">${esc(when)}<br>${names}</span></button>`;}
async function archive(){setPage('archive');shell(`<h1 class="hand">Past stories</h1><div class="archive-list" id="archive" data-scroll></div>`,home);try{const d=await req('stories');const box=document.getElementById('archive');box.innerHTML=d.stories.length?d.stories.map(filed).join(''):'<p class="message sheet">No stories saved yet.</p>';box.querySelectorAll('[data-id]').forEach(el=>el.onclick=async()=>{try{story=await req('stories/'+el.dataset.id);savedResult();}catch(e){error(e.message,archive);}});more(box);}catch(e){error(e.message,home);}}
function savedResult(){fromArchive=true;reveal();}
function confirmDelete(){setPage('status-center');shell(`<div class="confirm">${notice('Delete this story?','<p class="lead">It will disappear from Past stories.</p>','t-red','<div class="actions"><button class="btn" id="cancel">Cancel</button><button class="btn red" id="delete">Delete</button></div>')}</div>`,savedResult);document.getElementById('cancel').onclick=savedResult;document.getElementById('delete').onclick=async()=>{try{await req('stories/'+story.id,{method:'DELETE'});archive();}catch(e){error(e.message,savedResult);}};}
async function boot(){try{const r=await fetch(API+'config');if(r.ok)cfg=await r.json();}catch(_){}home();}
boot();setInterval(()=>{if(lease)kiosk('heartbeat');},30000);window.addEventListener('pagehide',()=>{stopMic();if(lease&&cfg.kiosk_lease)navigator.sendBeacon(cfg.kiosk_lease,new Blob([JSON.stringify({action:'release'})],{type:'application/json'}));});
})();
