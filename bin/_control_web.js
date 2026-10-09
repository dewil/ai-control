'use strict';
const $ = id => document.getElementById(id);
let csrf = '';
let busy = false;
let taskLoaded = false;
const drafts = new Map();
const modelDrafts = new Map();
let modelExpiryTimer=null;
let sessionSettingsTimer=null;
let chatAuthGeneration=0;
const receipts = new Map();
const latestAttempts = new Map();
let acceptedStatusTimer=null;
const sendsInFlight = new Set();
const statusChecks = new Set();
const creates = new Map();
let createDialogProject=null;
let createDialogEpoch=0;
const renames = new Map();
let renameDialogScope=null;
let renameStatusTimer=null;
const historyData = new Map();
const historyFlights = new Map();
const messages = {invalid_code:'Код уже использован или неверен. Дождитесь нового кода.',unauthorized:'Сеанс завершён или код неверен. Войдите снова.',forbidden:'Запрос не подтверждён. Войдите снова.',rate_limited:'Слишком много попыток. Подождите минуту.',invalid_request:'Проверьте введённые данные.',invalid_or_stale:'Вопрос или результат изменился. Обновите задачи.',stale:'Эта карточка устарела. Обновите задачи.',saved_pending:'Ответ сохранён, доставка пока не завершена. Повторите позже.',unavailable:'Control временно недоступен. Попробуйте ещё раз.'};
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
// Deliberately a bounded subset, not CommonMark. Message data only becomes text
// nodes or these fixed elements; no HTML parser, media, or syntax highlighting.
function markdownHref(raw){
  if(!raw||/[\s\u0000-\u001f\u007f-\u009f\\<>"']/.test(raw)||/&(?:#\w+|[a-z]+);/i.test(raw))return null;
  let decoded;try{decoded=decodeURIComponent(raw);}catch(_){return null;}
  if(/[\u0000-\u001f\u007f-\u009f\\]/.test(decoded)||raw.startsWith('//')||decoded.startsWith('//'))return null;
  const absolute=/^https?:\/\//i.test(raw);
  if(!absolute&&(/^[^/?#]*:/.test(raw)||/^[^/?#]*:/.test(decoded)))return null;
  try{const url=new URL(raw,location.href);if(!['http:','https:'].includes(url.protocol)||url.username||url.password||(!absolute&&url.origin!==location.origin))return null;return url.href;}catch(_){return null;}
}
function markdownHasRawHtml(text){
  for(let i=0;i<text.length;i++){
    if(text[i]==='`'){
      if(text[i+1]==='`'){while(text[i+1]==='`')i++;continue;}
      const end=text.indexOf('`',i+1);if(end>i+1){i=end;continue;}
    }
    if(text[i]==='<'&&/^<\/?[a-zA-Z!?]/.test(text.slice(i,i+3)))return true;
  }
  return false;
}
function markdownInline(parent,text,depth=0,budget={left:text.length*24+1}){
  // Conservative subset fallback: an entire prose block with raw HTML stays
  // literal, including attributes, body markers, comments and quoted '>' chars.
  // Single-backtick code is skipped by detection, and ordinary '<3' is prose.
  if(markdownHasRawHtml(text)){parent.append(document.createTextNode(text));return;}
  if(depth>=8){parent.append(document.createTextNode(text));return;}
  let plain='',i=0;
  const flush=()=>{if(plain){parent.append(document.createTextNode(plain));plain='';}};
  const find=(token,start)=>{budget.left-=text.length-start;return budget.left<0?-1:text.indexOf(token,start);};
  while(i<text.length){
    if(budget.left<0){plain+=text.slice(i);break;}
    const ch=text[i];
    if(ch==='\\'&&i+1<text.length&&/[\\`*_{}\[\]()#+.!>|-]/.test(text[i+1])){plain+=text[i+1];i+=2;continue;}
    if(ch==='`'){
      // Only single backtick spans are in this subset.
      if(text[i+1]==='`'){let end=i+1;while(text[end]==='`')end++;plain+=text.slice(i,end);i=end;continue;}
      const end=find('`',i+1);if(end>i+1){flush();parent.append(node('code',text.slice(i+1,end)));i=end+1;continue;}
    }
    if(ch==='!'&&text[i+1]==='['){
      const labelEnd=find('](',i+2);const end=labelEnd<0?-1:find(')',labelEnd+2);
      if(end>=0){plain+=text.slice(i,end+1);i=end+1;continue;}
    }
    if(ch==='['&&text[i-1]!=='!'){
      const labelEnd=find('](',i+1);const end=labelEnd<0?-1:find(')',labelEnd+2);
      if(end>=0){const href=markdownHref(text.slice(labelEnd+2,end));if(href){flush();const a=node('a');a.href=href;a.target='_blank';a.rel='noopener noreferrer';markdownInline(a,text.slice(i+1,labelEnd),depth+1,budget);parent.append(a);}else plain+=text.slice(i,end+1);i=end+1;continue;}
    }
    if(ch==='*'||ch==='_'){
      const strong=text[i+1]===ch;const marker=strong?ch+ch:ch;
      // Intraword underscores and longer marker runs are unsupported literals.
      if((ch==='_'&&i>0&&/[\p{L}\p{N}]/u.test(text[i-1]))||text[i+marker.length]===ch){plain+=marker;i+=marker.length;continue;}
      const end=find(marker,i+marker.length);
      if(end>i+marker.length&&!/\s/.test(text[i+marker.length])&&!/\s/.test(text[end-1])){flush();const el=node(strong?'strong':'em');markdownInline(el,text.slice(i+marker.length,end),depth+1,budget);parent.append(el);i=end+marker.length;continue;}
    }
    plain+=ch;i++;
  }
  flush();
}
function markdownCells(line){
  const trimmed=line.trim();if(!trimmed.includes('|'))return null;
  let cells=trimmed.split('|');if(trimmed.startsWith('|'))cells.shift();if(trimmed.endsWith('|'))cells.pop();
  return cells.length>=2?cells.map(cell=>cell.trim()):null;
}
function markdownBlockStart(lines,i){
  return /^(?: {0,3}#{1,6}\s| {0,3}(?:`{3,}|~{3,})| {0,3}>\s?| {0,3}(?:[-+*]|\d{1,9}[.)])\s+)/.test(lines[i])||Boolean(i+1<lines.length&&markdownTableHeader(lines[i],lines[i+1]));
}
function markdownTableHeader(line,separator){
  const head=markdownCells(line),rule=markdownCells(separator);
  return head&&rule&&head.length===rule.length&&rule.every(cell=>/^:?-{3,}:?$/.test(cell))?head:null;
}
function renderMarkdown(text){
  const box=node('div',undefined,'content markdown');
  // The backend caps messages at 8000 characters. Unexpected larger input stays
  // readable without invoking the parser; the scan budget also bounds bad spans.
  if(text.length>8000){box.textContent=text;return box;}
  const lines=text.replace(/\r\n?/g,'\n').split('\n');const budget={left:text.length*24+1};
  const inline=(el,value)=>{markdownInline(el,value,0,budget);return el;};
  for(let i=0;i<lines.length;){
    const line=lines[i];if(!line.trim()){i++;continue;}
    const fence=/^ {0,3}(`{3,}|~{3,})([^`]*)$/.exec(line);
    if(fence){
      const marker=fence[1];let end=i+1;
      while(end<lines.length){const candidate=lines[end].trim();if(candidate.length>=marker.length&&[...candidate].every(ch=>ch===marker[0]))break;end++;}
      // Keep an unfinished fence literal so polling can later complete it.
      if(end===lines.length){box.append(node('p',lines.slice(i).join('\n')));break;}
      const language=fence[2].trim();if(language)box.append(node('span',language,'code-language'));
      const pre=node('pre');pre.append(node('code',lines.slice(i+1,end).join('\n')+(end>i+1?'\n':'')));box.append(pre);i=end+1;continue;
    }
    if(markdownHasRawHtml(line)){
      const literal=[line];i++;while(i<lines.length&&lines[i].trim())literal.push(lines[i++]);
      box.append(node('p',literal.join('\n')));continue;
    }
    const heading=/^ {0,3}(#{1,6})[ \t]+(.+)$/.exec(line);
    if(heading){box.append(inline(node('h'+heading[1].length),heading[2]));i++;continue;}
    const head=i+1<lines.length?markdownTableHeader(line,lines[i+1]):null;
    if(head){
      const table=node('table'),thead=node('thead'),tr=node('tr');for(const cell of head)tr.append(inline(node('th'),cell));thead.append(tr);table.append(thead);const tbody=node('tbody');i+=2;
      while(i<lines.length){const cells=markdownCells(lines[i]);if(!cells||cells.length!==head.length)break;const row=node('tr');for(const cell of cells)row.append(inline(node('td'),cell));tbody.append(row);i++;}
      table.append(tbody);const wrap=node('div',undefined,'markdown-table');wrap.append(table);box.append(wrap);continue;
    }
    const list=/^ {0,3}([-+*]|\d{1,9}[.)])\s+(.+)$/.exec(line);
    if(list){
      const ordered=/^\d/.test(list[1]),el=node(ordered?'ol':'ul');if(ordered)el.start=parseInt(list[1],10);
      while(i<lines.length){const item=/^ {0,3}([-+*]|\d{1,9}[.)])\s+(.+)$/.exec(lines[i]);if(!item||/^\d/.test(item[1])!==ordered)break;el.append(inline(node('li'),item[2]));i++;}box.append(el);continue;
    }
    if(/^ {0,3}>/.test(line)){
      const quote=[];while(i<lines.length&&/^ {0,3}>/.test(lines[i])){quote.push(lines[i].replace(/^ {0,3}> ?/,''));i++;}const el=node('blockquote');el.append(inline(node('p'),quote.join('\n')));box.append(el);continue;
    }
    const paragraph=[line];i++;while(i<lines.length&&lines[i].trim()&&!markdownBlockStart(lines,i)){paragraph.push(lines[i]);i++;}box.append(inline(node('p'),paragraph.join('\n')));
  }
  return box;
}
function notice(text){$('notice').textContent=text;}
let androidResumeGeneration=0;
function androidAuth(){return window.AndroidAuth&&typeof window.AndroidAuth.requestAuth==='function'?window.AndroidAuth:null;}
function authExpired(){const native=androidAuth();if(native){androidResumeGeneration++;stopPolling();native.requestAuth();}else signedOut();}
async function api(path,body,signal,isCurrent=()=>true){let response;try{response=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',signal,headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});}catch(_){throw new Error(messages.unavailable);}let data;try{data=await response.json();}catch(_){throw new Error(messages.unavailable);}if(signal&&signal.aborted)throw new Error(messages.unavailable);if(!response.ok){if(response.status===401&&path!=='/api/login'&&isCurrent())authExpired();const error=new Error(messages[data.error]||messages.unavailable);error.code=data.error;error.status=response.status;error.data=data;throw error;}return data;}
function signedOut(){projectsSelectionProof=null;setProjectsExpanded(true);closeCreateDialog();creates.clear();closeRenameDialog();renames.clear();chatAuthGeneration++;sendsInFlight.clear();modelDrafts.clear();if(acceptedStatusTimer!==null){clearTimeout(acceptedStatusTimer);acceptedStatusTimer=null;}csrf='';taskLoaded=false;stopPolling();selectionGeneration++;initialScrollTarget=null;clearHistoryScrollSlack();selectedSession=null;selectedProject='';projectNames=[];availableProjects=new Set();projectEntries=[];projectSummaries.clear();projectsGeneration++;$('project-cloud').replaceChildren();$('project-summary-status').textContent='';sessionRows=[];drafts.clear();receipts.clear();latestAttempts.clear();historyData.clear();$('session-loading').hidden=true;$('workspace').hidden=true;$('login').hidden=false;$('logout').hidden=true;$('session-list').replaceChildren();$('cards').replaceChildren();updateUrl();syncCurrentSessionControls();}
function field(parent,key,label,kind='textarea'){const wrap=node('label',label);const input=node(kind);input.maxLength=16000;input.value=drafts.get(key)||'';input.addEventListener('input',()=>drafts.set(key,input.value));wrap.append(input);parent.append(wrap);return input;}
function button(parent,label,action,cls){const b=node('button',label,cls);b.type='button';b.addEventListener('click',action);parent.append(b);return b;}
async function mutate(card,path,body){if(busy)return;busy=true;const controls=[...document.querySelectorAll('#tasks-panel button')];controls.forEach(b=>b.disabled=true);const status=card.querySelector('.message');status.textContent='Сохраняем…';try{const data=await api(path,body);status.textContent=data.status==='already'?'Решение уже было принято.':'Решение принято.';await refresh();}catch(err){status.textContent=err.message;if(err.code==='saved_pending'){await refresh();notice(err.message);}}finally{busy=false;controls.forEach(b=>b.disabled=false);}}
function question(card,task,q){
  const box=node('div',undefined,'question');box.append(node('h3',q.kind==='permission'?'Нужно разрешение':'Нужен ваш ответ'));box.append(node('p',q.question,'content'));card.append(box);
  if(q.answered){box.append(node('h3','Ваш сохранённый ответ'));box.append(node('p',q.kind==='info'?(q.saved_answer||''):q.saved_decision==='approve'?'Вы разрешили операцию':'Вы отклонили операцию','content'));box.append(node('span',q.pending_delivery?'Ответ сохранён и ожидает доставки':'Ответ доставлен','badge'));if(q.status==='open'&&q.pending_delivery){box.append(node('p','Первый ответ уже сохранён. Повторная попытка доставит именно его.','meta'));const actions=node('div',undefined,'actions');button(actions,'Повторить доставку',()=>mutate(card,'/api/answer',{agent:task.agent,qid:q.qid,decision:'recover',text:''}));box.append(actions);}if(q.status!=='open')box.append(node('p','Вопрос закрыт','meta'));return;}
  if(q.status!=='open'){box.append(node('span','Вопрос закрыт','badge'));return;}const actions=node('div',undefined,'actions');if(q.kind==='info'){const input=field(box,task.agent+':'+q.qid,'Ваш ответ');button(actions,'Отправить ответ',()=>{if(!input.value.trim()){card.querySelector('.message').textContent='Напишите ответ.';return;}mutate(card,'/api/answer',{agent:task.agent,qid:q.qid,decision:'text',text:input.value});});}else{for(const decision of q.allowed_decisions||[]){if(!['approve','reject'].includes(decision))continue;button(actions,decision==='approve'?'Разрешить':'Отклонить',()=>mutate(card,'/api/answer',{agent:task.agent,qid:q.qid,decision,text:''}),decision==='reject'?'secondary':'');}}box.append(actions);
}
function result(card,task,r){if(!r)return;const box=node('div',undefined,'question');card.append(box);box.append(node('h3','Результат работы'));box.append(node('p',r.summary,'content'));const labels={requested:r.finalized?'Ждёт вашей проверки':'Готовится к проверке',accepted:'Вы приняли результат',rejected:'Вы отклонили результат',archived:'Работа завершена'};box.append(node('span',labels[r.state]||'Решение сохранено','badge'));if(r.state!=='requested'||!r.finalized)return;box.append(node('p','Принятие подтверждает результат. Применение изменений может завершиться позже.','meta'));const comment=field(box,task.agent+':'+r.generation,'Комментарий (необязательно)');const confirmLabel=node('label',undefined,'confirm');const check=node('input');check.type='checkbox';confirmLabel.append(check,node('span','Я проверил результат и подтверждаю решение'));box.append(confirmLabel);const rejectDetails=node('div');rejectDetails.hidden=true;const totp=field(rejectDetails,task.agent+':totp','Свежий код подтверждения','input');totp.maxLength=6;totp.inputMode='numeric';totp.autocomplete='one-time-code';totp.value='';totp.addEventListener('input',()=>drafts.delete(task.agent+':totp'));box.append(rejectDetails);const actions=node('div',undefined,'actions');const send=decision=>{if(!check.checked){card.querySelector('.message').textContent='Подтвердите, что проверили результат.';check.focus();return;}if(decision==='reject'&&(!rejectDetails.hidden&&!/^[0-9]{6}$/.test(totp.value)||rejectDetails.hidden)){rejectDetails.hidden=false;card.querySelector('.message').textContent='Для отклонения нужен новый код, отличный от кода входа.';totp.focus();return;}const body={agent:task.agent,generation:r.generation,decision,comment:comment.value,confirmed:true};if(decision==='reject')body.totp=totp.value;mutate(card,'/api/verdict',body);};button(actions,'Принять результат',()=>send('accept'));button(actions,'Отклонить',()=>send('reject'),'danger');box.append(actions);}
function priority(task){if((task.questions||[]).some(q=>q.status==='open'&&!q.answered))return 0;if(task.result&&task.result.state==='requested'&&task.result.finalized)return 1;return 2;}
async function refresh(){if(!csrf)return;const b=$('refresh');b.disabled=true;notice('Загружаем задачи…');try{const data=await api('/api/tasks');const tasks=data.tasks.slice().sort((a,b)=>priority(a)-priority(b));const fragment=document.createDocumentFragment();for(const task of tasks){const card=node('article',undefined,'card');card.append(node('h2',task.name||task.agent));card.append(node('p',task.engine==='codex'?'Codex':'Claude','meta'));card.append(node('p','','message'));if(task.unavailable){card.append(node('p','Данные задачи временно недоступны. Обновите позже.'));}else{if(task.summary)card.append(node('p',task.summary,'content'));for(const q of task.questions||[])question(card,task,q);result(card,task,task.result);}fragment.append(card);}$('cards').replaceChildren(fragment);$('count').textContent=tasks.length?'Задач: '+tasks.length:'Пока нет задач';taskLoaded=true;notice(tasks.some(t=>t.unavailable)?'Некоторые задачи недоступны. Попробуйте обновить позже.':tasks.length?'':'Здесь появятся вопросы и результаты ваших задач.');}catch(err){notice(err.message+' Нажмите «Обновить», чтобы повторить.');}finally{b.disabled=false;}}

// Session chat state is memory-only. The URL can identify a project/thread, never message text.
let selectedProject='';
let selectedSession=null;
let projectsSelectionProof=null;
let selectionGeneration=0;
let initialScrollTarget=null;
let pageReaderScope=null;
let historyScrollSpacer=null;
let historyScrollSlack=0;
let pinnedHistoryScope=null;
let historyScrollIntent=false;
let historyTouchY=null;
let historyScrollbarStartY=null;
let currentTab='tasks';
let projectPage=0;
let sessionPage=0;
let sessionListRequest=0;
let sessionsHaveMore=false;
let sessionRows=[];
let projectNames=[];
let availableProjects=new Set();
let projectEntries=[];
let projectSummaries=new Map();
let projectsGeneration=0;
let projectSort='count';
try{if(localStorage.getItem('project-sort')==='activity')projectSort='activity';}catch(_){}
$('project-sort').value=projectSort;
let pollTimer=null;
let messageAgeTimer=null;
const UUID_RE=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
function chatKey(project,sid){return project+'\u0000'+sid;}
function ensureReceipts(key){if(!receipts.has(key))receipts.set(key,new Map());return receipts.get(key);}
function queryPath(path,values){const params=new URLSearchParams();for(const [k,v] of Object.entries(values)){if(v!==undefined&&v!==null)params.set(k,String(v));}return path+'?'+params.toString();}
function activeSelection(project=selectedProject,sid=selectedSession&&selectedSession.sid,generation=selectionGeneration){return Boolean(csrf&&currentTab==='sessions'&&selectedSession&&selectedProject===project&&selectedSession.sid===sid&&selectionGeneration===generation);}
function updateUrl(){const params=new URLSearchParams();if(selectedProject)params.set('project',selectedProject);if(selectedSession)params.set('sid',selectedSession.sid);const query=params.toString();history.replaceState(null,'',location.pathname+(query?'?'+query:''));}
function parseDeepLink(){const params=new URLSearchParams(location.search);if(params.getAll('project').length>1||params.getAll('sid').length>1)return null;const project=params.get('project')||'';const sid=params.get('sid')||'';if(!project&&!sid)return null;if(!project||!UUID_RE.test(sid))return null;return {project,sid};}
function stopPolling(){stopLive();stopMessageAges();if(pollTimer!==null){clearInterval(pollTimer);pollTimer=null;}}
function startPolling(){stopPolling();syncMessageAges();startLive();}
// INV-WSESS-51..53: one selected history transport; HTTP alone grants the lease.
let liveGeneration=0,liveTransport=null,liveAndroidAuthGeneration=-1;
function liveVisible(){return Boolean(csrf&&currentTab==='sessions'&&selectedSession&&document.visibilityState==='visible');}
function settingsProjection(data){
  if(!sessionSettingsSnapshot(data,{perf:performance.now(),wall:Date.now()}))return null;
  return JSON.stringify([data.schema,data.source,data.scope,data.model,data.effort]);
}
function settingsLeaseRemaining(snapshot){
  if(!snapshot)return 0;
  const perf=performance.now()-snapshot.perf,wall=Date.now()-snapshot.wall;
  if(perf<0||wall<0)snapshot.discontinuous=true;
  if(snapshot.discontinuous)return 0;
  return snapshot.expires_in_ms-Math.max(0,perf,wall);
}
function stopLive(invalidate=true){
  liveGeneration++;
  const live=liveTransport;liveTransport=null;
  if(live){if(live.es)live.es.close();if(live.controller)live.controller.abort();for(const timer of live.timers)clearTimeout(timer);}
  if(invalidate){const state=currentSessionKey()&&historyData.get(currentSessionKey());if(state)state.sessionSettings=null;}
}
function liveCurrent(live){return liveTransport===live&&live.generation===liveGeneration&&live.auth===chatAuthGeneration&&activeSelection(live.project,live.sid,live.selection)&&liveVisible();}
function liveLater(live,delay,callback){const timer=setTimeout(()=>{live.timers.delete(timer);if(liveCurrent(live))callback();},delay);live.timers.add(timer);return timer;}
function validLiveSnapshot(data,live){
  if(!exactFields(data,['schema','project','sid','epoch','revision','observation','source','observed_at','history'])||data.schema!==1||data.project!==live.project||data.sid!==live.sid||data.source!=='owner_history_poll'||!/^[a-f0-9]{32}$/.test(data.epoch)||!Number.isSafeInteger(data.revision)||data.revision<1||!Number.isSafeInteger(data.observation)||data.observation<1||!Number.isInteger(data.observed_at)||data.observed_at<0||data.observed_at>253402300799999)return false;
  const h=data.history;
  if(!h||typeof h!=='object'||Array.isArray(h)||new TextEncoder().encode(JSON.stringify(h)).length>96*1024)return false;
  if(!Array.isArray(h.recent_sends)||h.recent_sends.length>8||!h.recent_sends.every(row=>exactFields(row,['status','message_id','turn_id'])&&UUID_RE.test(row.message_id)&&['accepted','delivery_unknown','rejected'].includes(row.status)&&(row.status==='accepted'?validHistoryId(row.turn_id):row.turn_id===null))||Object.hasOwn(h,'needs_native_attention')&&h.needs_native_attention!==true)return false;
  const common=['recent_sends'];if(Object.hasOwn(h,'session_settings'))common.push('session_settings');if(Object.hasOwn(h,'needs_native_attention'))common.push('needs_native_attention');
  if(Object.hasOwn(h,'history_state'))return exactFields(h,[...common,'history_state','reason'])&&h.history_state==='unavailable'&&h.reason==='unavailable'&&Array.isArray(h.recent_sends);
  return exactFields(h,[...common,'turns','next_cursor','truncated'])&&Array.isArray(h.turns)&&h.turns.length<=8&&typeof h.truncated==='boolean'&&(h.next_cursor===null||typeof h.next_cursor==='string'&&h.next_cursor.length>0&&h.next_cursor.length<=4096)&&Array.isArray(h.recent_sends)&&h.recent_sends.length<=8&&(!Object.hasOwn(h,'needs_native_attention')||h.needs_native_attention===true)&&h.turns.reduce((sum,turn)=>sum+(Array.isArray(turn?.items)?turn.items.length:25),0)<=24&&h.turns.every(turn=>exactFields(turn,['id','status','items'])&&validHistoryId(turn.id)&&typeof turn.status==='string'&&Array.isArray(turn.items)&&turn.items.every(item=>{const keys=['id','role','text','truncated','timestamp','time_precision'];if(Object.hasOwn(item,'client_id'))keys.push('client_id');return exactFields(item,keys)&&validHistoryId(item.id)&&['assistant','user'].includes(item.role)&&typeof item.text==='string'&&Array.from(item.text).length<=8000&&typeof item.truncated==='boolean'&&(item.timestamp===null||Number.isInteger(item.timestamp)&&item.timestamp>=0&&item.timestamp<=253402300799)&&['item','turn','unknown'].includes(item.time_precision)&&(!Object.hasOwn(item,'client_id')||item.role==='user'&&UUID_RE.test(item.client_id));}));
}
function bindLiveEpoch(state,data){
  if(state.liveEpoch&&state.liveEpoch!==data.epoch){
    state.turns.clear();state.order=[];state.olderAnchors=[];state.initialized=false;state.windowIds=null;state.windowOlder=false;state.pendingLatest=false;state.truncated=false;state.liveGap=false;state.sessionSettings=null;state.latestWindowIds=[];state.liveProjection=null;state.settingsFloor=0;state.leaseObservation=0;state.historyObservation=0;state.historyRevision=0;
  }
  state.liveEpoch=data.epoch;
}
function acceptLiveLease(live,data,started,merge=false){
  if(!liveCurrent(live)||!validLiveSnapshot(data,live))return;
  const state=normalizeHistoryState(live.key);
  if(state.liveEpoch&&state.liveEpoch!==data.epoch){if(started.epoch!==state.liveEpoch)return;if(!merge){state.sessionSettings=null;syncCurrentSessionControls();return;}bindLiveEpoch(state,data);}
  if(!state.liveEpoch)state.liveEpoch=data.epoch;
  const projection=settingsProjection(data.history.session_settings);
  if(data.revision<(state.settingsFloor||0)&&projection!==state.liveProjection)return;
  if(data.observation<=(state.leaseObservation||0))return;
  state.leaseObservation=data.observation;
  const snapshot=sessionSettingsSnapshot(data.history.session_settings,started);
  if(projection!==state.liveProjection){if(data.revision>=(state.settingsFloor||0)){state.sessionSettings=null;state.settingsFloor=Math.max(state.settingsFloor||0,data.revision);syncCurrentSessionControls();}return;}
  state.settingsFloor=Math.max(state.settingsFloor||0,data.revision);
  if(!snapshot)return;
  state.sessionSettings={...snapshot,selection:live.selection};state.settingsFailure=false;
  syncCurrentSessionControls();
}
function applyLiveHistory(live,data){
  if(!liveCurrent(live)||!validLiveSnapshot(data,live))return false;
  const state=normalizeHistoryState(live.key),newEpoch=Boolean(state.liveEpoch&&state.liveEpoch!==data.epoch);
  bindLiveEpoch(state,data);
  if(data.revision<(state.settingsFloor||0)||data.revision<=(state.historyRevision||0)||data.observation<=(state.historyObservation||0))return true;
  const projection=settingsProjection(data.history.session_settings);
  if(state.liveProjection!==undefined&&state.liveProjection!==projection)state.sessionSettings=null;
  state.liveProjection=projection;state.historyRevision=data.revision;state.historyObservation=data.observation;state.settingsFloor=Math.max(state.settingsFloor||0,data.revision);
  const h=data.history;let decision=captureHistoryScroll(live.project,live.sid,live.selection,false);
  const known=new Set(historyItems(state).map(entry=>entry.key));
  const ids=(h.turns||[]).flatMap(turn=>(turn.items||[]).map(item=>JSON.stringify([turn.id,item.id])));
  if(!newEpoch&&state.latestWindowIds?.length&&ids.length&&!ids.some(id=>state.latestWindowIds.includes(id)))state.liveGap=true;
  state.latestWindowIds=ids;
  if(h.truncated)state.liveGap=true;
  const hold=state.windowIds!==null&&(state.windowOlder||focusedHistoryBubble()||decision&&decision.kind!=='bottom');
  if(hold&&decision?.kind==='bottom')decision=captureHistoryScroll(live.project,live.sid,live.selection,true);
  state.unavailable=h.history_state==='unavailable';state.confirmedOrigin=state.unavailable;
  if(state.unavailable){state.initialized=true;state.attention=h.needs_native_attention===true;for(const receipt of h.recent_sends)applyReceipt(live.key,receipt);}
  else mergeHistory(live.key,h,null);
  decision=reconcileHistoryCorrelations(state,known,decision);
  confirmProjectSelection(live.selection);state.latestHistoryError=state.unavailable?'История пока недоступна':'';state.historyError=state.latestHistoryError;state.historyErrorOrigin=state.historyError?'latest':null;
  if(!hold){state.windowIds=null;state.windowOlder=false;state.pendingLatest=false;}else if(historyItems(state).some(entry=>!known.has(entry.key)))state.pendingLatest=true;
  renderHistory(live.key);$('history-status').textContent=historyErrorText(state);syncCurrentSessionControls();restoreHistoryScroll(decision,live.project,live.sid,live.selection);return true;
}
async function liveJSON(live){
  const controller=new AbortController();live.controller=controller;const started={perf:performance.now(),wall:Date.now(),epoch:normalizeHistoryState(live.key).liveEpoch};let timer;
  try{
    const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new Error(messages.unavailable));},6000);});
    const data=await Promise.race([api(queryPath('/api/session-live-snapshot',{project:live.project,sid:live.sid}),undefined,controller.signal,()=>liveCurrent(live)),deadline]);
    if(!liveCurrent(live))return null;
    if(!validLiveSnapshot(data,live))throw new Error(messages.unavailable);
    return {data,started};
  }finally{clearTimeout(timer);if(live.controller===controller)live.controller=null;}
}
function liveTerminal(live,error){
  const terminal=error.status===401||error.status===403||error.status===422||error.status===503&&error.code==='unsupported';
  if(terminal){if(live.es){live.es.close();live.es=null;}if(live.controller)live.controller.abort();for(const timer of live.timers)clearTimeout(timer);live.timers.clear();live.mode='terminal';}
  if(error.status===401||error.status===403){const state=normalizeHistoryState(live.key);state.sessionSettings=null;syncCurrentSessionControls();}
  if(error.status===403){if(liveAndroidAuthGeneration!==chatAuthGeneration&&androidAuth()){liveAndroidAuthGeneration=chatAuthGeneration;androidAuth().requestAuth();}notice('Войдите снова для обновления переписки.');return true;}
  if(error.status===401||error.status===422)return true;
  if(error.status===503&&error.code==='unsupported'){notice('Обновление переписки недоступно в этой версии. Обновите её вручную.');return true;}
  return false;
}
function liveFallback(live){
  if(!liveCurrent(live))return;live.mode='fallback';live.fallbackRetry=false;live.fallbackStarted=performance.now();let failures=0;
  const poll=async()=>{let delay=5000;try{const result=await liveJSON(live);if(result){applyLiveHistory(live,result.data);acceptLiveLease(live,result.data,result.started,true);failures=0;}}catch(error){if(!liveCurrent(live)||liveTerminal(live,error))return;failures++;delay=[5000,10000,30000][Math.min(failures-1,2)];}if(liveCurrent(live)&&live.mode==='fallback')liveLater(live,delay,poll);};
  liveLater(live,5000,poll);
  liveLater(live,60000,()=>{if(live.controller)live.controller.abort();for(const timer of live.timers)clearTimeout(timer);live.timers.clear();live.generation=++liveGeneration;live.fallbackRetry=true;liveOpen(live);});
}
async function liveFailure(live){
  if(!liveCurrent(live)||live.failureLatched)return;
  live.failureLatched=true;if(live.es){live.es.close();live.es=null;}if(live.controller)live.controller.abort();for(const timer of live.timers)clearTimeout(timer);live.timers.clear();
  const now=performance.now();live.failures=live.failures.filter(at=>at>now-30000);live.failures.push(now);
  const state=normalizeHistoryState(live.key);
  if(!state.unavailable&&!state.historyError)$('history-status').textContent='Обновление переписки приостановлено. История и черновик сохранены.';
  try{const result=await liveJSON(live);if(result){applyLiveHistory(live,result.data);acceptLiveLease(live,result.data,result.started,true);}}catch(error){if(!liveCurrent(live)||liveTerminal(live,error))return;if(error.status===429&&!live.fallbackRetry){liveLater(live,[1000,2000,5000,10000,30000][Math.min(live.failures.length-1,4)],()=>liveOpen(live));return;}}
  if(!liveCurrent(live))return;
  if(live.fallbackRetry||live.failures.length>=3)liveFallback(live);else liveLater(live,[1000,2000,5000,10000,30000][Math.min(live.failures.length-1,4)],()=>liveOpen(live));
}
function liveOpen(live){
  if(!liveCurrent(live))return;live.failureLatched=false;live.mode='connecting';
  const es=new EventSource(queryPath('/api/session-events',{project:live.project,sid:live.sid}));live.es=es;
  const current=()=>liveCurrent(live)&&live.es===es&&!live.failureLatched;
  es.addEventListener('snapshot',event=>{
    if(!current())return;let data;try{data=JSON.parse(event.data);}catch(_){liveFailure(live);return;}
    if(!validLiveSnapshot(data,live)||event.lastEventId!==data.epoch+':'+data.revision){liveFailure(live);return;}
    if(!applyLiveHistory(live,data)){liveFailure(live);return;}
    if(live.mode!=='sse'){live.mode='sse';live.fallbackRetry=false;const renew=async()=>{if(!current())return;try{const result=await liveJSON(live);if(result)acceptLiveLease(live,result.data,result.started);}catch(error){if(current()&&liveTerminal(live,error))return;}if(current())liveLater(live,5000,renew);};liveLater(live,5000,renew);}
  });
  es.addEventListener('reset',event=>{if(!current())return;try{const data=JSON.parse(event.data);if(data.project===live.project&&data.sid===live.sid&&data.reason==='overflow'){const state=normalizeHistoryState(live.key);state.liveGap=true;renderHistory(live.key);}}catch(_){liveFailure(live);}});
  es.addEventListener('unavailable',()=>{if(current())liveFailure(live);});es.onerror=()=>{if(current())liveFailure(live);};
}
function startLive(){
  if(!liveVisible())return;const live={project:selectedProject,sid:selectedSession.sid,key:currentSessionKey(),auth:chatAuthGeneration,selection:selectionGeneration,generation:++liveGeneration,timers:new Set(),failures:[],es:null,controller:null,mode:'initial',failureLatched:false};liveTransport=live;
  const state=normalizeHistoryState(live.key);if(state.liveProjection===undefined)state.liveProjection=settingsProjection(state.sessionSettings&&{schema:state.sessionSettings.schema,source:state.sessionSettings.source,scope:state.sessionSettings.scope,model:state.sessionSettings.model,effort:state.sessionSettings.effort,age_ms:state.sessionSettings.age_ms,expires_in_ms:state.sessionSettings.expires_in_ms});
  const initial=historyFlights.get(live.key)?.promise;if(initial)initial.then(()=>{if(liveCurrent(live)){if(state.historyError&&!state.initialized)return;state.liveProjection=state.sessionSettings?JSON.stringify([state.sessionSettings.schema,state.sessionSettings.source,state.sessionSettings.scope,state.sessionSettings.model,state.sessionSettings.effort]):null;liveOpen(live);}});else liveOpen(live);
}

function currentSessionKey(){return selectedProject&&selectedSession?chatKey(selectedProject,selectedSession.sid):null;}
function modelDraft(key){if(!modelDrafts.has(key))modelDrafts.set(key,{modelId:'',label:'',effort:'',catalog:null,expires:0,request:0,loading:false,stale:false,message:''});return modelDrafts.get(key);}
function explicitModelReady(key){const state=modelDraft(key);if(!state.modelId)return true;const row=state.catalog?.rows.find(row=>row.id===state.modelId);return Boolean(!state.loading&&!state.stale&&state.expires>performance.now()&&row&&row.efforts.includes(state.effort));}
// The snapshot is configured/persisted thread metadata, never active-turn telemetry.
function validSessionSetting(value){
  if(value===null)return true;
  if(typeof value!=='string'||!value.trim()||Array.from(value).length>256)return false;
  if(Array.from(value).some(char=>{const code=char.codePointAt(0);return code<32||code>=127&&code<=159||code>=0xd800&&code<=0xdfff;}))return false;
  const secret=/(?:(?:api[_-]?key|access[_-]?key|token|secret|password|passwd|pwd|authorization)"?\s*[=:]\s*"?(?:bearer\s+)?[^\s&"]+|(?<![\p{L}\p{N}_])bearer\s+\S+|(?<![\p{L}\p{N}_])(?:sk|xox[a-z]|ghp|gho|github_pat)-[A-Za-z0-9_-]{8,}|(?<![\p{L}\p{N}_])(?=[\p{L}\p{N}_])[A-Za-z0-9+/_-]{40,}(?<=[\p{L}\p{N}_])(?![\p{L}\p{N}_]))/iu;
  return !secret.test(value);
}
function sessionSettingsSnapshot(data,started){
  if(!exactFields(data,['schema','scope','source','model','effort','age_ms','expires_in_ms'])||data.schema!==1||data.scope!=='configured_or_persisted'||data.source!=='thread_read'||!validSessionSetting(data.model)||!validSessionSetting(data.effort)||!Number.isInteger(data.age_ms)||data.age_ms<0||data.age_ms>=15000||!Number.isInteger(data.expires_in_ms)||data.expires_in_ms!==15000-data.age_ms)return null;
  const begin=typeof started==='number'?{perf:started,wall:Date.now()}:started;
  const snapshot={...data,...begin,expires:begin.perf+data.expires_in_ms};
  return settingsLeaseRemaining(snapshot)>0?snapshot:null;
}
function renderSessionSettings(){
  if(sessionSettingsTimer!==null){clearTimeout(sessionSettingsTimer);sessionSettingsTimer=null;}
  const key=currentSessionKey(),state=key&&historyData.get(key),snapshot=state?.sessionSettings;
  const known=snapshot&&settingsLeaseRemaining(snapshot)>0&&snapshot.selection===selectionGeneration;
  const model=known&&snapshot.model||'модель неизвестна',effort=known&&snapshot.effort||'уровень неизвестен';
  $('current-model-status').textContent='Сессия: '+model+' · Размышление: '+effort;
  $('current-model-status').title=state?.settingsFailure?'Настройки сессии неизвестны: последнее обновление не удалось.':snapshot&&!known?'Настройки сессии неизвестны: данные устарели.':'';
  if(known){
    const generation=selectionGeneration;
    sessionSettingsTimer=setTimeout(()=>{sessionSettingsTimer=null;if(key===currentSessionKey()&&activeSelection()&&generation===selectionGeneration){syncCurrentSessionControls();}},Math.max(1,settingsLeaseRemaining(snapshot)));
  }
}
function renderModelControls(){
  if(modelExpiryTimer!==null){clearTimeout(modelExpiryTimer);modelExpiryTimer=null;}
  const key=currentSessionKey(),state=key?modelDraft(key):null,model=$('chat-model'),effort=$('chat-effort');
  const rows=state?.catalog?.rows||[],locked=Boolean(key&&(sendsInFlight.has(key)||hasUnknown(key)));
  renderSessionSettings();
  model.replaceChildren(new Option('Использовать текущую модель',''));
  for(const row of rows)model.add(new Option(row.label,row.id));
  let row=state&&rows.find(row=>row.id===state.modelId);
  if(state?.modelId&&!row)model.add(new Option(state.label||'Выбранная модель недоступна',state.modelId));
  model.value=state?.modelId||'';
  effort.replaceChildren(new Option('Выберите уровень размышления',''));
  for(const value of row?.efforts||[])effort.add(new Option(value,value));
  if(state?.effort&&!(row?.efforts||[]).includes(state.effort))effort.add(new Option(state.effort,state.effort));
  effort.value=state?.effort||'';
  model.disabled=!key||locked;effort.disabled=!key||locked||!state.modelId||!row;
  $('models-refresh').disabled=!key||locked||Boolean(state?.loading);
  $('model-notes').hidden=!state?.catalog;
  let message=state?.message||'';
  if(state?.loading)message='Загружаем список моделей. Можно отправить сообщение с текущими настройками.';
  else if(state?.stale)message='Явный выбор требует свежего списка моделей; черновик и выбор сохранены.';
  else if(state?.catalog&&state.expires<=performance.now())message='Срок доступности списка истёк. Получите свежий список моделей; черновик и выбор сохранены.';
  else if(state?.modelId&&!row)message='Выбранная модель недоступна. Обновите список или измените выбор; черновик сохранён.';
  $('model-status').textContent=message;
  const attempt=key&&latestAttempts.get(key),pending=Boolean(key&&(sendsInFlight.has(key)||hasUnknown(key)));
  const selection=pending?attempt?.selection:state?.modelId?{model_id:state.modelId,effort:state.effort}:null;
  const requested=selection&&(pending?attempt.selectionLabel||selection.model_id:rows.find(item=>item.id===selection.model_id)?.label||state?.label||selection.model_id);
  $('next-model-status').textContent=selection?'Следующая отправка: '+requested+' · Размышление: '+(selection.effort||'выберите уровень'):'Следующая отправка: настройки сессии';
  // The hint describes the next draft choice, never the immutable dispatched pair.
  let hint='';
  if(state?.modelId&&!pending){
    if(state.loading)hint='Проверяем выбор';
    else if(state.stale||state.catalog&&state.expires<=performance.now())hint='Каталог устарел';
    else if(!state.catalog)hint='Каталог недоступен';
    else if(!row)hint='Модель недоступна';
    else if(!state.effort)hint='Выберите уровень';
    else if(!row.efforts.includes(state.effort))hint='Уровень недоступен';
  }
  $('next-model-hint').textContent=hint;$('next-model-hint').hidden=!hint;
  if(state?.catalog&&state.expires>performance.now()){
    const project=selectedProject,sid=selectedSession.sid,generation=selectionGeneration;
    modelExpiryTimer=setTimeout(()=>{modelExpiryTimer=null;if(activeSelection(project,sid,generation))syncCurrentSessionControls();},Math.max(1,state.expires-performance.now()));
  }
}
function validModelCatalog(data){return Boolean(data&&data.schema===1&&data.vendor==='codex'&&data.context_kind==='legacy_unbound'&&data.selection_support==='available'&&typeof data.catalog_id==='string'&&/^[0-9a-f]{64}$/.test(data.catalog_id)&&Number.isFinite(data.expires_in_ms)&&data.expires_in_ms>0&&data.expires_in_ms<=60000&&Array.isArray(data.rows)&&data.rows.length>0&&data.rows.length<=256&&new Set(data.rows.map(row=>row?.id)).size===data.rows.length&&data.rows.every(row=>row&&typeof row.id==='string'&&row.id&&typeof row.label==='string'&&Array.isArray(row.efforts)&&row.efforts.length>0&&row.efforts.length<=32&&row.efforts.every(value=>typeof value==='string'&&value)&&new Set(row.efforts).size===row.efforts.length));}
async function loadModelCatalog(){
  const key=currentSessionKey();if(!key)return;
  const project=selectedProject,sid=selectedSession.sid,generation=selectionGeneration,state=modelDraft(key),request=++state.request;
  const current=()=>activeSelection(project,sid,generation)&&state.request===request;
  state.loading=true;syncCurrentSessionControls();
  try{const data=await api(queryPath('/api/session-models',{project,sid}),undefined,undefined,current);if(!current())return;
    state.catalog=validModelCatalog(data)?data:null;state.expires=state.catalog?performance.now()+data.expires_in_ms:0;state.stale=false;
    state.message=state.catalog?'':'Выбор модели недоступен. Можно наследовать текущие настройки и отправить сообщение.';
  }catch(_){if(current()){state.catalog=null;state.expires=0;state.message='Список моделей недоступен. Можно наследовать текущие настройки и отправить сообщение.';}}
  finally{if(state.request===request)state.loading=false;if(current())syncCurrentSessionControls();}
}
function syncCurrentSessionControls(){const key=currentSessionKey();const historyBusy=Boolean(key&&historyFlights.has(key));const state=key&&historyData.get(key);const hasOlder=Boolean(state&&(hasEarlierHistory(state)||state.olderAnchors.some(anchor=>!anchor.error)));renderModelControls();$('chat-send').disabled=!csrf||currentTab!=='sessions'||!key||Boolean(selectedSession?.created&&!state?.initialized&&!state?.confirmedOrigin)||sendsInFlight.has(key)||hasUnknown(key)||!explicitModelReady(key);$('chat-refresh').disabled=!key||historyBusy;$('history-older').disabled=!key||historyBusy||!hasOlder;$('history-retry').hidden=!(state&&state.historyError);$('history-retry').disabled=!key||historyBusy;renderCurrentSendStatus();syncRenameControls();syncCreateControls();}
function showTab(tab,load=true){currentTab=tab;const tasks=tab==='tasks';if(tasks)clearHistoryScrollSlack();$('tab-tasks').setAttribute('aria-selected',String(tasks));$('tab-sessions').setAttribute('aria-selected',String(!tasks));$('tasks-panel').hidden=!tasks;$('sessions-panel').hidden=tasks;syncCurrentSessionControls();if(tasks){stopPolling();if(load&&!taskLoaded)refresh();}else{if(load&&!projectNames.length)loadProjects();else if(load&&!selectedProject)loadSessionList(0,false);startPolling();}}
function setSessionStatus(text){$('session-list-status').textContent=text;}
// Disclosure is a local UI choice; only a fresh deliberate selection consumes proof.
function setProjectsExpanded(expanded){
  const body=$('projects-body'),toggle=$('projects-toggle');
  if(!expanded&&body.contains(document.activeElement))toggle.focus({preventScroll:true});
  body.hidden=!expanded;toggle.setAttribute('aria-expanded',String(expanded));
}
function confirmProjectSelection(generation){
  if(projectsSelectionProof!==generation)return;
  projectsSelectionProof=null;if(selectedSession)selectedSession.proven=true;
  setProjectsExpanded(false);
}
$('projects-toggle').addEventListener('click',()=>setProjectsExpanded($('projects-body').hidden));
document.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||event.defaultPrevented||event.isComposing)return;
  const details=document.activeElement?.closest('details[open]');
  if(details){event.preventDefault();details.open=false;details.querySelector(':scope>summary')?.focus({preventScroll:true});}
});

function projectExactTime(timestamp){
  const date=new Date(timestamp*1000);
  if(!Number.isFinite(date.getTime()))return null;
  return new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(date);
}
// Project badges have their own compact clock semantics; message ages stay unchanged.
function projectAge(timestamp){
  if(!Number.isFinite(timestamp)||!Number.isFinite(new Date(timestamp*1000).getTime()))return '?';
  const age=Date.now()/1000-timestamp;
  if(age<0)return '?';
  if(age<60)return '<1м';
  if(age<3600)return Math.floor(age/60)+'м';
  if(age<86400)return Math.floor(age/3600)+'ч';
  return Math.floor(age/86400)+'д';
}
function knownProjectSummary(name){
  const value=projectSummaries.get(name);
  return value&&['fresh','stale'].includes(value.summary_state)&&Number.isSafeInteger(value.session_count)&&value.session_count>=0?value:null;
}
function renderProjectDetails(){
  const details=$('project-details'),content=$('project-details-content');
  details.hidden=!selectedProject;content.replaceChildren();if(!selectedProject)return;
  details.querySelector('summary').textContent='Сведения о проекте '+selectedProject;
  content.setAttribute('role','region');content.setAttribute('aria-label','Сведения о проекте '+selectedProject);
  const value=knownProjectSummary(selectedProject),available=availableProjects.has(selectedProject),known=Boolean(value);
  content.append(node('p',selectedProject));
  content.append(node('p',!available?'Проект недоступен':known?value.session_count+' сессий':'Число сессий неизвестно'));
  const exact=known&&value.last_activity!==null&&projectAge(value.last_activity)!=='?'&&projectExactTime(value.last_activity);
  content.append(node('p',!available?'Активность недоступна':exact?'Последняя активность: '+exact.replace(',','')+' МСК':known&&value.last_activity===null?'Нет активности':'Активность неизвестна'));
  const asOf=known&&projectExactTime(value.as_of);
  content.append(node('p',asOf?'Сводка на '+asOf.replace(',','')+' МСК'+(value.summary_state==='stale'?' · данные устарели':''):'Время сводки неизвестно'));
}
function renderProjects(){
  $('projects-heading').textContent=selectedProject||'Проекты';
  const cloud=$('project-cloud'),focused=document.activeElement,y=window.scrollY;
  const existing=new Map([...cloud.children].map(button=>[button.dataset.project,button]));
  const aliasCompare=(a,b)=>{const x=a.name.toLowerCase(),z=b.name.toLowerCase();return x<z?-1:x>z?1:a.name<b.name?-1:a.name>b.name?1:0;};
  const activityGroup=value=>!value?3:value.last_activity===null?2:projectAge(value.last_activity)==='?'?3:value.summary_state==='fresh'?0:1;
  const ordered=projectEntries.slice().sort((a,b)=>{
    const x=knownProjectSummary(a.name),z=knownProjectSummary(b.name);
    if(projectSort==='count'){if(Boolean(x)!==Boolean(z))return x?-1:1;if(x&&x.session_count!==z.session_count)return z.session_count-x.session_count;}
    else{const gx=activityGroup(x),gz=activityGroup(z);if(gx!==gz)return gx-gz;if(gx<2&&x.last_activity!==z.last_activity)return z.last_activity-x.last_activity;}
    return aliasCompare(a,b);
  });
  const retained=new Set();
  for(const entry of ordered){
    let button=existing.get(entry.name);
    if(!button){button=node('button',undefined,'project-tile');button.type='button';button.dataset.project=entry.name;button.addEventListener('click',()=>projectChanged(entry.name));}
    retained.add(button);
    const value=knownProjectSummary(entry.name),unavailable=!availableProjects.has(entry.name);
    button.disabled=unavailable;button.setAttribute('aria-pressed',String(!unavailable&&selectedProject===entry.name));
    if(!unavailable&&selectedProject===entry.name)button.setAttribute('aria-controls','project-details-content');else button.removeAttribute('aria-controls');
    const bucket=value?Math.min(5,Math.floor(Math.log2(value.session_count+1))):0;
    button.style.setProperty('--tile-width',(112+4*bucket)+'px');
    const details=unavailable?'Недоступен':value?value.session_count+' сессий'+(value.summary_state==='stale'?' · устарело':''):'Число сессий неизвестно';
    button.replaceChildren(node('span',entry.name,'project-name'),document.createTextNode(' '),node('span',unavailable?'недост.':value?String(value.session_count):'?','meta project-badge'),document.createTextNode(' '));
    const activity=unavailable?'?':value?value.last_activity===null?'—':projectAge(value.last_activity):'?';
    let exact=null;
    if(value&&!unavailable&&activity!=='?'&&value.last_activity!==null){
      exact=projectExactTime(value.last_activity);
      const time=node('time',activity,'meta project-badge');
      time.dateTime=new Date(value.last_activity*1000).toISOString();time.title=exact+' МСК';time.dataset.projectTimestamp=String(value.last_activity);
      button.append(time);
    }else button.append(node('span',activity,'meta project-badge'));
    if(!unavailable&&value?.summary_state==='stale')button.append(document.createTextNode(' '),node('span','устар.','meta project-badge'));
    button.setAttribute('aria-label',entry.name+', '+details+', '+(unavailable?'Активность недоступна':exact?'Последняя активность: '+exact+' МСК':value?.last_activity===null?'Нет активности':'Активность неизвестна'));
    button.title=unavailable?'Проект и активность недоступны.':value?'Сводка: '+(projectExactTime(value.as_of)||'время неизвестно')+(value.last_activity===null?' · нет активности':' · последняя активность: '+(exact||'время неизвестно')):'Метаданные временно недоступны. Обновите проекты, чтобы запросить их снова.';
    cloud.append(button);
  }
  for(const button of existing.values())if(!retained.has(button))button.remove();
  if(retained.has(focused)&&!focused.disabled)focused.focus({preventScroll:true});
  if(window.scrollY!==y)window.scrollTo(0,y);
  renderProjectDetails();syncCreateControls();syncMessageAges();
}
function clearUnavailableProject(){projectsSelectionProof=null;setProjectsExpanded(true);stopPolling();selectionGeneration++;initialScrollTarget=null;selectedProject='';selectedSession=null;sessionRows=[];sessionPage=0;sessionsHaveMore=false;clearHistoryView();$('session-list').replaceChildren();$('sessions-more').hidden=true;updateUrl();syncCurrentSessionControls();renderProjects();}
function projectChanged(name){
  if(!availableProjects.has(name))return;
  projectsSelectionProof=null;setProjectsExpanded(true);
  selectedProject=name;sessionPage=0;sessionRows=[];selectedSession=null;selectionGeneration++;initialScrollTarget=null;clearHistoryView();$('session-list').replaceChildren();$('sessions-more').hidden=true;updateUrl();stopPolling();renderProjects();loadSessionList(0,false);
}
async function loadProjects(){
  if(!csrf)return;
  const generation=++projectsGeneration,auth=chatAuthGeneration,selection=selectionGeneration,hadNames=projectEntries.length>0;
  const current=()=>Boolean(csrf&&auth===chatAuthGeneration&&generation===projectsGeneration);
  if(!hadNames)setSessionStatus('Загружаем проекты…');
  $('projects-refresh').disabled=true;
  try{
    const data=await api('/api/session-projects',undefined,undefined,current);if(!current())return;
    if(!Array.isArray(data.projects))throw new Error('invalid projects');
    projectEntries=data.projects.filter(x=>x&&typeof x.name==='string');
    projectNames=projectEntries.map(x=>x.name);
    availableProjects=new Set(projectEntries.filter(x=>x.unavailable!==true).map(x=>x.name));
    if(selectedProject&&!availableProjects.has(selectedProject)){clearUnavailableProject();setSessionStatus('Выбранный проект недоступен. Выберите другой проект.');}
    renderProjects();
    let summarySelection=selectionGeneration;
    const summaryCurrent=()=>current()&&summarySelection===selectionGeneration;
    let summaryFailed=false,summaryUnknown=false;
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
    const validSummary=data=>exactFields(data,['projects'])&&Array.isArray(data.projects)&&data.projects.length<=1000&&data.projects.length===projectNames.length&&new Set(data.projects.map(x=>x?.name)).size===data.projects.length&&data.projects.every(x=>exactFields(x,['name','session_count','last_activity','summary_state','as_of'])&&projectNames.includes(x.name)&&(['fresh','stale'].includes(x.summary_state)?Number.isSafeInteger(x.session_count)&&x.session_count>=0&&(x.last_activity===null||typeof x.last_activity==='number'&&Number.isFinite(x.last_activity)&&x.last_activity>=0)&&typeof x.as_of==='number'&&Number.isFinite(x.as_of)&&x.as_of>=0:['unknown','unavailable'].includes(x.summary_state)&&x.session_count===null&&x.last_activity===null&&x.as_of===null));
    const unknown=data=>data.projects.some(x=>availableProjects.has(x.name)&&x.summary_state==='unknown');
    try{
      let summary=await api('/api/session-project-summary',undefined,controller.signal,summaryCurrent);if(!summaryCurrent())return;
      if(!validSummary(summary))throw new Error('invalid summary');
      if(unknown(summary)){
        $('project-summary-status').textContent='Обновляем метаданные проектов…';
        if(!summaryCurrent()||controller.signal.aborted)return;
        summary=await api('/api/session-project-summary',undefined,controller.signal,summaryCurrent);if(!summaryCurrent())return;
        if(!validSummary(summary))throw new Error('invalid summary');
      }
      summaryUnknown=unknown(summary);
      projectSummaries=new Map(summary.projects.filter(x=>x&&projectNames.includes(x.name)).map(x=>[x.name,x]));
      for(const [name,value] of projectSummaries)if(value.summary_state==='unavailable')availableProjects.delete(name);
      if(selectedProject&&!availableProjects.has(selectedProject)){clearUnavailableProject();summarySelection=selectionGeneration;setSessionStatus('Выбранный проект недоступен. Выберите другой проект.');}
    }catch(_){if(!summaryCurrent())return;projectSummaries.clear();summaryFailed=true;}
    finally{clearTimeout(timer);if(current()&&!summaryCurrent())$('project-summary-status').textContent='';}
    if(!summaryCurrent())return;
    $('project-summary-status').textContent=summaryFailed?'Сводка недоступна. Число сессий и активность неизвестны.':summaryUnknown?'Некоторые метаданные пока недоступны. Обновите проекты, чтобы повторить.':'';
    renderProjects();
    // A refresh never reopens history or overrides a newer user selection.
    if(selection!==selectionGeneration)return;
    const link=!hadNames&&parseDeepLink();
    if(link){
      if(!availableProjects.has(link.project)){clearUnavailableProject();setSessionStatus('Проект из ссылки недоступен. Выберите доступный проект.');return;}
      selectedProject=link.project;renderProjects();await loadSessionList(0,false,link.sid);return;
    }
    if(selectedProject){if(!selectedSession)await loadSessionList(0,false);}
    else setSessionStatus(projectNames.length?'Выберите проект, чтобы увидеть сессии.':'Нет доступных проектов.');
  }catch(_){if(current())setSessionStatus('Список проектов недоступен. Нажмите «Обновить проекты», чтобы повторить.');}
  finally{if(current())$('projects-refresh').disabled=false;}
}
async function loadSessionList(page=0,append=false,deepSid=null){
  const project=selectedProject;if(!project||!availableProjects.has(project))return;
  const generation=selectionGeneration,auth=chatAuthGeneration,request=++sessionListRequest;
  const owns=()=>Boolean(csrf&&auth===chatAuthGeneration&&project===selectedProject&&request===sessionListRequest);
  const current=()=>owns()&&generation===selectionGeneration;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
  setSessionStatus(deepSid?'Ищем выбранную сессию…':'Загружаем сессии…');$('sessions-more').disabled=true;
  try{
    const path=queryPath('/api/sessions',{project,page});let data;
    try{data=await api(path,undefined,controller.signal,current);}
    catch(err){
      if(err.status!==409||err.code!=='stale'||!current()||controller.signal.aborted)throw err;
      setSessionStatus('Обновляем метаданные сессий…');
      data=await api(path,undefined,controller.signal,current);
    }
    if(!current()||controller.signal.aborted)return;
    const rows=Array.isArray(data.rows)?data.rows:[];sessionPage=page;sessionsHaveMore=data.has_more===true;
    sessionRows=append?sessionRows.concat(rows):rows;renderSessions();$('sessions-more').hidden=!sessionsHaveMore;
    if(deepSid){const found=rows.find(row=>row&&row.sid===deepSid);if(found){openChat(found);return;}
      if(sessionsHaveMore&&page<99)return loadSessionList(page+1,false,deepSid);
      setSessionStatus('Сессия из ссылки не найдена среди доступных сессий. Выберите другую из списка.');
    }else setSessionStatus(sessionRows.length?'Выберите сессию для переписки.':'В этом проекте пока нет доступных сессий.');
  }catch(err){if(current())setSessionStatus(err.status===409&&err.code==='stale'?'Метаданные сессий устарели. Обновите список, чтобы повторить.':'Список сессий недоступен. Обновите список, чтобы повторить.');}
  finally{clearTimeout(timer);if(owns())$('sessions-more').disabled=false;}
}
function renderSessions(){const list=$('session-list');const frag=document.createDocumentFragment();for(const row of sessionRows){if(!row||typeof row.sid!=='string'||!UUID_RE.test(row.sid))continue;const b=node('button',undefined,'session-choice'+(selectedSession&&selectedSession.sid===row.sid?' selected':''));b.type='button';b.setAttribute('aria-pressed',String(Boolean(selectedSession&&selectedSession.sid===row.sid)));b.append(node('span',row.title||'Codex','session-title'));const vendorLabel=row.vendor==='codex'?'Codex':row.vendor==='claude'?'Claude':'Вендор неизвестен';b.append(node('span',vendorLabel,'session-vendor-badge'));b.append(node('span',statusLabel(row.status),'meta'));if(row.needs_native_attention===true)b.append(node('span','Нужно действие в клиенте Codex; ответы из панели пока недоступны.','attention-inline'));b.addEventListener('click',()=>openChat(row));frag.append(b);}list.replaceChildren(frag);}
function statusLabel(status){const labels={active:'Работает',idle:'Готова',notLoaded:'Недоступна',systemError:'Ошибка',completed:'Завершён',interrupted:'Прерван',failed:'Ошибка',inProgress:'Выполняется'};return labels[status]||'Состояние неизвестно';}
function chatError(err){if(err&&err.code==='stale')return 'Сессия устарела или изменилась. Обновите список и выберите её снова.';return err&&err.message||messages.unavailable;}
function clearHistoryScrollSlack(){historyScrollSlack=0;pinnedHistoryScope=null;historyScrollIntent=false;historyTouchY=null;historyScrollbarStartY=null;if(historyScrollSpacer){historyScrollSpacer.remove();historyScrollSpacer=null;}}
function setHistoryScrollSlack(height){const bounded=Math.max(0,Math.min(window.innerHeight,Math.ceil(height)));historyScrollSlack=bounded;if(!bounded){clearHistoryScrollSlack();return;}if(!historyScrollSpacer){historyScrollSpacer=node('li',undefined,'history-scroll-slack');historyScrollSpacer.setAttribute('aria-hidden','true');historyScrollSpacer.append(document.createElementNS('http://www.w3.org/2000/svg','svg'));}const svg=historyScrollSpacer.firstElementChild;svg.setAttribute('width','0');svg.setAttribute('height',String(bounded));svg.setAttribute('focusable','false');const list=$('chat-items');if(historyScrollSpacer.parentNode!==list)list.append(historyScrollSpacer);}
function clearHistoryView(){stopMessageAges();clearHistoryScrollSlack();historyData.delete(chatKey(selectedProject,selectedSession&&selectedSession.sid||''));$('chat-panel').hidden=true;$('history-new').hidden=true;$('chat-items').replaceChildren();$('receipt-list').replaceChildren();$('history-status').textContent='';$('history-retry').hidden=true;$('send-status').textContent='';$('history-truncated').hidden=true;$('native-attention').hidden=true;$('chat-draft').value='';}
function openChat(row){if(!row||!UUID_RE.test(row.sid))return;const proven=selectedSession?.sid===row.sid&&selectedSession.proven===true;pageReaderScope=null;if($('session-list-status').textContent==='Выберите сессию для переписки.')setSessionStatus('');stopPolling();clearHistoryScrollSlack();selectionGeneration++;projectsSelectionProof=proven?null:selectionGeneration;selectedSession={proven,created:row.configuredCreated===true,sid:row.sid,title:typeof row.title==='string'?row.title:'Codex',needs:row.needs_native_attention===true};initialScrollTarget={project:selectedProject,sid:row.sid,generation:selectionGeneration};$('chat-title').textContent=selectedSession.title;$('chat-panel').hidden=false;$('history-status').textContent='Загружаем переписку…';$('chat-items').replaceChildren();$('receipt-list').replaceChildren();$('history-truncated').hidden=true;$('native-attention').hidden=!selectedSession.needs;$('chat-draft').value=drafts.get(chatKey(selectedProject,row.sid))||'';updateUrl();renderSessions();renderReceipts();const state=normalizeHistoryState(chatKey(selectedProject,row.sid));state.windowIds=null;state.windowOlder=false;state.pendingLatest=false;$('history-new').hidden=true;if(state.initialized)renderHistory(chatKey(selectedProject,row.sid));if(state.historyError)$('history-status').textContent=historyErrorText(state);syncCurrentSessionControls();loadHistory(false);loadModelCatalog();startPolling();}
// INV-WSESS-37: immutable in-memory operations survive dialog closure, never retry POST.
function exactFields(value,keys){return Boolean(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key)));}
function createState(project){if(!creates.has(project))creates.set(project,{operation:null,status:'draft',inFlight:false,loading:false,available:false,message:'',generation:0,auth:chatAuthGeneration});return creates.get(project);}
function closeCreateDialog(){createDialogEpoch++;createDialogProject=null;if($('create-dialog').open)$('create-dialog').close();}
function syncCreateControls(){
  $('create-open').disabled=!csrf||!selectedProject||!availableProjects.has(selectedProject);
  const state=createDialogProject&&creates.get(createDialogProject);if(!state)return;
  $('create-vendor').disabled=state.loading||state.inFlight||Boolean(state.operation);
  $('create-submit').disabled=!state.available||state.loading||state.inFlight||Boolean(state.operation)||selectedProject!==createDialogProject||state.optionsGeneration!==selectionGeneration;
  $('create-check').hidden=!state.operation;$('create-check').disabled=state.inFlight;
  $('create-status').textContent=state.message;
}
function validCreateOptions(data,project){return exactFields(data,['schema','project','options'])&&data.schema===1&&data.project===project&&Array.isArray(data.options)&&data.options.length===1&&data.options.every(row=>exactFields(row,['context_mode','provider_id','available','reason'])&&row.context_mode==='configured'&&row.provider_id==='codex'&&typeof row.available==='boolean'&&row.reason===(row.available?null:'unavailable'));}
async function openCreateDialog(){
  if(!csrf||!selectedProject||!availableProjects.has(selectedProject))return;
  const project=selectedProject,previous=creates.get(project);
  if(previous?.status==='accepted'&&previous.selected)creates.delete(project);
  const state=createState(project),auth=chatAuthGeneration,generation=selectionGeneration,epoch=++createDialogEpoch;
  const current=()=>auth===chatAuthGeneration&&createDialogProject===project&&createDialogEpoch===epoch&&selectedProject===project&&selectionGeneration===generation&&$('create-dialog').open;
  createDialogProject=project;state.optionsGeneration=generation;state.loading=true;state.available=false;
  const pendingOption=new Option('Codex','codex');pendingOption.disabled=true;
  $('create-vendor').replaceChildren(pendingOption);syncCreateControls();
  if(!$('create-dialog').open)$('create-dialog').showModal();
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
  try{const data=await api(queryPath('/api/session-create-options',{project}),undefined,controller.signal,current);if(!current())return;
    if(!validCreateOptions(data,project))throw new Error();
    state.available=data.options[0].available;const option=new Option('Codex','codex');option.disabled=!state.available;$('create-vendor').replaceChildren(option);
    if(!state.operation)state.message=state.available?'':'Создание пока недоступно.';
  }catch(_){if(current()){state.available=false;$('create-vendor').replaceChildren(new Option('Вендор недоступен',''));if(!state.operation)state.message='Создание пока недоступно.';}}
  finally{clearTimeout(timer);if(current()){state.loading=false;syncCreateControls();}}
}
function validCreateResult(data,operation){
  if(!data||data.operation_id!==operation.operation_id)return false;
  if(data.status==='delivery_unknown')return exactFields(data,['operation_id','status']);
  const row=data.session;
  return data.status==='accepted'&&exactFields(data,['operation_id','status','session'])&&exactFields(row,['sid','project','vendor','context_mode','title'])&&typeof row.sid==='string'&&UUID_RE.test(row.sid)&&row.project===operation.project&&row.vendor==='codex'&&row.context_mode==='configured'&&(row.title===null||typeof row.title==='string'&&Array.from(row.title).length<=500);
}
function confirmCreate(state,data,generation){
  if(!validCreateResult(data,state.operation))return false;
  if(data.status!=='accepted')return false;
  state.status='accepted';state.message='Сессия создана. Подтвердите выбор ручной проверкой статуса.';
  projectSummaries.delete(state.operation.project);renderProjects();
  const key=chatKey(state.operation.project,data.session.sid);modelDrafts.delete(key);historyData.delete(key);
  if(selectedProject!==state.operation.project||selectionGeneration!==generation||!availableProjects.has(selectedProject))return true;
  const row={sid:data.session.sid,title:data.session.title||'Новая сессия',vendor:'codex',status:'unknown',configuredCreated:true};
  sessionRows=[row,...sessionRows.filter(existing=>existing.sid!==row.sid)];
  state.selected=true;closeCreateDialog();renderSessions();openChat(row);return true;
}
async function submitCreate(event){
  event.preventDefault();const project=createDialogProject,state=project&&creates.get(project);
  if(!state||state.inFlight||state.operation||!state.available||project!==selectedProject||state.optionsGeneration!==selectionGeneration||$('create-vendor').value!=='codex')return;
  state.operation=Object.freeze({project,operation_id:crypto.randomUUID(),context_mode:'configured',provider_id:'codex'});
  state.generation=selectionGeneration;state.auth=chatAuthGeneration;state.inFlight=true;state.status='sending';state.message='Создаём сессию…';syncCreateControls();
  try{let data;try{data=await api('/api/session-create',state.operation,undefined,()=>state.auth===chatAuthGeneration);}catch(err){if(err.data?.status==='delivery_unknown')data=err.data;else if(['invalid_request','forbidden','stale'].includes(err.code)){if(state.auth===chatAuthGeneration){state.operation=null;state.status='refused';state.message='Создание отклонено. Обновите параметры перед новой попыткой.';}return;}else throw err;}
    if(state.auth!==chatAuthGeneration)return;
    if(!confirmCreate(state,data,state.generation)){state.status='delivery_unknown';state.message='Создание не подтверждено. Проверить статус';}
  }catch(_){if(state.auth===chatAuthGeneration){state.status='delivery_unknown';state.message='Создание не подтверждено. Проверить статус';}}
  finally{state.inFlight=false;if(state.auth===chatAuthGeneration)syncCreateControls();}
}
async function checkCreate(){
  const state=createDialogProject&&creates.get(createDialogProject);if(!state?.operation||state.inFlight)return;
  const auth=chatAuthGeneration,generation=selectionGeneration;state.inFlight=true;state.message='Проверяем статус…';syncCreateControls();
  try{const data=await api(queryPath('/api/session-create-status',state.operation),undefined,undefined,()=>auth===chatAuthGeneration);
    if(auth!==chatAuthGeneration)return;
    if(!confirmCreate(state,data,generation)){state.status='delivery_unknown';state.message='Создание не подтверждено. Проверить статус';}
  }catch(_){if(auth===chatAuthGeneration){state.status='delivery_unknown';state.message='Проверка недоступна. Проверить статус';}}
  finally{state.inFlight=false;if(auth===chatAuthGeneration)syncCreateControls();}
}

// INV-WSESS-30: rename receipts and drafts remain local to this authenticated page.
function renameState(key){if(!renames.has(key))renames.set(key,{draft:selectedSession.title,status:'draft',operation:null,inFlight:false,message:''});return renames.get(key);}
function closeRenameDialog(){if(renameStatusTimer!==null){clearTimeout(renameStatusTimer);renameStatusTimer=null;}$('rename-status').textContent='';renameDialogScope=null;if($('rename-dialog').open)$('rename-dialog').close();syncRenameControls();}
function syncRenameControls(){
  const key=currentSessionKey(),state=key&&renames.get(key);
  if(renameDialogScope&&(!activeSelection(renameDialogScope.project,renameDialogScope.sid,renameDialogScope.generation)))closeRenameDialog();
  const opened=$('rename-dialog').open;
  $('rename-open').disabled=!activeSelection();
  $('rename-current-check').hidden=!activeSelection()||opened||!state||state.status!=='delivery_unknown';
  $('rename-current-check').disabled=Boolean(state&&state.inFlight);
  if(!opened||!state)return;
  $('rename-title').disabled=state.inFlight||['delivery_unknown','accepted'].includes(state.status);
  $('rename-save').disabled=$('rename-title').disabled;
  $('rename-check').hidden=state.status!=='delivery_unknown';
  $('rename-check').disabled=state.inFlight;
  const text=state.status==='accepted'&&Date.now()>=(state.acceptedUntil||0)?'':state.message;
  if($('rename-status').textContent!==text)$('rename-status').textContent=text;
}
function openRenameDialog(){
  if(!activeSelection())return;
  const key=currentSessionKey();let state=renameState(key);
  if(state.status==='accepted'){state={draft:selectedSession.title,status:'draft',operation:null,inFlight:false,message:''};renames.set(key,state);}
  renameDialogScope={project:selectedProject,sid:selectedSession.sid,generation:selectionGeneration};
  $('rename-title').value=state.draft;$('rename-dialog').show();syncRenameControls();
}
function trimRenameTitle(raw){return raw.replace(/^\p{White_Space}+|\p{White_Space}+$/gu,'');}
function normalizedRenameTitle(raw){
  const encoder=new TextEncoder();
  // Reject invalid UTF-16 rather than silently UTF-8 encoding replacement characters.
  if(/[\u0000-\u001f\u007f-\u009f]/u.test(raw)||[...raw].some(c=>c.length===1&&c.charCodeAt(0)>=0xd800&&c.charCodeAt(0)<=0xdfff)||[...raw].length>2048||encoder.encode(raw).length>8192)return null;
  const title=trimRenameTitle(raw);return title&&[...title].length<=160&&encoder.encode(title).length<=1024?title:null;
}
function confirmedRename(state,data,operation,generation){
  if(!data||data.operation_id!==operation.operation_id||data.status!=='accepted'||typeof data.title!=='string'||!trimRenameTitle(data.title)||[...data.title].length>500)return false;
  if(!activeSelection(operation.project,operation.sid,generation))return false;
  state.status='accepted';state.message='Название сессии сохранено.';state.acceptedUntil=Date.now()+5000;
  selectedSession.title=data.title;$('chat-title').textContent=data.title;
  sessionRows=sessionRows.map(row=>row&&row.sid===operation.sid?{...row,title:data.title}:row);renderSessions();
  projectSummaries.delete(operation.project);renderProjects();
  if(renameStatusTimer!==null)clearTimeout(renameStatusTimer);
  if($('rename-dialog').open)renameStatusTimer=setTimeout(()=>{renameStatusTimer=null;syncRenameControls();},5000);
  return true;
}
async function submitRename(event){
  event.preventDefault();if(!activeSelection()||!renameDialogScope)return;
  const key=currentSessionKey(),state=renameState(key);if(state.inFlight||['delivery_unknown','accepted'].includes(state.status))return;
  state.draft=$('rename-title').value;const title=normalizedRenameTitle(state.draft);
  if(title===null){state.message='Введите название от 1 до 160 символов без управляющих символов.';syncRenameControls();return;}
  const operation=Object.freeze({project:selectedProject,sid:selectedSession.sid,operation_id:crypto.randomUUID(),title});
  const generation=selectionGeneration,auth=chatAuthGeneration;state.operation=operation;state.status='pending';state.inFlight=true;state.message='Сохраняем название…';syncRenameControls();
  try{
    const data=await api('/api/session-rename',operation);
    if(auth!==chatAuthGeneration||renames.get(key)!==state)return;
    if(!confirmedRename(state,data,operation,generation)){state.status='delivery_unknown';state.message='Название пока не подтверждено. Проверьте его вручную.';}
  }catch(err){
    if(auth!==chatAuthGeneration||renames.get(key)!==state)return;
    if(activeSelection(operation.project,operation.sid,generation)&&['invalid_request','forbidden','stale'].includes(err.code)){
      state.status='refused';state.message='Название не сохранено. Исправьте ввод или обновите выбранную сессию.';
    }else{state.status='delivery_unknown';state.message='Название пока не подтверждено. Проверьте его вручную.';}
  }finally{state.inFlight=false;if(auth===chatAuthGeneration&&renames.get(key)===state)syncRenameControls();}
}
async function checkRename(){
  if(!activeSelection())return;const key=currentSessionKey(),state=renames.get(key);
  if(!state||state.inFlight||state.status!=='delivery_unknown'||!state.operation)return;
  if(!$('rename-dialog').open)openRenameDialog();
  const operation=state.operation,generation=selectionGeneration,auth=chatAuthGeneration;state.inFlight=true;state.message='Проверяем название…';syncRenameControls();
  try{
    const data=await api(queryPath('/api/session-rename-status',{project:operation.project,sid:operation.sid,operation_id:operation.operation_id}));
    if(auth!==chatAuthGeneration||renames.get(key)!==state)return;
    if(!confirmedRename(state,data,operation,generation)){state.status='delivery_unknown';state.message='Название пока не подтверждено. Повторите ручную проверку.';}
  }catch(_){if(auth===chatAuthGeneration&&renames.get(key)===state){state.status='delivery_unknown';state.message='Проверка недоступна. Повторите ручную проверку названия.';}}
  finally{state.inFlight=false;if(auth===chatAuthGeneration&&renames.get(key)===state)syncRenameControls();}
}

function normalizeHistoryState(key){if(!historyData.has(key))historyData.set(key,{turns:new Map(),outgoing:new Map(),sessionSettings:null,settingsFailure:false,order:[],olderAnchors:[],initialized:false,truncated:false,attention:false,paginationError:'',historyError:'',historyErrorOrigin:null,latestHistoryError:'',windowIds:null,windowOlder:false,pendingLatest:false});return historyData.get(key);}
function validHistoryId(value){return typeof value==='string'&&value.length>0&&value.length<=500;}
function mergeHistory(key,data,olderAnchor){const state=normalizeHistoryState(key);const incoming=Array.isArray(data.turns)?data.turns:[];const chronological=incoming.slice().reverse().filter(turn=>turn&&validHistoryId(turn.id));const incomingIds=new Set(chronological.map(turn=>turn.id));const existingIds=new Set(state.order);const hadOverlap=chronological.some(turn=>existingIds.has(turn.id));for(const turn of chronological){const previous=state.turns.get(turn.id);const itemMap=new Map();for(const item of (previous&&previous.items)||[])if(validHistoryId(item&&item.id))itemMap.set(item.id,item);for(const item of (Array.isArray(turn.items)?turn.items:[])){if(item&&validHistoryId(item.id)&&(!olderAnchor||!itemMap.has(item.id)))itemMap.set(item.id,item);}state.turns.set(turn.id,{...(olderAnchor&&previous?previous:turn),items:[...itemMap.values()]});}
  const ids=chronological.map(turn=>turn.id).filter((id,i,a)=>a.indexOf(id)===i);if(olderAnchor){const anchorIndex=state.olderAnchors.indexOf(olderAnchor);const originalOrder=state.order;const overlapId=ids.find(id=>existingIds.has(id));const boundaryId=overlapId||olderAnchor.afterId;const boundaryIndex=boundaryId===null?-1:originalOrder.indexOf(boundaryId);const insertAt=boundaryIndex<0?0:originalOrder.slice(0,boundaryIndex).filter(id=>!incomingIds.has(id)).length;state.order=originalOrder.filter(id=>!incomingIds.has(id));state.order.splice(insertAt,0,...ids.filter(id=>!state.order.includes(id)));if(anchorIndex>=0){if(data.next_cursor){if(olderAnchor.seen.has(data.next_cursor)){olderAnchor.error=true;state.paginationError='Продолжение истории недоступно: сервер повторил cursor.';}else{state.olderAnchors[anchorIndex]={cursor:data.next_cursor,afterId:ids[0]||olderAnchor.afterId,seen:new Set([...olderAnchor.seen,data.next_cursor]),error:false};}}else state.olderAnchors.splice(anchorIndex,1);}}else{state.order=[...state.order.filter(id=>!incomingIds.has(id)),...ids];if(!state.initialized){state.olderAnchors=[];if(data.next_cursor)state.olderAnchors.push({cursor:data.next_cursor,afterId:ids[0]||state.order[0]||null,seen:new Set([data.next_cursor]),error:false});state.initialized=true;}else if(data.next_cursor&&!hadOverlap&&!state.olderAnchors.some(anchor=>anchor.cursor===data.next_cursor)){state.olderAnchors.push({cursor:data.next_cursor,afterId:ids[0]||state.order[0]||null,seen:new Set([data.next_cursor]),error:false});}}
  state.paginationError=state.olderAnchors.some(anchor=>anchor.error)?'Продолжение истории недоступно: сервер повторил cursor.':'';
  // Only authoritative user correlation replaces a local record. Remap a visible
  // local window slot so reconciliation cannot hide the canonical replacement.
  for(const turnId of state.order)for(const item of state.turns.get(turnId)?.items||[]){
    if(item?.role!=='user'||typeof item.text!=='string'||!validHistoryId(item.id)||typeof item.client_id!=='string'||!UUID_RE.test(item.client_id)||!state.outgoing.has(item.client_id))continue;
    const localKey=JSON.stringify(['local-outgoing',item.client_id]),canonicalKey=JSON.stringify([turnId,item.id]);
    if(state.windowIds)state.windowIds=state.windowIds.map(id=>id===localKey?canonicalKey:id);
    state.outgoing.delete(item.client_id);
  }
  state.truncated=state.truncated||data.truncated===true;state.attention=data.needs_native_attention===true;for(const receipt of Array.isArray(data.recent_sends)?data.recent_sends:[])applyReceipt(key,receipt);return state;}
function reconcileHistoryCorrelations(state,known,scrollDecision){
for(const entry of historyItems(state)){
        if(entry.local||entry.item.role!=='user'||typeof entry.item.client_id!=='string'||!UUID_RE.test(entry.item.client_id))continue;
        const localKey=JSON.stringify(['local-outgoing',entry.item.client_id]);
        if(known.has(localKey))known.add(entry.key);
        if(scrollDecision?.kind==='anchor'&&scrollDecision.turnId==='local-outgoing'&&scrollDecision.itemId===entry.item.client_id)
          scrollDecision={...scrollDecision,turnId:entry.turnId,itemId:entry.item.id};
      }
  return scrollDecision;
}
function scrollScopeMatches(project,sid,generation){return activeSelection(project,sid,generation)&&document.visibilityState==='visible';}
function scrollToDocumentBottom(){showLatestHistory();pageReaderScope=null;clearHistoryScrollSlack();const root=document.documentElement;const body=document.body;const height=Math.max(root?root.scrollHeight:0,body?body.scrollHeight:0);window.scrollTo(0,Math.max(0,height-window.innerHeight));}
function documentMaxScroll(){const root=document.documentElement;const body=document.body;return Math.max(0,Math.max(root?root.scrollHeight:0,body?body.scrollHeight:0)-window.innerHeight);}
function markdownTextNodes(article){
  const content=article.querySelector('.markdown');if(!content)return null;
  const walker=document.createTreeWalker(content,NodeFilter.SHOW_TEXT),entries=[];let text='',part;
  while((part=walker.nextNode())){if(text.length+part.length>8000)return null;entries.push({node:part,start:text.length});text+=part.textContent;}
  return {entries,text};
}
function markdownCharRange(part,offset){const range=document.createRange();range.setStart(part,offset);range.setEnd(part,offset+1);return range;}
function captureMarkdownAnchor(article){
  const content=markdownTextNodes(article);if(!content)return null;
  for(const entry of content.entries){
    const part=entry.node;if(!part.length||!part.textContent.trim())continue;
    const whole=document.createRange();whole.selectNodeContents(part);const rect=whole.getBoundingClientRect();
    if(rect.bottom<=0||rect.top>=window.innerHeight)continue;
    // Text-node character positions follow their rendered lines. Find the first
    // visible line without measuring every character of a long paragraph/code.
    let low=0,high=part.length-1;
    while(low<high){const mid=Math.floor((low+high)/2);if(markdownCharRange(part,mid).getBoundingClientRect().bottom<=0)low=mid+1;else high=mid;}
    for(let offset=low;offset<Math.min(part.length,low+64);offset++){
      if(/\s/.test(part.textContent[offset]))continue;
      const point=markdownCharRange(part,offset).getBoundingClientRect();if(point.bottom<=0||point.top>=window.innerHeight)continue;
      const index=entry.start+offset,context=content.text.slice(index,index+48);let occurrence=0,previous=-1;
      while((previous=content.text.indexOf(context,previous+1))>=0&&previous<index)occurrence++;
      return {context,occurrence,top:point.top,text:content.text,index};
    }
  }
  return null;
}
function resolveMarkdownAnchor(article,anchor){
  if(!anchor)return null;const content=markdownTextNodes(article);if(!content)return null;
  // A wholly unchanged prefix preserves offsets during append. Otherwise map
  // the original glyph in the unchanged suffix before context lookup, so an
  // inserted duplicate passage does not select its new first copy.
  const old=anchor.text,fresh=content.text;let suffix=0,prefix=0,index=-1;
  if(fresh.startsWith(old))index=anchor.index;
  else{
    while(suffix<Math.min(old.length,fresh.length)&&old[old.length-1-suffix]===fresh[fresh.length-1-suffix])suffix++;
    if(anchor.index>=old.length-suffix)index=fresh.length-old.length+anchor.index;
    else{
      while(prefix<Math.min(old.length,fresh.length)&&old[prefix]===fresh[prefix])prefix++;
      if(anchor.index<prefix)index=anchor.index;
    }
  }
  if(index<0)for(let i=0;i<=anchor.occurrence;i++){index=fresh.indexOf(anchor.context,index+1);if(index<0)return null;}
  const entry=content.entries.find(entry=>index>=entry.start&&index<entry.start+entry.node.length);
  return entry?markdownCharRange(entry.node,index-entry.start):null;
}
function captureHistoryScroll(project,sid,generation,older){if(!scrollScopeMatches(project,sid,generation))return null;const initial=initialScrollTarget&&initialScrollTarget.project===project&&initialScrollTarget.sid===sid&&initialScrollTarget.generation===generation;if(initial&&!older)return {kind:'bottom',initial:true};const distance=documentMaxScroll()-window.scrollY;const pinned=pinnedHistoryScope&&pinnedHistoryScope.project===project&&pinnedHistoryScope.sid===sid&&pinnedHistoryScope.generation===generation&&historyScrollSlack>0;const pageReader=pageReaderScope&&pageReaderScope.project===project&&pageReaderScope.sid===sid&&pageReaderScope.generation===generation;if(pageReader){pageReaderScope.returnUntil=0;historyScrollbarStartY=null;}if(!older&&!pageReader&&(!pinned&&distance<=80||pinned&&historyScrollIntent&&distance<=80)){historyScrollIntent=false;return {kind:'bottom'};}historyScrollIntent=false;for(const article of $('chat-items').querySelectorAll('article.chat-message')){const rect=article.getBoundingClientRect();if(rect.bottom>0&&rect.top<window.innerHeight)return {kind:'anchor',turnId:article.dataset.turnId,itemId:article.dataset.itemId,top:rect.top,y:window.scrollY,inner:captureMarkdownAnchor(article)};}return {kind:'position',y:window.scrollY};}
function restoreHistoryScroll(decision,project,sid,generation){if(!decision||!scrollScopeMatches(project,sid,generation))return;if(decision.kind==='bottom'){scrollToDocumentBottom();if(decision.initial)initialScrollTarget=null;return;}const findAnchor=()=>decision.kind==='anchor'?[...$('chat-items').querySelectorAll('article.chat-message')].find(article=>article.dataset.turnId===decision.turnId&&article.dataset.itemId===decision.itemId):null;const article=findAnchor();const inner=article&&resolveMarkdownAnchor(article,decision.inner);const anchor=inner||article;const anchorTop=inner?decision.inner.top:decision.top;let target=anchor?Math.max(0,window.scrollY+anchor.getBoundingClientRect().top-anchorTop):Math.max(0,decision.y);const root=document.documentElement;const body=document.body;let maxHeight=Math.max(root?root.scrollHeight:0,body?body.scrollHeight:0);let naturalMax=Math.max(0,maxHeight-window.innerHeight-historyScrollSlack);setHistoryScrollSlack(Math.max(0,target-naturalMax));window.scrollTo(0,target);for(let i=0;i<3&&anchor;i++){const difference=anchor.getBoundingClientRect().top-anchorTop;if(Math.abs(difference)<=0.5)break;target=Math.max(0,window.scrollY+difference);maxHeight=Math.max(root?root.scrollHeight:0,body?body.scrollHeight:0);const maxScroll=Math.max(0,maxHeight-window.innerHeight);if(target>maxScroll&&historyScrollSlack<window.innerHeight)setHistoryScrollSlack(historyScrollSlack+Math.min(window.innerHeight-historyScrollSlack,target-maxScroll+1));window.scrollTo(0,target);}if(historyScrollSlack){pinnedHistoryScope={project,sid,generation};historyScrollIntent=false;}else pinnedHistoryScope=null;}
// Keep latest failure provenance until its own explicit retry succeeds.
function historyErrorText(state){return [...new Set([state.latestHistoryError,state.historyError,state.paginationError])].filter(Boolean).join(' ');}
async function loadHistory(older=false,manual=false){
  if(!selectedSession||!selectedProject)return;
  if(manual&&!older){stopLive(false);const fresh=normalizeHistoryState(currentSessionKey());fresh.liveGap=false;fresh.latestWindowIds=[];}
  const project=selectedProject,sid=selectedSession.sid,key=chatKey(project,sid),generation=selectionGeneration;
  const existing=historyFlights.get(key);
  if(existing){if(existing.generation===generation)return existing.promise;existing.controller.abort();}
  const state=normalizeHistoryState(key);
  if(older&&hasEarlierHistory(state)){
    let decision=captureHistoryScroll(project,sid,generation,true);
    decision=openOlderHistory(state,decision);renderHistory(key);syncCurrentSessionControls();
    restoreHistoryScroll(decision,project,sid,generation);return;
  }
  if(state.historyError&&!manual&&(!older||state.historyErrorOrigin!=='latest'))return;
  const anchor=older?[...state.olderAnchors].reverse().find(candidate=>!candidate.error):null;
  if(older&&!anchor)return;
  const cursor=anchor?anchor.cursor:null,path=queryPath('/api/session-history',{project,sid,cursor});
  const controller=new AbortController(),settingsRequestStarted={perf:performance.now(),wall:Date.now()};
  const capturedEpoch=state.liveEpoch,capturedLiveRevision=state.historyRevision;
  let timeout;
  const deadline=new Promise((_,reject)=>{timeout=setTimeout(()=>{controller.abort();reject(new Error('Время загрузки переписки истекло. Повторите загрузку.'));},15000);});
  if(!state.initialized||manual)$('history-status').textContent='Загружаем переписку…';
  const flight={generation,controller,promise:null};
  historyFlights.set(key,flight);
  const promise=(async()=>{
    try{
      // The deadline includes JSON consumption, and only cancels this browser GET.
      const data=await Promise.race([api(path,undefined,controller.signal,()=>activeSelection(project,sid,generation)),deadline]);
      if(!activeSelection(project,sid,generation)||historyFlights.get(key)!==flight||older&&capturedEpoch!==state.liveEpoch||!older&&capturedLiveRevision!==state.historyRevision)return;
      if(Object.hasOwn(data,'history_state')){
        const keys=['history_state','reason','recent_sends'];if(Object.hasOwn(data,'session_settings'))keys.push('session_settings');if(Object.hasOwn(data,'needs_native_attention'))keys.push('needs_native_attention');
        if(older||!exactFields(data,keys)||data.history_state!=='unavailable'||data.reason!=='unavailable'||Object.hasOwn(data,'needs_native_attention')&&data.needs_native_attention!==true||!Array.isArray(data.recent_sends)||data.recent_sends.length>8||!data.recent_sends.every(row=>exactFields(row,['status','message_id','turn_id'])&&UUID_RE.test(row.message_id)&&(['accepted','delivery_unknown','rejected'].includes(row.status))&&(row.status==='accepted'?typeof row.turn_id==='string'&&row.turn_id.length>0&&Array.from(row.turn_id).length<=500:row.turn_id===null)))throw new Error(messages.unavailable);
        const snapshot=sessionSettingsSnapshot(data.session_settings,settingsRequestStarted);state.sessionSettings=snapshot?{...snapshot,selection:generation}:null;state.liveProjection=settingsProjection(data.session_settings);state.settingsFailure=false;
        confirmProjectSelection(generation);state.confirmedOrigin=true;state.unavailable=true;state.attention=data.needs_native_attention===true;
        state.latestHistoryError='История пока недоступна';state.historyError=state.latestHistoryError;state.historyErrorOrigin='latest';
        for(const receipt of data.recent_sends)applyReceipt(key,receipt);
        renderHistory(key);$('history-status').textContent=state.historyError;syncCurrentSessionControls();return;
      }
      if(!older){const snapshot=sessionSettingsSnapshot(data.session_settings,settingsRequestStarted);state.sessionSettings=snapshot?{...snapshot,selection:generation}:null;state.liveProjection=settingsProjection(data.session_settings);state.settingsFailure=false;}
      state.confirmedOrigin=false;state.unavailable=false;
      let scrollDecision=captureHistoryScroll(project,sid,generation,older);
      const known=new Set(historyItems(state).map(entry=>entry.key));
      const hold=state.windowIds!==null&&(state.windowOlder||focusedHistoryBubble()||scrollDecision&&scrollDecision.kind!=='bottom');
      if(hold&&scrollDecision&&scrollDecision.kind==='bottom')scrollDecision=captureHistoryScroll(project,sid,generation,true);
      mergeHistory(key,data,anchor);
      confirmProjectSelection(generation);
      scrollDecision=reconcileHistoryCorrelations(state,known,scrollDecision);
      if(!older)state.latestHistoryError='';
      state.historyError=state.latestHistoryError;
      state.historyErrorOrigin=state.historyError?'latest':null;
      if(older)scrollDecision=openOlderHistory(state,scrollDecision);
      else if(!hold){state.windowIds=null;state.windowOlder=false;state.pendingLatest=false;}
      else if(historyItems(state).some(entry=>!known.has(entry.key)))state.pendingLatest=true;
      renderHistory(key);
      $('history-status').textContent=historyErrorText(state);
      if(historyFlights.get(key)===flight){historyFlights.delete(key);syncCurrentSessionControls();restoreHistoryScroll(scrollDecision,project,sid,generation);}
    }catch(err){
      if(activeSelection(project,sid,generation)&&historyFlights.get(key)===flight){
        state.historyError=(controller.signal.aborted?'Время загрузки переписки истекло. Повторите загрузку.':chatError(err))+' История и черновик сохранены.';
        state.historyErrorOrigin=older?'older':'latest';
        if(!older){state.latestHistoryError=state.historyError;state.sessionSettings=null;state.settingsFailure=true;}
        $('history-status').textContent=historyErrorText(state);
      }
    }finally{
      clearTimeout(timeout);
      if(historyFlights.get(key)===flight){historyFlights.delete(key);if(activeSelection(project,sid,generation))syncCurrentSessionControls();}
    }
  })();
  flight.promise=promise;if(manual&&!older)promise.then(()=>{if(activeSelection(project,sid,generation)&&liveVisible())startLive();});syncCurrentSessionControls();return promise;
}
// INV-WSESS-20/21: producer item starts are preferred; turn fallbacks are explicit.
function messageTimestamp(item){return ['item','turn'].includes(item.time_precision)&&Number.isInteger(item.timestamp)&&item.timestamp>=0&&item.timestamp<=253402300799?item.timestamp:null;}
function messageAge(timestamp){
  const age=Date.now()/1000-timestamp;
  if(!Number.isFinite(age)||age<0)return 'время неизвестно';
  if(age<60)return 'только что';
  if(age<3600)return Math.floor(age/60)+' мин. назад';
  if(age<86400)return Math.floor(age/3600)+' ч назад';
  return Math.floor(age/86400)+' дн. назад';
}
function messageTime(item){
  const timestamp=messageTimestamp(item);
  if(timestamp===null)return node('span','время неизвестно','message-time-unknown');
  const date=new Date(timestamp*1000);
  const exact=new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(date)+(item.time_precision==='item'?' — начало сообщения':' — начало хода');
  const control=node('button',undefined,'message-time');control.type='button';
  control.setAttribute('aria-label',exact);control.setAttribute('aria-expanded','false');
  const time=node('time',messageAge(timestamp));time.dateTime=date.toISOString();time.dataset.timestamp=String(timestamp);
  if(item.time_precision==='turn')control.append(node('span','Ход начат','message-time-precision'));
  control.append(time,node('span',exact,'message-time-detail'));
  control.addEventListener('click',()=>control.setAttribute('aria-expanded',String(control.getAttribute('aria-expanded')!=='true')));
  return control;
}
function stopMessageAges(){if(messageAgeTimer!==null){clearInterval(messageAgeTimer);messageAgeTimer=null;}}
function messageAgesActive(){return Boolean(csrf&&currentTab==='sessions'&&selectedSession&&document.visibilityState==='visible'&&!$('workspace').hidden&&!$('chat-panel').hidden);}
function projectAgesActive(){return Boolean(csrf&&currentTab==='sessions'&&document.visibilityState==='visible'&&!$('workspace').hidden&&$('project-cloud').querySelector('time[data-project-timestamp]'));}
function updateMessageAges(){
  if(messageAgesActive())for(const time of $('chat-items').querySelectorAll('time[data-timestamp]')){
    const text=messageAge(Number(time.dataset.timestamp));
    if(time.textContent!==text)time.textContent=text;
  }
  if(projectAgesActive())for(const time of $('project-cloud').querySelectorAll('time[data-project-timestamp]')){
    const text=projectAge(Number(time.dataset.projectTimestamp));
    if(time.textContent!==text)time.textContent=text;
  }
}
function syncMessageAges(){
  stopMessageAges();
  if(messageAgesActive()||projectAgesActive()){updateMessageAges();messageAgeTimer=setInterval(updateMessageAges,60000);}
}
// INV-WSESS-22/23: bound DOM only; keep loaded cache and opaque gap cursors intact.
const HISTORY_WINDOW_LIMIT=100;
function historyItems(state){
  const entries=[];
  for(const turnId of state.order){
    const turn=state.turns.get(turnId);if(!turn)continue;
    for(const item of turn.items||[])if(item&&typeof item.text==='string'&&['user','assistant'].includes(item.role))
      entries.push({key:JSON.stringify([turnId,item.id]),turnId,turn,item});
  }
  for(const attempt of state.outgoing.values()){
    const turnId='local-outgoing',item={id:attempt.id,role:'user',text:attempt.text,
      timestamp:null,time_precision:'unknown',truncated:false,outgoing_status:attempt.status};
    entries.push({key:JSON.stringify([turnId,item.id]),turnId,turn:{status:'local'},item,local:true});
  }
  return entries;
}
function hasEarlierHistory(state){
  if(!state.windowIds||!state.windowIds.length)return false;
  return historyItems(state).findIndex(entry=>entry.key===state.windowIds[0])>0;
}
function openOlderHistory(state,decision){
  const entries=historyItems(state),first=state.windowIds&&state.windowIds[0];
  state.windowOlder=true;
  if(entries.length<=HISTORY_WINDOW_LIMIT){state.windowIds=entries.map(entry=>entry.key);return decision;}
  const firstIndex=entries.findIndex(entry=>entry.key===first);
  // Empty/repeated pages must leave the readable window intact.
  if(first&&firstIndex<=0)return decision;
  const anchor=decision&&decision.kind==='anchor'?JSON.stringify([decision.turnId,decision.itemId]):first;
  let end=entries.findIndex(entry=>entry.key===anchor);
  if(end<0)end=entries.findIndex(entry=>entry.key===first);
  if(end<0)end=entries.length-1;
  // Keep the first fully readable neighbor when the captured bubble is clipped
  // above the viewport; both reader anchors overlap, never the whole old window.
  if(decision&&decision.kind==='anchor'&&decision.top<0){
    const readable=[...$('chat-items').querySelectorAll('article.chat-message')].find(article=>{const rect=article.getBoundingClientRect();return rect.top>=0&&rect.top<window.innerHeight;});
    const next=readable&&entries.findIndex(entry=>entry.key===JSON.stringify([readable.dataset.turnId,readable.dataset.itemId]));
    if(next===end+1)end=next;
  }
  // Explicit Older must progress even when the reader is at the window's end.
  // Use the oldest previous boundary as overlap, keeping chronology continuous.
  if(firstIndex>0&&Math.max(0,end-HISTORY_WINDOW_LIMIT+1)>=firstIndex){
    end=firstIndex;
    const boundary=entries[end];
    decision={...(decision||{top:0,y:window.scrollY}),kind:'anchor',
      turnId:boundary.turnId,itemId:boundary.item.id,inner:null};
  }
  state.windowIds=entries.slice(Math.max(0,end-HISTORY_WINDOW_LIMIT+1),end+1).map(entry=>entry.key);
  return decision;
}
function focusedHistoryBubble(){
  const article=document.activeElement&&document.activeElement.closest('article.chat-message');
  if(article&&$('chat-items').contains(article))return article;
  const selection=window.getSelection();
  if(selection&&!selection.isCollapsed){const parent=selection.anchorNode&&selection.anchorNode.parentElement;const selected=parent&&parent.closest('article.chat-message');if(selected&&$('chat-items').contains(selected))return selected;}
  return null;
}
function showLatestHistory(){
  const key=currentSessionKey();if(!key||!activeSelection())return;
  const state=normalizeHistoryState(key),ids=historyItems(state).slice(-HISTORY_WINDOW_LIMIT).map(entry=>entry.key);
  const changed=state.pendingLatest||!state.windowIds||ids.length!==state.windowIds.length||ids.some((id,index)=>id!==state.windowIds[index]);
  state.windowIds=ids;state.windowOlder=false;state.pendingLatest=false;
  if(changed)renderHistory(key,true);else $('history-new').hidden=true;
  syncCurrentSessionControls();
}
function reconcileHistoryChildren(parent,children){
  const keep=new Set(children);
  for(const child of [...parent.childNodes])if(!keep.has(child))child.remove();
  children.forEach((child,index)=>{if(parent.childNodes[index]!==child)parent.insertBefore(child,parent.childNodes[index]||null);});
}
function localOutgoingStatus(status){return status==='accepted'?'Принято':status==='rejected'?'Не принято':status==='delivery_unknown'?'Доставка неизвестна':'Отправляется';}
// A receipt belongs to its immutable project/thread/auth scope even when the
// operator has left and returned before the ACK. Update only passive labels;
// an older selection callback must not rebuild the current feed or move it.
function syncLocalOutgoingStatuses(key){
  if(key!==currentSessionKey()||!activeSelection())return;
  const outgoing=historyData.get(key)?.outgoing;
  for(const article of $('chat-items').querySelectorAll('[data-local-outgoing="true"]')){
    const attempt=outgoing?.get(article.dataset.sendId),label=article.querySelector('.outgoing-status');
    if(!attempt||!label)continue;
    label.textContent=localOutgoingStatus(attempt.status);
    article.historyItem={...article.historyItem,outgoing_status:attempt.status};
  }
}
function historyArticle(entry,existing,force){
  const article=existing||node('article',undefined,'chat-message '+(entry.item.role==='user'?'from-user':'from-assistant'));
  const item=entry.item,old=article.historyItem;
  const reconciled=existing?.dataset.localOutgoing==='true'&&!entry.local;
  if(reconciled){
    delete article.dataset.localOutgoing;delete article.dataset.sendId;
    article.dataset.turnId=entry.turnId;article.dataset.itemId=item.id;
    article.querySelector('.outgoing-status')?.remove();
    if(old.role===item.role&&old.text===item.text&&old.truncated===item.truncated){
      // Same canonical-safe content keeps its links and text selection intact.
      const heading=node('div',undefined,'message-heading');heading.append(node('h3','Вы'),messageTime(item));
      article.querySelector('.message-heading').replaceWith(heading);
      article.historyItem=item;return article;
    }
  }
  if(entry.local){article.dataset.localOutgoing='true';article.dataset.sendId=item.id;}
  const changed=!old||['role','text','truncated','timestamp','time_precision','outgoing_status'].some(field=>old[field]!==item[field]);
  if(changed){
    if(existing&&!reconciled&&!force&&focusedHistoryBubble()===article){
      // Receipt transitions can update the passive label without rebuilding a
      // focused message/link or disturbing its text selection.
      if(entry.local&&old.text===item.text){
        const status=article.querySelector('.outgoing-status');
        if(status)status.textContent=localOutgoingStatus(item.outgoing_status);
        article.historyItem=item;return article;
      }
      normalizeHistoryState(currentSessionKey()).pendingLatest=true;return article;
    }
    article.dataset.turnId=entry.turnId;article.dataset.itemId=item.id;
    const heading=node('div',undefined,'message-heading');heading.append(node('h3',item.role==='user'?'Вы':'Codex'),messageTime(item));
    const children=[heading,renderMarkdown(item.text)];
    if(entry.local)children.push(node('span',localOutgoingStatus(item.outgoing_status),'meta outgoing-status'));
    if(item.truncated===true)children.push(node('span','Сообщение сокращено','meta'));
    article.replaceChildren(...children);article.historyItem=item;
  }
  return article;
}
function renderHistory(key,force=false){
  const state=normalizeHistoryState(key),list=$('chat-items'),all=historyItems(state);
  const focusBefore=document.activeElement,focusedLocal=focusBefore?.closest('[data-local-outgoing="true"]');
  if(state.windowIds===null)state.windowIds=all.slice(-HISTORY_WINDOW_LIMIT).map(entry=>entry.key);
  const wanted=new Set(state.windowIds),visible=all.filter(entry=>wanted.has(entry.key)).slice(-HISTORY_WINDOW_LIMIT);
  const articles=new Map([...list.querySelectorAll('article.chat-message')].map(article=>[JSON.stringify([article.dataset.turnId,article.dataset.itemId]),article]));
  const groups=new Map([...list.querySelectorAll('li.turn')].map(group=>[group.dataset.turnId,group]));
  const children=[],contents=new Map();
  for(const entry of visible){
    let group=contents.get(entry.turnId);
    if(!group){
      const element=groups.get(entry.turnId)||node('li',undefined,'turn');element.dataset.turnId=entry.turnId;
      const heading=element.querySelector('.turn-status')||node('p',undefined,'turn-status');
      const text=entry.local?'Исходящие сообщения':'Ход: '+statusLabel(entry.turn.status);if(heading.textContent!==text)heading.textContent=text;
      group={element,children:[heading]};contents.set(entry.turnId,group);children.push(element);
    }
    const localKey=!entry.local&&entry.item.role==='user'&&typeof entry.item.client_id==='string'&&UUID_RE.test(entry.item.client_id)
      ?JSON.stringify(['local-outgoing',entry.item.client_id]):null;
    const existing=articles.get(entry.key)||(localKey&&articles.get(localKey));
    if(localKey&&existing)articles.delete(localKey);
    group.children.push(historyArticle(entry,existing,force));
  }
  for(const group of contents.values())reconcileHistoryChildren(group.element,group.children);
  if(!visible.length&&!state.unavailable)children.push(node('li','Пока нет отображаемых текстовых сообщений.','meta'));
  if(historyScrollSlack&&historyScrollSpacer)children.push(historyScrollSpacer);
  reconcileHistoryChildren(list,children);
  // Moving a preserved article between turn groups can itself blur a link.
  // Restore only the same still-present safe node, or the canonical article.
  if(focusedLocal&&list.contains(focusedLocal)&&focusedLocal.dataset.localOutgoing!=='true'){
    const focus=focusedLocal.contains(focusBefore)?focusBefore:focusedLocal;
    if(focus===focusedLocal)focus.tabIndex=-1;
    focus.focus({preventScroll:true});
  }
  syncMessageAges();
  if(historyScrollSlack)setHistoryScrollSlack(historyScrollSlack);
  $('history-truncated').textContent=state.liveGap?'Показано последнее окно. Возможен пропуск сообщений':'История показана не полностью. Некоторые сообщения могут отсутствовать или быть сокращены.';
  $('history-truncated').hidden=!(state.liveGap||state.truncated||all.some(entry=>entry.item.truncated===true));
  $('history-older').hidden=state.unavailable||!state.initialized;
  $('history-older').disabled=!(hasEarlierHistory(state)||state.olderAnchors.some(anchor=>!anchor.error));
  $('history-new').hidden=!state.pendingLatest;
  $('native-attention').hidden=!(state.attention||(selectedSession&&selectedSession.needs));renderReceipts(key);
}

function statusText(status){return status==='accepted'?'Сообщение принято Codex; работа может продолжаться.':status==='rejected'?'Codex отклонил сообщение; черновик сохранён.':status==='delivery_unknown'?'Доставка неизвестна. Проверьте статус вручную; отправка не повторяется автоматически.':status==='sending'?'Отправляем сообщение…':'Статус сообщения недоступен.';}
function renderCurrentSendStatus(){if(acceptedStatusTimer!==null){clearTimeout(acceptedStatusTimer);acceptedStatusTimer=null;}const key=currentSessionKey(),attempt=key&&latestAttempts.get(key);let slot=$('send-status');if(attempt&&attempt.statusNode&&attempt.statusNode!==slot){attempt.statusNode.setAttribute('aria-live',attempt.status==='accepted'?'off':'polite');slot.replaceWith(attempt.statusNode);slot=attempt.statusNode;}else if(attempt&&!attempt.statusNode){attempt.statusNode=slot;slot.setAttribute('aria-live','polite');}else if(!attempt&&slot.textContent){const empty=slot.cloneNode(false);empty.setAttribute('aria-live','polite');slot.replaceWith(empty);slot=empty;}$('send-check').hidden=!(attempt&&attempt.status==='delivery_unknown');$('send-check').disabled=Boolean(attempt&&statusChecks.has(key+'\u0000'+attempt.id));let text=attempt?(attempt.localError||statusText(attempt.status)):'';if(attempt&&attempt.status==='accepted'){const remaining=(attempt.acceptedUntil||0)-Date.now();if(remaining<=0)text='';else{const project=selectedProject,sid=selectedSession.sid,generation=selectionGeneration,id=attempt.id;acceptedStatusTimer=setTimeout(()=>{acceptedStatusTimer=null;if(currentSessionKey()===key&&selectionGeneration===generation&&selectedSession&&selectedSession.sid===sid&&selectedProject===project&&latestAttempts.get(key)?.id===id)renderCurrentSendStatus();},remaining);}}if($('send-status').textContent!==text)$('send-status').textContent=text;}
function renderReceipts(key=currentSessionKey()){const list=$('receipt-list');if(!list||!selectedSession||key!==currentSessionKey())return;const open=list.querySelector('details')?.open||false;const records=[...ensureReceipts(key).entries()].filter(([,record])=>['sending','delivery_unknown','rejected'].includes(record.status));list.replaceChildren();if(!records.length)return;const details=node('details');details.open=open;details.append(node('summary','Проблемы доставки ('+records.length+')'));for(const [id,record] of records.reverse()){const row=node('div',undefined,'receipt-row');row.append(node('span',record.checkError||statusText(record.status),'receipt-label'));if(record.status==='delivery_unknown'){const check=node('button','Проверить доставку','secondary');check.type='button';check.disabled=statusChecks.has(key+'\u0000'+id);check.addEventListener('click',()=>checkDelivery(key,id));row.append(check);}details.append(row);}list.append(details);}

function hasUnknown(key){return [...ensureReceipts(key).values()].some(entry=>entry.status==='delivery_unknown');}
// applyReceipt updates passive outgoing labels. A delivery check must not
// flush deferred history changes or disturb the current reader anchor.
async function checkDelivery(key,id){if(statusChecks.has(key+'\u0000'+id))return;const [project,sid]=key.split('\u0000');if(project!==selectedProject||!selectedSession||sid!==selectedSession.sid)return;const generation=selectionGeneration,mark=key+'\u0000'+id;statusChecks.add(mark);renderCurrentSendStatus();renderReceipts(key);try{const data=await api(queryPath('/api/session-send-status',{project,sid,message_id:id}));if(!activeSelection(project,sid,generation))return;applyReceipt(key,data);const record=ensureReceipts(key).get(id);if(record)delete record.checkError;const attempt=latestAttempts.get(key);if(attempt&&attempt.id===id)delete attempt.localError;renderCurrentSendStatus();renderReceipts(key);}catch(err){if(activeSelection(project,sid,generation)){const message=err.code==='stale'?'Эта отправка больше недоступна для проверки. Черновик сохранён.':chatError(err)+' Повторите ручную проверку.';const record=ensureReceipts(key).get(id);if(record&&!['accepted','rejected'].includes(record.status))record.checkError=message;const attempt=latestAttempts.get(key);if(attempt&&attempt.id===id&&!['accepted','rejected'].includes(attempt.status))attempt.localError=message;}}finally{statusChecks.delete(mark);if(activeSelection(project,sid,generation)){syncCurrentSessionControls();renderReceipts(key);}}}
function applyReceipt(key,data){if(!data||!['sending','accepted','delivery_unknown','rejected'].includes(data.status)||!UUID_RE.test(data.message_id||''))return;const id=data.message_id,map=ensureReceipts(key),existing=map.get(id),attempt=latestAttempts.get(key);const outgoing=historyData.get(key)?.outgoing.get(id);const terminal=existing&&['accepted','rejected'].includes(existing.status)?existing:attempt&&attempt.id===id&&['accepted','rejected'].includes(attempt.status)?{status:attempt.status,turn_id:existing&&existing.turn_id||null}:null;if(terminal){if(outgoing)outgoing.status=terminal.status;map.set(id,terminal);if(attempt&&attempt.id===id)attempt.status=terminal.status;syncLocalOutgoingStatuses(key);return;}if(data.status==='sending'&&existing&&existing.status==='delivery_unknown')return;const record={status:data.status,turn_id:data.turn_id||null};if(existing?.checkError&&data.status==='delivery_unknown')record.checkError=existing.checkError;map.set(id,record);if(outgoing&&outgoing!==attempt)outgoing.status=record.status;if(attempt&&attempt.id===id){if(data.status==='accepted'&&attempt.status!=='accepted'&&attempt.text!==null)attempt.acceptedUntil=Date.now()+5000;attempt.status=data.status;if(!record.checkError)delete attempt.localError;}syncLocalOutgoingStatuses(key);}
async function submitMessage(event){event.preventDefault();if(!selectedSession||!selectedProject)return;const project=selectedProject,sid=selectedSession.sid,key=chatKey(project,sid),generation=selectionGeneration,auth=chatAuthGeneration,text=$('chat-draft').value;if(!text.trim()){$('send-status').textContent='Напишите сообщение перед отправкой.';return;}if(sendsInFlight.has(key))return;if(hasUnknown(key)){const attempt=latestAttempts.get(key);$('send-status').textContent=attempt&&attempt.text===text?'Для этой попытки уже сохранён ID. Проверьте доставку вручную.':'Сначала проверьте неизвестную доставку. Новый текст пока не отправлен.';renderReceipts(key);return;}const state=modelDraft(key);if(!explicitModelReady(key)){$('send-status').textContent='Выберите поддерживаемый уровень размышления или обновите каталог; черновик сохранён.';syncCurrentSessionControls();return;}const selection=state.modelId?Object.freeze({catalog_id:state.catalog.catalog_id,model_id:state.modelId,effort:state.effort}):null;let attempt=latestAttempts.get(key);if(!attempt||attempt.text!==text||['accepted','rejected'].includes(attempt.status)){attempt={id:crypto.randomUUID(),text,status:'sending',selection,selectionLabel:state.label,context:Object.freeze({project,sid,generation,auth})};latestAttempts.set(key,attempt);normalizeHistoryState(key).outgoing.set(attempt.id,attempt);ensureReceipts(key).set(attempt.id,{status:'sending',turn_id:null});}else if(attempt.status==='delivery_unknown'){$('send-status').textContent='Проверьте доставку вручную; повторная отправка отключена.';return;}else{attempt.status='sending';}
  sendsInFlight.add(key);renderHistory(key);syncCurrentSessionControls();$('send-status').textContent='Отправляем сообщение…';renderReceipts(key);if(scrollScopeMatches(project,sid,generation))scrollToDocumentBottom();try{let result;try{result=await api('/api/session-send',{project,sid,message_id:attempt.id,text:attempt.text,...(attempt.selection?{selection:attempt.selection}:{})});}catch(err){if(!csrf||chatAuthGeneration!==auth)return;if(err.data&&['accepted','rejected','delivery_unknown'].includes(err.data.status))result=err.data;else if(['invalid_request','forbidden','unauthorized','stale'].includes(err.code)){attempt.status='rejected';if(attempt.selection&&err.code==='stale'){state.stale=true;state.message='Каталог моделей устарел. Обновите список моделей; выбор и черновик сохранены.';}attempt.localError=err.message+' Черновик сохранён; отправка не повторялась.';ensureReceipts(key).delete(attempt.id);if(activeSelection(project,sid,generation)){renderHistory(key);$('send-status').textContent=attempt.localError;}return;}else{result={status:'delivery_unknown',message_id:attempt.id,turn_id:null};}}if(!csrf||chatAuthGeneration!==auth)return;if(!result.message_id)result.message_id=attempt.id;applyReceipt(key,result);if(!ensureReceipts(key).has(attempt.id))applyReceipt(key,{status:'delivery_unknown',message_id:attempt.id,turn_id:null});attempt.status=ensureReceipts(key).get(attempt.id).status;if(attempt.status==='accepted'&&drafts.get(key)===text){drafts.delete(key);if(activeSelection(project,sid,generation)&&$('chat-draft').value===text)$('chat-draft').value='';}if(activeSelection(project,sid,generation)){renderHistory(key);renderCurrentSendStatus();renderReceipts(key);}}finally{if(chatAuthGeneration===auth){sendsInFlight.delete(key);syncLocalOutgoingStatuses(key);}syncCurrentSessionControls();}}
function historyChange(){if(document.visibilityState==='hidden')stopPolling();else{syncCurrentSessionControls();startPolling();if(liveTransport)liveJSON(liveTransport).then(result=>{if(result)acceptLiveLease(liveTransport,result.data,result.started);}).catch(()=>{});}}
function historyPinActive(){return Boolean(historyScrollSlack&&pinnedHistoryScope&&selectedSession&&pinnedHistoryScope.project===selectedProject&&pinnedHistoryScope.sid===selectedSession.sid&&pinnedHistoryScope.generation===selectionGeneration);}
function noteHistoryScrollIntent(event){const reader=pageReaderScope&&scrollScopeMatches(pageReaderScope.project,pageReaderScope.sid,pageReaderScope.generation);if(!historyPinActive()&&!reader)return;if(!event.isTrusted)return;const target=event.target;if(target&&(['INPUT','TEXTAREA','SELECT'].includes(target.tagName)||target.isContentEditable)){historyTouchY=null;return;}if(event.type==='wheel'){if(event.deltaY>0){historyScrollIntent=true;notePageReaderReturn();}return;}if(event.type==='touchstart'){historyTouchY=event.touches&&event.touches.length?event.touches[0].clientY:null;return;}if(event.type==='touchmove'){const y=event.touches&&event.touches.length?event.touches[0].clientY:null;if(y!==null&&historyTouchY!==null&&y<historyTouchY){historyScrollIntent=true;notePageReaderReturn();}historyTouchY=y;return;}if(event.type==='keydown'){if(!['ArrowDown','PageDown','End'].includes(event.key)&&!(event.key===' '&&!event.shiftKey))return;historyScrollIntent=true;notePageReaderReturn();return;}if(event.type==='pointerdown'&&event.clientX>=document.documentElement.clientWidth)historyScrollbarStartY=window.scrollY;}
function notePageReaderReturn(){if(pageReaderScope&&scrollScopeMatches(pageReaderScope.project,pageReaderScope.sid,pageReaderScope.generation)){if(window.scrollY>0&&documentMaxScroll()-window.scrollY<=80){pageReaderScope=null;return;}pageReaderScope.returnY=window.scrollY;pageReaderScope.returnUntil=Date.now()+1000;}}
function noteHistoryScrollPosition(){const reader=pageReaderScope&&scrollScopeMatches(pageReaderScope.project,pageReaderScope.sid,pageReaderScope.generation);const scrollbar=historyScrollbarStartY!==null&&window.scrollY>historyScrollbarStartY;if(historyPinActive()&&scrollbar)historyScrollIntent=true;if(reader&&window.scrollY>0&&documentMaxScroll()-window.scrollY<=80&&(scrollbar||pageReaderScope.returnUntil>=Date.now()&&window.scrollY>pageReaderScope.returnY))pageReaderScope=null;}
function endHistoryScrollbarDrag(){historyScrollbarStartY=null;}

$('login-form').addEventListener('submit',async event=>{event.preventDefault();if(busy)return;busy=true;const b=event.target.querySelector('button');b.disabled=true;notice('Входим…');try{const data=await api('/api/login',{username:$('username').value,password:$('password').value,totp:$('login-totp').value});csrf=data.csrf;$('password').value='';$('login-totp').value='';$('login').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;const link=parseDeepLink();if(link){showTab('sessions',false);await loadProjects();}else{showTab('tasks',false);updateUrl();await refresh();}}catch(err){notice(err.message);}finally{busy=false;b.disabled=false;}});
$('refresh').addEventListener('click',refresh);
$('logout').addEventListener('click',async()=>{const native=androidAuth();if(native&&typeof native.requestLogout==='function'){stopPolling();native.requestLogout();return;}try{await api('/api/logout',{});signedOut();drafts.clear();receipts.clear();latestAttempts.clear();historyData.clear();sessionRows=[];$('cards').replaceChildren();$('session-list').replaceChildren();clearHistoryView();updateUrl();notice('Вы вышли из Control.');}catch(err){notice(err.message);}});
$('tab-tasks').addEventListener('click',()=>showTab('tasks'));
$('tab-sessions').addEventListener('click',()=>showTab('sessions'));
$('project-sort').addEventListener('change',()=>{projectSort=$('project-sort').value==='activity'?'activity':'count';try{localStorage.setItem('project-sort',projectSort);}catch(_){}renderProjects();});
$('projects-refresh').addEventListener('click',loadProjects);
$('sessions-more').addEventListener('click',()=>{if(sessionsHaveMore)loadSessionList(sessionPage+1,true);});
$('chat-refresh').addEventListener('click',()=>loadHistory(false,true));
$('history-retry').addEventListener('click',()=>loadHistory(false,true));
$('history-new').addEventListener('click',()=>{if(activeSelection()){initialScrollTarget=null;scrollToDocumentBottom();}});
$('chat-latest').addEventListener('click',()=>{const project=selectedProject,sid=selectedSession&&selectedSession.sid,generation=selectionGeneration;if(scrollScopeMatches(project,sid,generation)){initialScrollTarget=null;scrollToDocumentBottom();}});
document.querySelectorAll('[data-page-scroll]').forEach(button=>button.addEventListener('click',()=>{initialScrollTarget=null;clearHistoryScrollSlack();if(button.dataset.pageScroll==='up'){pageReaderScope={project:selectedProject,sid:selectedSession&&selectedSession.sid,generation:selectionGeneration};window.scrollTo(0,0);}else scrollToDocumentBottom();}));
$('history-older').addEventListener('click',()=>loadHistory(true));
$('send-check').addEventListener('click',()=>{const key=currentSessionKey(),attempt=key&&latestAttempts.get(key);if(attempt&&attempt.status==='delivery_unknown')checkDelivery(key,attempt.id);});
$('rename-open').addEventListener('click',openRenameDialog);
$('rename-form').addEventListener('submit',submitRename);
$('rename-title').addEventListener('input',()=>{const key=currentSessionKey();if(key&&renameDialogScope)renameState(key).draft=$('rename-title').value;});
$('rename-cancel').addEventListener('click',()=>{closeRenameDialog();$('rename-open').focus({preventScroll:true});});
$('rename-dialog').addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();closeRenameDialog();$('rename-open').focus({preventScroll:true});}});
// A text input sanitizes line breaks before exposing value; reject raw pasted controls first.
$('rename-title').addEventListener('paste',event=>{const raw=event.clipboardData?.getData('text');if(typeof raw==='string'&&/[\u0000-\u001f\u007f-\u009f]/u.test(raw)){event.preventDefault();const key=currentSessionKey();if(key){renameState(key).message='Управляющие символы в названии запрещены.';syncRenameControls();}}});
$('rename-dialog').addEventListener('cancel',event=>{event.preventDefault();closeRenameDialog();});
$('rename-check').addEventListener('click',checkRename);
$('rename-current-check').addEventListener('click',checkRename);
$('create-open').addEventListener('click',openCreateDialog);
$('create-form').addEventListener('submit',submitCreate);
$('create-cancel').addEventListener('click',closeCreateDialog);
$('create-dialog').addEventListener('cancel',event=>{event.preventDefault();closeCreateDialog();});
$('create-check').addEventListener('click',checkCreate);
$('chat-form').addEventListener('submit',submitMessage);
$('chat-model').addEventListener('change',()=>{const key=currentSessionKey();if(!key||sendsInFlight.has(key)||hasUnknown(key))return;const state=modelDraft(key),row=state.catalog?.rows.find(row=>row.id===$('chat-model').value),previous=state.effort;state.modelId=$('chat-model').value;state.label=row?.label||'';if(!state.modelId||!row?.efforts.includes(previous)){state.effort='';state.message=previous&&state.modelId?'Выберите уровень размышления: прежний уровень недоступен для этой модели.':'';}else state.message='';syncCurrentSessionControls();});
$('chat-effort').addEventListener('change',()=>{const key=currentSessionKey();if(!key||sendsInFlight.has(key)||hasUnknown(key))return;const state=modelDraft(key);state.effort=$('chat-effort').value;state.message='';syncCurrentSessionControls();});
$('models-refresh').addEventListener('click',()=>{const key=currentSessionKey();if(key&&!sendsInFlight.has(key)&&!hasUnknown(key))loadModelCatalog();});
$('chat-draft').addEventListener('input',()=>{if(selectedSession){const key=chatKey(selectedProject,selectedSession.sid);drafts.set(key,$('chat-draft').value);syncCurrentSessionControls();if(hasUnknown(key))$('send-status').textContent='Есть отправка с неизвестным статусом. Сначала проверьте её вручную.';}});
document.addEventListener('visibilitychange',historyChange);
window.addEventListener('pagehide',()=>stopPolling());
document.addEventListener('wheel',noteHistoryScrollIntent,{passive:true});
document.addEventListener('touchstart',noteHistoryScrollIntent,{passive:true});
document.addEventListener('touchmove',noteHistoryScrollIntent,{passive:true});
document.addEventListener('keydown',noteHistoryScrollIntent);
document.addEventListener('pointerdown',noteHistoryScrollIntent,{passive:true});
document.addEventListener('pointerup',endHistoryScrollbarDrag,{passive:true});
document.addEventListener('pointercancel',endHistoryScrollbarDrag,{passive:true});
window.addEventListener('scroll',noteHistoryScrollPosition,{passive:true});

async function restoreSession(){if(busy)return;busy=true;const retry=$('session-retry');retry.hidden=true;retry.disabled=true;$('session-loading').hidden=false;$('login').hidden=true;$('workspace').hidden=true;$('logout').hidden=true;notice('Восстанавливаем сессию…');try{const data=await api('/api/session');if(typeof data.csrf!=='string'||!data.csrf)throw new Error(messages.unavailable);csrf=data.csrf;$('session-loading').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;notice('');const link=parseDeepLink();if(link){showTab('sessions',false);await loadProjects();}else{showTab('tasks',false);updateUrl();await refresh();}}catch(err){if(err.status===401){if(!androidAuth())signedOut();notice('');}else{notice(err.message+' Повторите восстановление сессии.');retry.hidden=false;}}finally{busy=false;retry.disabled=false;}}
window.aiControlAndroidResume=async function(){const generation=++androidResumeGeneration;try{const data=await api('/api/session',undefined,undefined,()=>generation===androidResumeGeneration);if(generation!==androidResumeGeneration)return false;if(typeof data.csrf!=='string'||!data.csrf)return false;csrf=data.csrf;$('session-loading').hidden=true;$('login').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;notice('');startPolling();if(selectedSession)await loadHistory(false);else if(!projectNames.length){if(currentTab==='sessions')await loadProjects();else await refresh();}return true;}catch(_){return false;}};
$('session-retry').addEventListener('click',restoreSession);
// Native admission invokes the fixed resume entry once after cookie synchronization.
if(!androidAuth())restoreSession();
