'use strict';
const $ = id => document.getElementById(id);
let csrf = '';
let busy = false;
let taskLoaded = false;
const drafts = new Map();
const modelDrafts = new Map();
let modelExpiryTimer=null;
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
async function api(path,body,signal,isCurrent=()=>true){let response;try{response=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',signal,headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});}catch(_){throw new Error(messages.unavailable);}let data;try{data=await response.json();}catch(_){throw new Error(messages.unavailable);}if(signal&&signal.aborted)throw new Error(messages.unavailable);if(!response.ok){if(response.status===401&&path!=='/api/login'&&isCurrent())signedOut();const error=new Error(messages[data.error]||messages.unavailable);error.code=data.error;error.status=response.status;error.data=data;throw error;}return data;}
function signedOut(){attentionProjectsBlocked=false;attentionReset(false);closeCreateDialog();creates.clear();closeRenameDialog();renames.clear();chatAuthGeneration++;sendsInFlight.clear();modelDrafts.clear();if(acceptedStatusTimer!==null){clearTimeout(acceptedStatusTimer);acceptedStatusTimer=null;}csrf='';taskLoaded=false;stopPolling();selectionGeneration++;initialScrollTarget=null;clearHistoryScrollSlack();selectedSession=null;selectedProject='';projectNames=[];availableProjects=new Set();projectEntries=[];projectSummaries.clear();projectsGeneration++;$('project-cloud').replaceChildren();$('project-summary-status').textContent='';sessionRows=[];drafts.clear();receipts.clear();latestAttempts.clear();historyData.clear();$('session-loading').hidden=true;$('workspace').hidden=true;$('login').hidden=false;$('logout').hidden=true;$('session-list').replaceChildren();$('cards').replaceChildren();updateUrl();syncCurrentSessionControls();}
function field(parent,key,label,kind='textarea'){const wrap=node('label',label);const input=node(kind);input.maxLength=16000;input.value=drafts.get(key)||'';input.addEventListener('input',()=>drafts.set(key,input.value));wrap.append(input);parent.append(wrap);return input;}
function button(parent,label,action,cls){const b=node('button',label,cls);b.type='button';b.addEventListener('click',action);parent.append(b);return b;}
async function mutate(card,path,body){if(busy)return;busy=true;const controls=[...document.querySelectorAll('#tasks-panel button')];controls.forEach(b=>b.disabled=true);const status=card.querySelector('.message');status.textContent='Сохраняем…';try{const data=await api(path,body);status.textContent=data.status==='already'?'Решение уже было принято.':'Решение принято.';await refresh();}catch(err){status.textContent=err.message;if(err.code==='saved_pending'){await refresh();notice(err.message);}}finally{busy=false;controls.forEach(b=>b.disabled=false);}}
function question(card,task,q){
  const box=node('div',undefined,'question');if(UUID_RE.test(q.qid))box.dataset.qid=q.qid;box.append(node('h3',q.kind==='permission'?'Нужно разрешение':'Нужен ваш ответ'));box.append(node('p',q.question,'content'));card.append(box);
  if(q.answered){box.append(node('h3','Ваш сохранённый ответ'));box.append(node('p',q.kind==='info'?(q.saved_answer||''):q.saved_decision==='approve'?'Вы разрешили операцию':'Вы отклонили операцию','content'));box.append(node('span',q.pending_delivery?'Ответ сохранён и ожидает доставки':'Ответ доставлен','badge'));if(q.status==='open'&&q.pending_delivery){box.append(node('p','Первый ответ уже сохранён. Повторная попытка доставит именно его.','meta'));const actions=node('div',undefined,'actions');button(actions,'Повторить доставку',()=>mutate(card,'/api/answer',{agent:task.agent,qid:q.qid,decision:'recover',text:''}));box.append(actions);}if(q.status!=='open')box.append(node('p','Вопрос закрыт','meta'));return;}
  if(q.status!=='open'){box.append(node('span','Вопрос закрыт','badge'));return;}const actions=node('div',undefined,'actions');if(q.kind==='info'){const input=field(box,task.agent+':'+q.qid,'Ваш ответ');button(actions,'Отправить ответ',()=>{if(!input.value.trim()){card.querySelector('.message').textContent='Напишите ответ.';return;}mutate(card,'/api/answer',{agent:task.agent,qid:q.qid,decision:'text',text:input.value});});}else{for(const decision of q.allowed_decisions||[]){if(!['approve','reject'].includes(decision))continue;button(actions,decision==='approve'?'Разрешить':'Отклонить',()=>mutate(card,'/api/answer',{agent:task.agent,qid:q.qid,decision,text:''}),decision==='reject'?'secondary':'');}}box.append(actions);
}
function result(card,task,r){if(!r)return;const box=node('div',undefined,'question');if(typeof r.generation==='string'&&/^[0-9a-f]{8}$/.test(r.generation))box.dataset.resultGeneration=r.generation;card.append(box);box.append(node('h3','Результат работы'));box.append(node('p',r.summary,'content'));const labels={requested:r.finalized?'Ждёт вашей проверки':'Готовится к проверке',accepted:'Вы приняли результат',rejected:'Вы отклонили результат',archived:'Работа завершена'};box.append(node('span',labels[r.state]||'Решение сохранено','badge'));if(r.state!=='requested'||!r.finalized)return;box.append(node('p','Принятие подтверждает результат. Применение изменений может завершиться позже.','meta'));const comment=field(box,task.agent+':'+r.generation,'Комментарий (необязательно)');const confirmLabel=node('label',undefined,'confirm');const check=node('input');check.type='checkbox';confirmLabel.append(check,node('span','Я проверил результат и подтверждаю решение'));box.append(confirmLabel);const rejectDetails=node('div');rejectDetails.hidden=true;const totp=field(rejectDetails,task.agent+':totp','Свежий код подтверждения','input');totp.maxLength=6;totp.inputMode='numeric';totp.autocomplete='one-time-code';totp.value='';totp.addEventListener('input',()=>drafts.delete(task.agent+':totp'));box.append(rejectDetails);const actions=node('div',undefined,'actions');const send=decision=>{if(!check.checked){card.querySelector('.message').textContent='Подтвердите, что проверили результат.';check.focus();return;}if(decision==='reject'&&(!rejectDetails.hidden&&!/^[0-9]{6}$/.test(totp.value)||rejectDetails.hidden)){rejectDetails.hidden=false;card.querySelector('.message').textContent='Для отклонения нужен новый код, отличный от кода входа.';totp.focus();return;}const body={agent:task.agent,generation:r.generation,decision,comment:comment.value,confirmed:true};if(decision==='reject')body.totp=totp.value;mutate(card,'/api/verdict',body);};button(actions,'Принять результат',()=>send('accept'));button(actions,'Отклонить',()=>send('reject'),'danger');box.append(actions);}
function priority(task){if((task.questions||[]).some(q=>q.status==='open'&&!q.answered))return 0;if(task.result&&task.result.state==='requested'&&task.result.finalized)return 1;return 2;}
function renderTasks(data){const tasks=data.tasks.slice().sort((a,b)=>priority(a)-priority(b));const fragment=document.createDocumentFragment();for(const task of tasks){const card=node('article',undefined,'card');card.tabIndex=-1;if(/^[a-z][a-z0-9-]{0,30}[a-z0-9]$/.test(task.agent))card.dataset.agent=task.agent;if(typeof task.task_key==='string'&&/^[0-9a-f]{64}$/.test(task.task_key))card.dataset.taskKey=task.task_key;card.append(node('h2',task.name||task.agent));card.append(node('p',task.engine==='codex'?'Codex':'Claude','meta'));card.append(node('p','','message'));if(task.unavailable){card.append(node('p','Данные задачи временно недоступны. Обновите позже.'));}else{if(task.summary)card.append(node('p',task.summary,'content'));for(const q of task.questions||[])question(card,task,q);result(card,task,task.result);}fragment.append(card);}$('cards').replaceChildren(fragment);$('count').textContent=tasks.length?'Задач: '+tasks.length:'Пока нет задач';taskLoaded=true;}
let tasksRequest=0;
async function refresh(){if(!csrf)return;const request=++tasksRequest,auth=chatAuthGeneration,scope=attentionScope;const current=()=>Boolean(csrf&&auth===chatAuthGeneration&&scope===attentionScope&&request===tasksRequest);const b=$('refresh');b.disabled=true;notice('Загружаем задачи…');try{const data=await api('/api/tasks',undefined,undefined,current);if(!current())return;renderTasks(data);notice(data.tasks.some(t=>t.unavailable)?'Некоторые задачи недоступны. Попробуйте обновить позже.':'');}catch(err){if(current())notice(err.message+' Нажмите «Обновить», чтобы повторить.');}finally{if(current())b.disabled=false;}}

// Session chat state is memory-only. The URL can identify a project/thread, never message text.
let selectedProject='';
let selectedSession=null;
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
function stopPolling(){stopMessageAges();if(pollTimer!==null){clearInterval(pollTimer);pollTimer=null;}}
function startPolling(){stopPolling();syncMessageAges();if(currentTab==='sessions'&&selectedSession&&document.visibilityState==='visible'&&csrf)pollTimer=setInterval(()=>{if(document.visibilityState==='visible'&&selectedSession&&!normalizeHistoryState(currentSessionKey()).historyError)loadHistory(false);},5000);}
function currentSessionKey(){return selectedProject&&selectedSession?chatKey(selectedProject,selectedSession.sid):null;}
function modelDraft(key){if(!modelDrafts.has(key))modelDrafts.set(key,{modelId:'',label:'',effort:'',catalog:null,expires:0,request:0,loading:false,stale:false,message:''});return modelDrafts.get(key);}
function explicitModelReady(key){const state=modelDraft(key);if(!state.modelId)return true;const row=state.catalog?.rows.find(row=>row.id===state.modelId);return Boolean(!state.loading&&!state.stale&&state.expires>performance.now()&&row&&row.efforts.includes(state.effort));}
function renderModelControls(){
  if(modelExpiryTimer!==null){clearTimeout(modelExpiryTimer);modelExpiryTimer=null;}
  const key=currentSessionKey(),state=key?modelDraft(key):null,model=$('chat-model'),effort=$('chat-effort');
  const rows=state?.catalog?.rows||[],locked=Boolean(key&&(sendsInFlight.has(key)||hasUnknown(key)));
  model.replaceChildren(new Option('Наследовать текущую',''));
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
function syncCurrentSessionControls(){const key=currentSessionKey();const historyBusy=Boolean(key&&historyFlights.has(key));const state=key&&historyData.get(key);const hasOlder=Boolean(state&&(hasEarlierHistory(state)||state.olderAnchors.some(anchor=>!anchor.error)));$('chat-send').disabled=!csrf||currentTab!=='sessions'||!key||Boolean(selectedSession?.created&&!state?.initialized&&!state?.confirmedOrigin)||sendsInFlight.has(key)||hasUnknown(key)||!explicitModelReady(key);$('chat-refresh').disabled=!key||historyBusy;$('history-older').disabled=!key||historyBusy||!hasOlder;$('history-retry').hidden=!(state&&state.historyError);$('history-retry').disabled=!key||historyBusy;renderModelControls();renderCurrentSendStatus();syncRenameControls();syncCreateControls();}
function showTab(tab,load=true){attentionReset(true);currentTab=tab;const tasks=tab==='tasks';if(tasks)clearHistoryScrollSlack();$('tab-tasks').setAttribute('aria-selected',String(tasks));$('tab-sessions').setAttribute('aria-selected',String(!tasks));$('tasks-panel').hidden=!tasks;$('sessions-panel').hidden=tasks;syncCurrentSessionControls();if(tasks){stopPolling();if(load&&!taskLoaded)refresh();}else{if(load&&!projectNames.length)loadProjects();else if(load&&!selectedProject)loadSessionList(0,false);startPolling();}}
function setSessionStatus(text){$('session-list-status').textContent=text;}
function renderProjects(){
  const cloud=$('project-cloud'),focused=document.activeElement,y=window.scrollY;
  const existing=new Map([...cloud.children].map(button=>[button.dataset.project,button]));
  const known=entry=>{const value=projectSummaries.get(entry.name);return value&&['fresh','stale'].includes(value.summary_state)&&Number.isSafeInteger(value.session_count)&&value.session_count>=0?value:null;};
  const aliasCompare=(a,b)=>{const x=a.name.toLowerCase(),z=b.name.toLowerCase();return x<z?-1:x>z?1:a.name<b.name?-1:a.name>b.name?1:0;};
  const activityGroup=value=>!value?3:value.last_activity===null?2:value.summary_state==='fresh'?0:1;
  const ordered=projectEntries.slice().sort((a,b)=>{
    const x=known(a),z=known(b);
    if(projectSort==='count'){if(Boolean(x)!==Boolean(z))return x?-1:1;if(x&&x.session_count!==z.session_count)return z.session_count-x.session_count;}
    else{const gx=activityGroup(x),gz=activityGroup(z);if(gx!==gz)return gx-gz;if(gx<2&&x.last_activity!==z.last_activity)return z.last_activity-x.last_activity;}
    return aliasCompare(a,b);
  });
  const retained=new Set();
  for(const entry of ordered){
    let button=existing.get(entry.name);
    if(!button){button=node('button',undefined,'project-tile');button.type='button';button.dataset.project=entry.name;button.addEventListener('click',()=>projectChanged(entry.name));}
    retained.add(button);
    const value=known(entry),unavailable=!availableProjects.has(entry.name);
    button.disabled=unavailable;button.setAttribute('aria-pressed',String(!unavailable&&selectedProject===entry.name));
    const bucket=value?Math.min(5,Math.floor(Math.log2(value.session_count+1))):0;
    button.style.setProperty('--tile-width',(112+12*bucket)+'px');button.style.setProperty('--tile-height',(64+8*bucket)+'px');
    const details=unavailable?'Недоступен':value?value.session_count+' сессий'+(value.summary_state==='stale'?' · устарело':''):'Число сессий неизвестно';
    button.replaceChildren(node('span',entry.name,'project-name'),node('span',details,'meta'));
    button.title=value?'Сводка: '+new Date(value.as_of*1000).toLocaleString()+(value.last_activity===null?' · нет активности':' · последняя активность: '+new Date(value.last_activity*1000).toLocaleString()):details;
    cloud.append(button);
  }
  for(const button of existing.values())if(!retained.has(button))button.remove();
  if(retained.has(focused)&&!focused.disabled)focused.focus({preventScroll:true});
  if(window.scrollY!==y)window.scrollTo(0,y);
  syncCreateControls();
}
function clearUnavailableProject(){attentionReset(false);stopPolling();selectionGeneration++;initialScrollTarget=null;selectedProject='';selectedSession=null;sessionRows=[];sessionPage=0;sessionsHaveMore=false;clearHistoryView();$('session-list').replaceChildren();$('sessions-more').hidden=true;updateUrl();syncCurrentSessionControls();renderProjects();}
function projectChanged(name){
  if(!availableProjects.has(name))return;
  attentionReset(true);
  selectedProject=name;sessionPage=0;sessionRows=[];selectedSession=null;selectionGeneration++;initialScrollTarget=null;clearHistoryView();$('session-list').replaceChildren();$('sessions-more').hidden=true;updateUrl();stopPolling();renderProjects();loadSessionList(0,false);
}
async function loadProjects(){
  if(!csrf)return;
  attentionProjectsBlocked=true;attentionReset(false);
  const generation=++projectsGeneration,auth=csrf,selection=selectionGeneration,hadNames=projectEntries.length>0;
  const current=()=>csrf===auth&&generation===projectsGeneration;
  if(!hadNames)setSessionStatus('Загружаем проекты…');
  $('projects-refresh').disabled=true;
  try{
    const data=await api('/api/session-projects');if(!current())return;
    if(!Array.isArray(data.projects))throw new Error('invalid projects');
    attentionProjectsBlocked=false;projectEntries=data.projects.filter(x=>x&&typeof x.name==='string');
    projectNames=projectEntries.map(x=>x.name);
    availableProjects=new Set(projectEntries.filter(x=>x.unavailable!==true).map(x=>x.name));
    if(selectedProject&&!availableProjects.has(selectedProject)){clearUnavailableProject();setSessionStatus('Выбранный проект недоступен. Выберите другой проект.');}
    renderProjects();
    let summaryFailed=false;
    try{
      const summary=await api('/api/session-project-summary');if(!current())return;
      if(!Array.isArray(summary.projects))throw new Error('invalid summary');
      projectSummaries=new Map(summary.projects.filter(x=>x&&projectNames.includes(x.name)).map(x=>[x.name,x]));
      for(const [name,value] of projectSummaries)if(value.summary_state==='unavailable')availableProjects.delete(name);
      if(selectedProject&&!availableProjects.has(selectedProject)){clearUnavailableProject();setSessionStatus('Выбранный проект недоступен. Выберите другой проект.');}
    }catch(_){if(!current())return;projectSummaries.clear();summaryFailed=true;}
    $('project-summary-status').textContent=summaryFailed?'Сводка недоступна. Число сессий и активность неизвестны.':'';
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
  finally{if(current()){$('projects-refresh').disabled=false;attentionReset(true);}}
}
async function loadSessionList(page=0,append=false,deepSid=null){const project=selectedProject;if(!project||!availableProjects.has(project))return;const generation=selectionGeneration;setSessionStatus(deepSid?'Ищем выбранную сессию…':'Загружаем сессии…');$('sessions-more').disabled=true;try{const data=await api(queryPath('/api/sessions',{project,page}));if(project!==selectedProject||generation!==selectionGeneration)return;const rows=Array.isArray(data.rows)?data.rows:[];sessionPage=page;sessionsHaveMore=data.has_more===true;sessionRows=append?sessionRows.concat(rows):rows;renderSessions();$('sessions-more').hidden=!sessionsHaveMore;if(deepSid){const found=rows.find(row=>row&&row.sid===deepSid);if(found){openChat(found);return;}if(sessionsHaveMore&&page<99)return loadSessionList(page+1,false,deepSid);setSessionStatus('Сессия из ссылки не найдена среди доступных сессий. Выберите другую из списка.');}else setSessionStatus(sessionRows.length?'Выберите сессию для переписки.':'В этом проекте пока нет доступных сессий.');}catch(_){if(project===selectedProject&&generation===selectionGeneration)setSessionStatus('Список сессий недоступен. Попробуйте ещё раз.');}finally{$('sessions-more').disabled=false;}}
function renderSessions(){const list=$('session-list');const frag=document.createDocumentFragment();for(const row of sessionRows){if(!row||typeof row.sid!=='string'||!UUID_RE.test(row.sid))continue;const b=node('button',undefined,'session-choice'+(selectedSession&&selectedSession.sid===row.sid?' selected':''));b.type='button';b.setAttribute('aria-pressed',String(Boolean(selectedSession&&selectedSession.sid===row.sid)));b.append(node('span',row.title||'Codex','session-title'));const vendorLabel=row.vendor==='codex'?'Codex':row.vendor==='claude'?'Claude':'Вендор неизвестен';b.append(node('span',vendorLabel,'session-vendor-badge'));b.append(node('span',statusLabel(row.status),'meta'));if(row.needs_native_attention===true)b.append(node('span','Нужно действие в клиенте Codex; ответы из панели пока недоступны.','attention-inline'));b.addEventListener('click',()=>openChat(row));frag.append(b);}list.replaceChildren(frag);}
function statusLabel(status){const labels={active:'Работает',idle:'Готова',notLoaded:'Недоступна',systemError:'Ошибка',completed:'Завершён',interrupted:'Прерван',failed:'Ошибка',inProgress:'Выполняется'};return labels[status]||'Состояние неизвестно';}
function chatError(err){if(err&&err.code==='stale')return 'Сессия устарела или изменилась. Обновите список и выберите её снова.';return err&&err.message||messages.unavailable;}
function clearHistoryScrollSlack(){historyScrollSlack=0;pinnedHistoryScope=null;historyScrollIntent=false;historyTouchY=null;historyScrollbarStartY=null;if(historyScrollSpacer){historyScrollSpacer.remove();historyScrollSpacer=null;}}
function setHistoryScrollSlack(height){const bounded=Math.max(0,Math.min(window.innerHeight,Math.ceil(height)));historyScrollSlack=bounded;if(!bounded){clearHistoryScrollSlack();return;}if(!historyScrollSpacer){historyScrollSpacer=node('li',undefined,'history-scroll-slack');historyScrollSpacer.setAttribute('aria-hidden','true');historyScrollSpacer.append(document.createElementNS('http://www.w3.org/2000/svg','svg'));}const svg=historyScrollSpacer.firstElementChild;svg.setAttribute('width','0');svg.setAttribute('height',String(bounded));svg.setAttribute('focusable','false');const list=$('chat-items');if(historyScrollSpacer.parentNode!==list)list.append(historyScrollSpacer);}
function clearHistoryView(){stopMessageAges();clearHistoryScrollSlack();historyData.delete(chatKey(selectedProject,selectedSession&&selectedSession.sid||''));$('chat-panel').hidden=true;$('history-new').hidden=true;$('chat-items').replaceChildren();$('receipt-list').replaceChildren();$('history-status').textContent='';$('history-retry').hidden=true;$('send-status').textContent='';$('history-truncated').hidden=true;$('native-attention').hidden=true;$('chat-draft').value='';}
function openChat(row){if(!row||!UUID_RE.test(row.sid))return;attentionReset(true);pageReaderScope=null;if($('session-list-status').textContent==='Выберите сессию для переписки.')setSessionStatus('');stopPolling();clearHistoryScrollSlack();selectionGeneration++;selectedSession={created:row.configuredCreated===true,sid:row.sid,title:typeof row.title==='string'?row.title:'Codex',needs:row.needs_native_attention===true};initialScrollTarget={project:selectedProject,sid:row.sid,generation:selectionGeneration};$('chat-title').textContent=selectedSession.title;$('chat-panel').hidden=false;$('history-status').textContent='Загружаем переписку…';$('chat-items').replaceChildren();$('receipt-list').replaceChildren();$('history-truncated').hidden=true;$('native-attention').hidden=!selectedSession.needs;$('chat-draft').value=drafts.get(chatKey(selectedProject,row.sid))||'';updateUrl();renderSessions();renderReceipts();const state=normalizeHistoryState(chatKey(selectedProject,row.sid));state.windowIds=null;state.windowOlder=false;state.pendingLatest=false;$('history-new').hidden=true;if(state.initialized)renderHistory(chatKey(selectedProject,row.sid));if(state.historyError)$('history-status').textContent=historyErrorText(state);syncCurrentSessionControls();loadHistory(false);loadModelCatalog();startPolling();}
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

function normalizeHistoryState(key){if(!historyData.has(key))historyData.set(key,{turns:new Map(),order:[],olderAnchors:[],initialized:false,truncated:false,attention:false,paginationError:'',historyError:'',historyErrorOrigin:null,latestHistoryError:'',windowIds:null,windowOlder:false,pendingLatest:false});return historyData.get(key);}
function validHistoryId(value){return typeof value==='string'&&value.length>0&&value.length<=500;}
function mergeHistory(key,data,olderAnchor){const state=normalizeHistoryState(key);const incoming=Array.isArray(data.turns)?data.turns:[];const chronological=incoming.slice().reverse().filter(turn=>turn&&validHistoryId(turn.id));const incomingIds=new Set(chronological.map(turn=>turn.id));const existingIds=new Set(state.order);const hadOverlap=chronological.some(turn=>existingIds.has(turn.id));for(const turn of chronological){const previous=state.turns.get(turn.id);const itemMap=new Map();for(const item of (previous&&previous.items)||[])if(validHistoryId(item&&item.id))itemMap.set(item.id,item);for(const item of (Array.isArray(turn.items)?turn.items:[])){if(item&&validHistoryId(item.id))itemMap.set(item.id,item);}state.turns.set(turn.id,{...turn,items:[...itemMap.values()]});}
  const ids=chronological.map(turn=>turn.id).filter((id,i,a)=>a.indexOf(id)===i);if(olderAnchor){const anchorIndex=state.olderAnchors.indexOf(olderAnchor);const originalOrder=state.order;const overlapId=ids.find(id=>existingIds.has(id));const boundaryId=overlapId||olderAnchor.afterId;const boundaryIndex=boundaryId===null?-1:originalOrder.indexOf(boundaryId);const insertAt=boundaryIndex<0?0:originalOrder.slice(0,boundaryIndex).filter(id=>!incomingIds.has(id)).length;state.order=originalOrder.filter(id=>!incomingIds.has(id));state.order.splice(insertAt,0,...ids.filter(id=>!state.order.includes(id)));if(anchorIndex>=0){if(data.next_cursor){if(olderAnchor.seen.has(data.next_cursor)){olderAnchor.error=true;state.paginationError='Продолжение истории недоступно: сервер повторил cursor.';}else{state.olderAnchors[anchorIndex]={cursor:data.next_cursor,afterId:ids[0]||olderAnchor.afterId,seen:new Set([...olderAnchor.seen,data.next_cursor]),error:false};}}else state.olderAnchors.splice(anchorIndex,1);}}else{state.order=[...state.order.filter(id=>!incomingIds.has(id)),...ids];if(!state.initialized){state.olderAnchors=[];if(data.next_cursor)state.olderAnchors.push({cursor:data.next_cursor,afterId:ids[0]||state.order[0]||null,seen:new Set([data.next_cursor]),error:false});state.initialized=true;}else if(data.next_cursor&&!hadOverlap&&!state.olderAnchors.some(anchor=>anchor.cursor===data.next_cursor)){state.olderAnchors.push({cursor:data.next_cursor,afterId:ids[0]||state.order[0]||null,seen:new Set([data.next_cursor]),error:false});}}
  state.paginationError=state.olderAnchors.some(anchor=>anchor.error)?'Продолжение истории недоступно: сервер повторил cursor.':'';
  state.truncated=state.truncated||data.truncated===true;state.attention=data.needs_native_attention===true;for(const receipt of Array.isArray(data.recent_sends)?data.recent_sends:[])applyReceipt(key,receipt);return state;}
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
  const controller=new AbortController();
  let timeout;
  const deadline=new Promise((_,reject)=>{timeout=setTimeout(()=>{controller.abort();reject(new Error('Время загрузки переписки истекло. Повторите загрузку.'));},15000);});
  if(!state.initialized||manual)$('history-status').textContent='Загружаем переписку…';
  const flight={generation,controller,promise:null};
  historyFlights.set(key,flight);
  const promise=(async()=>{
    try{
      // The deadline includes JSON consumption, and only cancels this browser GET.
      const data=await Promise.race([api(path,undefined,controller.signal,()=>activeSelection(project,sid,generation)),deadline]);
      if(!activeSelection(project,sid,generation)||historyFlights.get(key)!==flight)return;
      if(Object.hasOwn(data,'history_state')){
        const keys=['history_state','reason','recent_sends'];if(Object.hasOwn(data,'needs_native_attention'))keys.push('needs_native_attention');
        if(older||!exactFields(data,keys)||data.history_state!=='unavailable'||data.reason!=='unavailable'||Object.hasOwn(data,'needs_native_attention')&&data.needs_native_attention!==true||!Array.isArray(data.recent_sends)||data.recent_sends.length>8||!data.recent_sends.every(row=>exactFields(row,['status','message_id','turn_id'])&&UUID_RE.test(row.message_id)&&(['accepted','delivery_unknown','rejected'].includes(row.status))&&(row.status==='accepted'?typeof row.turn_id==='string'&&row.turn_id.length>0&&Array.from(row.turn_id).length<=500:row.turn_id===null)))throw new Error(messages.unavailable);
        state.confirmedOrigin=true;state.unavailable=true;state.attention=data.needs_native_attention===true;
        state.latestHistoryError='История пока недоступна';state.historyError=state.latestHistoryError;state.historyErrorOrigin='latest';
        for(const receipt of data.recent_sends)applyReceipt(key,receipt);
        renderHistory(key);$('history-status').textContent=state.historyError;syncCurrentSessionControls();return;
      }
      state.confirmedOrigin=false;state.unavailable=false;
      let scrollDecision=captureHistoryScroll(project,sid,generation,older);
      const known=new Set(historyItems(state).map(entry=>entry.key));
      const hold=state.windowIds!==null&&(state.windowOlder||focusedHistoryBubble()||scrollDecision&&scrollDecision.kind!=='bottom');
      if(hold&&scrollDecision&&scrollDecision.kind==='bottom')scrollDecision=captureHistoryScroll(project,sid,generation,true);
      mergeHistory(key,data,anchor);
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
        if(!older)state.latestHistoryError=state.historyError;
        $('history-status').textContent=historyErrorText(state);
      }
    }finally{
      clearTimeout(timeout);
      if(historyFlights.get(key)===flight){historyFlights.delete(key);if(activeSelection(project,sid,generation))syncCurrentSessionControls();}
    }
  })();
  flight.promise=promise;syncCurrentSessionControls();return promise;
}
// INV-WSESS-20/21: only validated native turn starts supply dates; ages are local.
function messageTimestamp(item){return item.time_precision==='turn'&&Number.isInteger(item.timestamp)&&item.timestamp>=0&&item.timestamp<=253402300799?item.timestamp:null;}
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
  const exact=new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(date)+' — начало хода';
  const control=node('button',undefined,'message-time');control.type='button';
  control.setAttribute('aria-label',exact);control.setAttribute('aria-expanded','false');
  const time=node('time',messageAge(timestamp));time.dateTime=date.toISOString();time.dataset.timestamp=String(timestamp);
  control.append(time,node('span',exact,'message-time-detail'));
  control.addEventListener('click',()=>control.setAttribute('aria-expanded',String(control.getAttribute('aria-expanded')!=='true')));
  return control;
}
function stopMessageAges(){if(messageAgeTimer!==null){clearInterval(messageAgeTimer);messageAgeTimer=null;}}
function messageAgesActive(){return Boolean(csrf&&currentTab==='sessions'&&selectedSession&&document.visibilityState==='visible'&&!$('workspace').hidden&&!$('chat-panel').hidden);}
function updateMessageAges(){
  if(!messageAgesActive())return;
  for(const time of $('chat-items').querySelectorAll('time[data-timestamp]')){
    const text=messageAge(Number(time.dataset.timestamp));
    if(time.textContent!==text)time.textContent=text;
  }
}
function syncMessageAges(){
  stopMessageAges();
  if(messageAgesActive()){updateMessageAges();messageAgeTimer=setInterval(updateMessageAges,60000);}
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
function historyArticle(entry,existing,force){
  const article=existing||node('article',undefined,'chat-message '+(entry.item.role==='user'?'from-user':'from-assistant'));
  const item=entry.item,old=article.historyItem;
  const changed=!old||['role','text','truncated','timestamp','time_precision'].some(field=>old[field]!==item[field]);
  if(changed){
    if(existing&&!force&&focusedHistoryBubble()===article){normalizeHistoryState(currentSessionKey()).pendingLatest=true;return article;}
    article.dataset.turnId=entry.turnId;article.dataset.itemId=item.id;
    const heading=node('div',undefined,'message-heading');heading.append(node('h3',item.role==='user'?'Вы':'Codex'),messageTime(item));
    const children=[heading,renderMarkdown(item.text)];
    if(item.truncated===true)children.push(node('span','Сообщение сокращено','meta'));
    article.replaceChildren(...children);article.historyItem=item;
  }
  return article;
}
function renderHistory(key,force=false){
  const state=normalizeHistoryState(key),list=$('chat-items'),all=historyItems(state);
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
      const text='Ход: '+statusLabel(entry.turn.status);if(heading.textContent!==text)heading.textContent=text;
      group={element,children:[heading]};contents.set(entry.turnId,group);children.push(element);
    }
    group.children.push(historyArticle(entry,articles.get(entry.key),force));
  }
  for(const group of contents.values())reconcileHistoryChildren(group.element,group.children);
  if(!visible.length&&!state.unavailable)children.push(node('li','Пока нет отображаемых текстовых сообщений.','meta'));
  if(historyScrollSlack&&historyScrollSpacer)children.push(historyScrollSpacer);
  reconcileHistoryChildren(list,children);syncMessageAges();
  if(historyScrollSlack)setHistoryScrollSlack(historyScrollSlack);
  $('history-truncated').hidden=!(state.truncated||all.some(entry=>entry.item.truncated===true));
  $('history-older').hidden=state.unavailable||!state.initialized;
  $('history-older').disabled=!(hasEarlierHistory(state)||state.olderAnchors.some(anchor=>!anchor.error));
  $('history-new').hidden=!state.pendingLatest;
  $('native-attention').hidden=!(state.attention||(selectedSession&&selectedSession.needs));renderReceipts(key);
}

function statusText(status){return status==='accepted'?'Сообщение принято Codex; работа может продолжаться.':status==='rejected'?'Codex отклонил сообщение; черновик сохранён.':status==='delivery_unknown'?'Доставка неизвестна. Проверьте статус вручную; отправка не повторяется автоматически.':status==='sending'?'Отправляем сообщение…':'Статус сообщения недоступен.';}
function renderCurrentSendStatus(){if(acceptedStatusTimer!==null){clearTimeout(acceptedStatusTimer);acceptedStatusTimer=null;}const key=currentSessionKey(),attempt=key&&latestAttempts.get(key);let slot=$('send-status');if(attempt&&attempt.statusNode&&attempt.statusNode!==slot){attempt.statusNode.setAttribute('aria-live',attempt.status==='accepted'?'off':'polite');slot.replaceWith(attempt.statusNode);slot=attempt.statusNode;}else if(attempt&&!attempt.statusNode){attempt.statusNode=slot;slot.setAttribute('aria-live','polite');}else if(!attempt&&slot.textContent){const empty=slot.cloneNode(false);empty.setAttribute('aria-live','polite');slot.replaceWith(empty);slot=empty;}$('send-check').hidden=!(attempt&&attempt.status==='delivery_unknown');$('send-check').disabled=Boolean(attempt&&statusChecks.has(key+'\u0000'+attempt.id));let text=attempt?(attempt.localError||statusText(attempt.status)):'';if(attempt&&attempt.status==='accepted'){const remaining=(attempt.acceptedUntil||0)-Date.now();if(remaining<=0)text='';else{const project=selectedProject,sid=selectedSession.sid,generation=selectionGeneration,id=attempt.id;acceptedStatusTimer=setTimeout(()=>{acceptedStatusTimer=null;if(currentSessionKey()===key&&selectionGeneration===generation&&selectedSession&&selectedSession.sid===sid&&selectedProject===project&&latestAttempts.get(key)?.id===id)renderCurrentSendStatus();},remaining);}}if($('send-status').textContent!==text)$('send-status').textContent=text;}
function renderReceipts(key=currentSessionKey()){const list=$('receipt-list');if(!list||!selectedSession||key!==currentSessionKey())return;const open=list.querySelector('details')?.open||false;const records=[...ensureReceipts(key).entries()].filter(([,record])=>['sending','delivery_unknown','rejected'].includes(record.status));list.replaceChildren();if(!records.length)return;const details=node('details');details.open=open;details.append(node('summary','Проблемы доставки ('+records.length+')'));for(const [id,record] of records.reverse()){const row=node('div',undefined,'receipt-row');row.append(node('span',record.checkError||statusText(record.status),'receipt-label'));if(record.status==='delivery_unknown'){const check=node('button','Проверить доставку','secondary');check.type='button';check.disabled=statusChecks.has(key+'\u0000'+id);check.addEventListener('click',()=>checkDelivery(key,id));row.append(check);}details.append(row);}list.append(details);}

function hasUnknown(key){return [...ensureReceipts(key).values()].some(entry=>entry.status==='delivery_unknown');}
async function checkDelivery(key,id){if(statusChecks.has(key+'\u0000'+id))return;const [project,sid]=key.split('\u0000');if(project!==selectedProject||!selectedSession||sid!==selectedSession.sid)return;const generation=selectionGeneration,mark=key+'\u0000'+id;statusChecks.add(mark);renderCurrentSendStatus();renderReceipts(key);try{const data=await api(queryPath('/api/session-send-status',{project,sid,message_id:id}));if(!activeSelection(project,sid,generation))return;applyReceipt(key,data);const record=ensureReceipts(key).get(id);if(record)delete record.checkError;const attempt=latestAttempts.get(key);if(attempt&&attempt.id===id)delete attempt.localError;renderCurrentSendStatus();renderReceipts(key);}catch(err){if(activeSelection(project,sid,generation)){const message=err.code==='stale'?'Эта отправка больше недоступна для проверки. Черновик сохранён.':chatError(err)+' Повторите ручную проверку.';const record=ensureReceipts(key).get(id);if(record&&!['accepted','rejected'].includes(record.status))record.checkError=message;const attempt=latestAttempts.get(key);if(attempt&&attempt.id===id&&!['accepted','rejected'].includes(attempt.status))attempt.localError=message;}}finally{statusChecks.delete(mark);if(activeSelection(project,sid,generation)){syncCurrentSessionControls();renderReceipts(key);}}}
function applyReceipt(key,data){if(!data||!['sending','accepted','delivery_unknown','rejected'].includes(data.status)||!UUID_RE.test(data.message_id||''))return;const id=data.message_id,map=ensureReceipts(key),existing=map.get(id),attempt=latestAttempts.get(key);const terminal=existing&&['accepted','rejected'].includes(existing.status)?existing:attempt&&attempt.id===id&&['accepted','rejected'].includes(attempt.status)?{status:attempt.status,turn_id:existing&&existing.turn_id||null}:null;if(terminal){map.set(id,terminal);if(attempt&&attempt.id===id)attempt.status=terminal.status;return;}if(data.status==='sending'&&existing&&existing.status==='delivery_unknown')return;const record={status:data.status,turn_id:data.turn_id||null};if(existing?.checkError&&data.status==='delivery_unknown')record.checkError=existing.checkError;map.set(id,record);if(attempt&&attempt.id===id){if(data.status==='accepted'&&attempt.status!=='accepted'&&attempt.text!==null)attempt.acceptedUntil=Date.now()+5000;attempt.status=data.status;if(!record.checkError)delete attempt.localError;}}
async function submitMessage(event){event.preventDefault();if(!selectedSession||!selectedProject)return;const project=selectedProject,sid=selectedSession.sid,key=chatKey(project,sid),generation=selectionGeneration,auth=chatAuthGeneration,text=$('chat-draft').value;if(!text.trim()){$('send-status').textContent='Напишите сообщение перед отправкой.';return;}if(sendsInFlight.has(key))return;if(hasUnknown(key)){const attempt=latestAttempts.get(key);$('send-status').textContent=attempt&&attempt.text===text?'Для этой попытки уже сохранён ID. Проверьте доставку вручную.':'Сначала проверьте неизвестную доставку. Новый текст пока не отправлен.';renderReceipts(key);return;}const state=modelDraft(key);if(!explicitModelReady(key)){$('send-status').textContent='Выберите поддерживаемый уровень размышления или обновите каталог; черновик сохранён.';syncCurrentSessionControls();return;}const selection=state.modelId?Object.freeze({catalog_id:state.catalog.catalog_id,model_id:state.modelId,effort:state.effort}):null;let attempt=latestAttempts.get(key);if(!attempt||attempt.text!==text||['accepted','rejected'].includes(attempt.status)){attempt={id:crypto.randomUUID(),text,status:'sending',selection,context:Object.freeze({project,sid,generation,auth})};latestAttempts.set(key,attempt);ensureReceipts(key).set(attempt.id,{status:'sending',turn_id:null});}else if(attempt.status==='delivery_unknown'){$('send-status').textContent='Проверьте доставку вручную; повторная отправка отключена.';return;}else{attempt.status='sending';}
  sendsInFlight.add(key);syncCurrentSessionControls();$('send-status').textContent='Отправляем сообщение…';renderReceipts(key);if(scrollScopeMatches(project,sid,generation))scrollToDocumentBottom();try{let result;try{result=await api('/api/session-send',{project,sid,message_id:attempt.id,text:attempt.text,...(attempt.selection?{selection:attempt.selection}:{})});}catch(err){if(!csrf||chatAuthGeneration!==auth)return;if(err.data&&['accepted','rejected','delivery_unknown'].includes(err.data.status))result=err.data;else if(['invalid_request','forbidden','unauthorized','stale'].includes(err.code)){attempt.status='rejected';if(attempt.selection&&err.code==='stale'){state.stale=true;state.message='Каталог моделей устарел. Обновите список моделей; выбор и черновик сохранены.';}attempt.localError=err.message+' Черновик сохранён; отправка не повторялась.';ensureReceipts(key).delete(attempt.id);if(activeSelection(project,sid,generation))$('send-status').textContent=attempt.localError;return;}else{result={status:'delivery_unknown',message_id:attempt.id,turn_id:null};}}if(!csrf||chatAuthGeneration!==auth)return;if(!result.message_id)result.message_id=attempt.id;applyReceipt(key,result);if(!ensureReceipts(key).has(attempt.id))applyReceipt(key,{status:'delivery_unknown',message_id:attempt.id,turn_id:null});attempt.status=ensureReceipts(key).get(attempt.id).status;if(attempt.status==='accepted'&&drafts.get(key)===text){drafts.delete(key);if(activeSelection(project,sid,generation)&&$('chat-draft').value===text)$('chat-draft').value='';}if(activeSelection(project,sid,generation)){renderCurrentSendStatus();renderReceipts(key);}}finally{if(chatAuthGeneration===auth)sendsInFlight.delete(key);syncCurrentSessionControls();}}
function historyChange(){if(document.visibilityState==='hidden')stopPolling();else startPolling();}
function historyPinActive(){return Boolean(historyScrollSlack&&pinnedHistoryScope&&selectedSession&&pinnedHistoryScope.project===selectedProject&&pinnedHistoryScope.sid===selectedSession.sid&&pinnedHistoryScope.generation===selectionGeneration);}
function noteHistoryScrollIntent(event){const reader=pageReaderScope&&scrollScopeMatches(pageReaderScope.project,pageReaderScope.sid,pageReaderScope.generation);if(!historyPinActive()&&!reader)return;if(!event.isTrusted)return;const target=event.target;if(target&&(['INPUT','TEXTAREA','SELECT'].includes(target.tagName)||target.isContentEditable)){historyTouchY=null;return;}if(event.type==='wheel'){if(event.deltaY>0){historyScrollIntent=true;notePageReaderReturn();}return;}if(event.type==='touchstart'){historyTouchY=event.touches&&event.touches.length?event.touches[0].clientY:null;return;}if(event.type==='touchmove'){const y=event.touches&&event.touches.length?event.touches[0].clientY:null;if(y!==null&&historyTouchY!==null&&y<historyTouchY){historyScrollIntent=true;notePageReaderReturn();}historyTouchY=y;return;}if(event.type==='keydown'){if(!['ArrowDown','PageDown','End'].includes(event.key)&&!(event.key===' '&&!event.shiftKey))return;historyScrollIntent=true;notePageReaderReturn();return;}if(event.type==='pointerdown'&&event.clientX>=document.documentElement.clientWidth)historyScrollbarStartY=window.scrollY;}
function notePageReaderReturn(){if(pageReaderScope&&scrollScopeMatches(pageReaderScope.project,pageReaderScope.sid,pageReaderScope.generation)){if(window.scrollY>0&&documentMaxScroll()-window.scrollY<=80){pageReaderScope=null;return;}pageReaderScope.returnY=window.scrollY;pageReaderScope.returnUntil=Date.now()+1000;}}
function noteHistoryScrollPosition(){const reader=pageReaderScope&&scrollScopeMatches(pageReaderScope.project,pageReaderScope.sid,pageReaderScope.generation);const scrollbar=historyScrollbarStartY!==null&&window.scrollY>historyScrollbarStartY;if(historyPinActive()&&scrollbar)historyScrollIntent=true;if(reader&&window.scrollY>0&&documentMaxScroll()-window.scrollY<=80&&(scrollbar||pageReaderScope.returnUntil>=Date.now()&&window.scrollY>pageReaderScope.returnY))pageReaderScope=null;}
function endHistoryScrollbarDrag(){historyScrollbarStartY=null;}

// Attention has its own request/scope clocks and contains no writer actions.
let attentionScope=0,attentionSequence=0,attentionNavigation=0;
let attentionFlight=null,attentionNavFlight=null,attentionTimer=null,attentionAgeTimer=null;
let attentionData=null,attentionProjection=null,attentionAccepted=0,attentionProjectsBlocked=false;
const attentionLimits={decision:6,question:6,completed:6,delivery:6,unlinked:6};
const attentionLabels={decision:'Требуется решение',question:'Вопрос',completed:'Работа завершена — нужна проверка',delivery:'Ответ сохранён, ожидает доставки',unlinked:'Задачи без подтверждённой сессии'};
const attentionKinds={decision:'decision',question:'question',completed:'completed',delivery:'delivery_pending'};
function attentionStrictJSON(raw){
  let at=0;
  const whitespace=()=>{while(/[\t\r\n ]/.test(raw[at]||'x'))at++;};
  function string(){const start=at++;while(at<raw.length){if(raw[at]==='\\'){at+=2;continue;}if(raw[at++]==='"')return JSON.parse(raw.slice(start,at));}throw Error('json');}
  function value(depth){
    if(depth>64)throw Error('json');whitespace();const first=raw[at];
    if(first==='"')return string();
    if(first==='{'){at++;const out=Object.create(null);whitespace();if(raw[at]==='}'){at++;return out;}while(true){whitespace();if(raw[at]!=='"')throw Error('json');const key=string();if(Object.hasOwn(out,key))throw Error('json');whitespace();if(raw[at++]!==':')throw Error('json');out[key]=value(depth+1);whitespace();const end=raw[at++];if(end==='}')return out;if(end!==',')throw Error('json');}}
    if(first==='['){at++;const out=[];whitespace();if(raw[at]===']'){at++;return out;}while(true){out.push(value(depth+1));whitespace();const end=raw[at++];if(end===']')return out;if(end!==',')throw Error('json');}}
    const match=/^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(raw.slice(at));if(!match)throw Error('json');at+=match[0].length;const out=JSON.parse(match[0]);if(typeof out==='number'&&(!Number.isSafeInteger(out)||/[.eE]/.test(match[0])))throw Error('json');return out;
  }
  const data=value(0);whitespace();if(at!==raw.length)throw Error('json');return data;
}
async function attentionRaw(response){
  const reader=response.body.getReader(),blocks=[];let size=0;
  try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>131072)throw Error('limit');blocks.push(value);}const bytes=new Uint8Array(size);let offset=0;for(const block of blocks){bytes.set(block,offset);offset+=block.length;}return attentionStrictJSON(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}
  catch(error){await reader.cancel().catch(()=>{});throw error;}
}
function attentionValid(data){
  const fail=()=>{throw Error('schema');};
  const exact=(v,keys)=>{if(!exactFields(v,keys.split(' ')))fail();};
  const integer=(v,min=0)=>{if(!Number.isSafeInteger(v)||v<min)fail();};
  const hex=(v,n=64)=>{if(typeof v!=='string'||!new RegExp('^[0-9a-f]{'+n+'}$').test(v))fail();};
  const text=(v,max)=>{if(typeof v!=='string'||!v||[...v].length>max||[...v].some(c=>{const n=c.codePointAt(0);return n<32||(n>=127&&n<=159)||(n>=55296&&n<=57343);}))fail();};
  const project=v=>{if(typeof v!=='string'||!/^[a-zA-Z0-9_-]{1,32}$/.test(v))fail();};
  const sequence=(v,max)=>{if(!Array.isArray(v)||v.length>max)fail();};
  exact(data,'schema epoch revision observed_at complete truncated sources pool sessions reasons unlinked_tasks');if(data.schema!==1)fail();hex(data.epoch,32);integer(data.revision);integer(data.observed_at,1);if(data.complete!==false||typeof data.truncated!=='boolean')fail();
  exact(data.pool,'known_sessions running decision question completed');for(const count of Object.values(data.pool)){integer(count);if(count!==0)fail();}
  sequence(data.sessions,256);if(data.sessions.length)fail();exact(data.sources,'task_registry activity native_callbacks');
  for(const [name,source] of Object.entries(data.sources)){exact(source,'state complete observed_at reason');if(!['fresh','incomplete','stale','unavailable','unsupported'].includes(source.state)||typeof source.complete!=='boolean')fail();if(source.observed_at!==null)integer(source.observed_at,1);if(![null,'binding_incomplete','unavailable','disconnected','unsupported','limit','invalid_source'].includes(source.reason))fail();if(source.complete&&(source.state!=='fresh'||source.observed_at===null||source.reason!==null))fail();if(name!=='task_registry'&&(source.state!=='unsupported'||source.complete!==false||source.observed_at!==null||source.reason!=='unsupported'))fail();}
  sequence(data.unlinked_tasks,128);sequence(data.reasons,512);const tasks=new Map(),reasons=new Map(),used=new Set(),targets=new Set(),agents=new Map();
  for(const task of data.unlinked_tasks){exact(task,'task_key project label engine reason_ids');hex(task.task_key);project(task.project);text(task.label,120);if(!['codex','claude'].includes(task.engine))fail();sequence(task.reason_ids,512);if(!task.reason_ids.length||new Set(task.reason_ids).size!==task.reason_ids.length||tasks.has(task.task_key))fail();for(const id of task.reason_ids)hex(id);tasks.set(task.task_key,task);}
  for(const reason of data.reasons){exact(reason,'reason_id session_key task_key kind source state target');hex(reason.reason_id);hex(reason.task_key);if(reason.session_key!==null||reason.source!=='task_registry'||!['decision','question','completed','delivery_pending'].includes(reason.kind)||!['pending','stale','unknown'].includes(reason.state)||reasons.has(reason.reason_id))fail();const task=tasks.get(reason.task_key);if(!task||!task.reason_ids.includes(reason.reason_id))fail();const t=reason.target;exact(t,'kind agent task_key qid result_generation');if(t.kind!=='task'||t.task_key!==reason.task_key||typeof t.agent!=='string'||!/^[a-z][a-z0-9-]{0,30}[a-z0-9]$/.test(t.agent))fail();if(reason.kind==='completed'){if(t.qid!==null)fail();hex(t.result_generation,8);}else if(typeof t.qid!=='string'||!UUID_RE.test(t.qid)||t.result_generation!==null)fail();const identity=reason.task_key+'\0'+(t.qid===null?'result:'+t.result_generation:'qid:'+t.qid);if(targets.has(identity)||(agents.has(reason.task_key)&&agents.get(reason.task_key)!==t.agent))fail();targets.add(identity);agents.set(reason.task_key,t.agent);reasons.set(reason.reason_id,reason);}
  for(const task of tasks.values())for(const id of task.reason_ids){if(!reasons.has(id)||reasons.get(id).task_key!==task.task_key||used.has(id))fail();used.add(id);}if(used.size!==reasons.size)fail();return data;
}
function attentionCanonical(value){if(Array.isArray(value))return '['+value.map(attentionCanonical).join(',')+']';if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+attentionCanonical(value[k])).join(',')+'}';return JSON.stringify(value);}
function attentionIdentity(data){const copy={...data};delete copy.observed_at;copy.sources=Object.fromEntries(Object.entries(data.sources).map(([k,v])=>{const source={...v};delete source.observed_at;return [k,source];}));return attentionCanonical(copy);}
function attentionClear(){attentionData=null;attentionProjection=null;attentionAccepted=0;for(const group of Object.keys(attentionLimits)){$('attention-'+group+'-rows').replaceChildren();attentionLimits[group]=6;}$('attention-age').textContent='';$('attention-source-status').textContent='';$('attention-truncated').hidden=true;}
function attentionCancel(){attentionSequence++;attentionNavigation++;if(attentionNavFlight){attentionNavFlight.abort();attentionNavFlight=null;}if(attentionFlight){attentionFlight.abort();attentionFlight=null;}if(attentionTimer!==null)clearTimeout(attentionTimer);attentionTimer=null;if(attentionAgeTimer!==null)clearTimeout(attentionAgeTimer);attentionAgeTimer=null;$('attention-refresh').disabled=false;}
function attentionReset(load){attentionScope++;$('refresh').disabled=false;attentionCancel();attentionClear();$('attention-status').textContent='';if(load&&csrf&&document.visibilityState==='visible')attentionTimer=setTimeout(attentionFetch,0);}
function attentionFresh(){return Boolean(document.visibilityState==='visible'&&attentionData&&performance.now()-attentionAccepted<15000&&attentionData.observed_at<=Date.now()/1000+300);}
function attentionControls(){const enabled=Boolean(csrf&&!attentionFlight&&!attentionNavFlight&&attentionFresh());document.querySelectorAll('#attention-overview button[data-attention-reason-id]').forEach(b=>{const reason=attentionData?.reasons.find(r=>r.reason_id===b.dataset.attentionReasonId);b.disabled=!enabled||reason?.state!=='pending'||b.dataset.navBusy==='true';});}
function attentionAge(){if(!attentionData)return;const age=Math.max(0,Date.now()/1000-attentionData.observed_at);$('attention-age').textContent=attentionData.observed_at>Date.now()/1000+300?'Время обновления неизвестно':performance.now()-attentionAccepted>=15000?'Обзор устарел. Обновите данные':age<60?'Обновлено менее минуты назад':'Обновлено '+Math.floor(age/60)+' мин. назад';attentionControls();if(attentionAgeTimer!==null)clearTimeout(attentionAgeTimer);attentionAgeTimer=setTimeout(attentionAge,1000);}
function attentionFocusKey(){const d=document.activeElement?.dataset;if(!attentionData||!d)return null;if(d.attentionReasonId)return {epoch:attentionData.epoch,surface:d.attentionFocusSurface,owner:d.attentionFocusOwner,kind:'reason',id:d.attentionReasonId};const group=d.attentionExpand||d.attentionGroupHeading;return group?{epoch:attentionData.epoch,surface:'group',owner:group,kind:d.attentionExpand?'expand':'heading',id:group}:null;}
function attentionRestoreFocus(key){if(!key||key.epoch!==attentionData?.epoch)return;let match;if(key.kind==='reason')match=[...document.querySelectorAll('#attention-overview button[data-attention-reason-id]')].find(b=>b.dataset.attentionReasonId===key.id&&b.dataset.attentionFocusSurface===key.surface&&b.dataset.attentionFocusOwner===key.owner&&!b.disabled);else if(key.surface==='group'){if(key.kind==='expand')match=document.querySelector('#attention-overview button[data-attention-expand="'+key.owner+'"]');if(!match)match=document.querySelector('#attention-overview [data-attention-group-heading="'+key.owner+'"]');}if(match)match.focus({preventScroll:true});}
function attentionButton(reason,surface,owner){const b=node('button','Открыть задачу','secondary');b.type='button';b.dataset.attentionReasonId=reason.reason_id;b.dataset.attentionFocusSurface=surface;b.dataset.attentionFocusOwner=owner;b.dataset.taskKey=reason.task_key;b.dataset.agent=reason.target.agent;if(reason.target.qid!==null)b.dataset.qid=reason.target.qid;if(reason.target.result_generation!==null)b.dataset.resultGeneration=reason.target.result_generation;b.addEventListener('click',()=>attentionNavigate(reason,b));return b;}
function attentionRender(focused=attentionFocusKey()){
  const taskMap=new Map(attentionData.unlinked_tasks.map(t=>[t.task_key,t]));
  for(const group of Object.keys(attentionLimits)){
    const rows=group==='unlinked'?attentionData.unlinked_tasks:attentionData.reasons.filter(r=>r.kind===attentionKinds[group]);attentionLimits[group]=Math.min(Math.max(6,attentionLimits[group]),Math.max(6,rows.length));const frag=document.createDocumentFragment();
    const unique=group==='unlinked'?rows.length:new Set(rows.map(r=>r.task_key)).size;frag.append(node('p','Задач: '+unique,'meta'));if(!rows.length)frag.append(node('p','В показанных данных нет таких задач','meta'));
    for(const row of rows.slice(0,attentionLimits[group])){const task=group==='unlinked'?row:taskMap.get(row.task_key),card=node('div',undefined,'attention-task');card.dataset.attentionTaskKey=task.task_key;card.append(node('strong',task.label),node('p',task.project+' · '+(task.engine==='codex'?'Codex':'Claude'),'meta'));
      if(group==='unlinked'){const related=task.reason_ids.map(id=>attentionData.reasons.find(r=>r.reason_id===id));for(const kind of ['decision','question','completed','delivery_pending']){const count=related.filter(r=>r.kind===kind).length;if(count)card.append(node('span',(attentionLabels[kind==='delivery_pending'?'delivery':kind])+': '+count,'badge'));}const pending=related.filter(r=>r.state==='pending').sort((a,b)=>['decision','question','completed','delivery_pending'].indexOf(a.kind)-['decision','question','completed','delivery_pending'].indexOf(b.kind))[0];if(pending)card.append(attentionButton(pending,'task-card',task.task_key));else{const b=node('button','Открыть задачу','secondary');b.type='button';b.disabled=true;card.append(b);}}
      else{const badge=node('span',attentionLabels[group],'badge');badge.dataset.attentionKind=row.kind;badge.dataset.attentionState=row.state;card.append(badge);if(row.state!=='pending')card.append(node('span',row.state==='stale'?'Данные устарели':'Статус неизвестен','badge'));card.append(attentionButton(row,'group',group));}frag.append(card);}
    if(rows.length>attentionLimits[group]){const b=node('button','Показать ещё — '+attentionLabels[group],'secondary');b.type='button';b.dataset.attentionExpand=group;b.setAttribute('aria-expanded',String(attentionLimits[group]>6));b.setAttribute('aria-controls','attention-'+group+'-rows');b.addEventListener('click',()=>{attentionLimits[group]=Math.min(rows.length,attentionLimits[group]+6);attentionRender();});frag.append(b);}
    $('attention-'+group+'-rows').replaceChildren(frag);
  }
  $('attention-truncated').hidden=!attentionData.truncated;attentionControls();attentionRestoreFocus(focused);
}
async function attentionFetch(){
  if(!csrf||document.visibilityState!=='visible'||attentionFlight||$('projects-refresh').disabled)return;
  if(attentionProjectsBlocked){$('attention-status').textContent='Обзор пока недоступен';return;}
  attentionNavigation++;if(attentionNavFlight){attentionNavFlight.abort();attentionNavFlight=null;}if(attentionTimer!==null)clearTimeout(attentionTimer);attentionTimer=null;
  const auth=chatAuthGeneration,scope=attentionScope,sequence=++attentionSequence,controller=new AbortController();attentionFlight=controller;
  const current=()=>Boolean(csrf&&auth===chatAuthGeneration&&scope===attentionScope&&sequence===attentionSequence&&attentionFlight===controller&&document.visibilityState==='visible');
  const focused=attentionFocusKey();const timeout=setTimeout(()=>controller.abort(),6000);$('attention-refresh').disabled=true;$('attention-status').textContent='Обновляем обзор…';attentionControls();
  try{const response=await fetch('/api/attention',{credentials:'same-origin',signal:controller.signal});if(!current())return;if(response.status===401){signedOut();return;}if(!response.ok)throw Error('unavailable');const data=attentionValid(await attentionRaw(response));if(!current()||controller.signal.aborted)return;const projection=attentionIdentity(data),old=attentionData;
    if(old&&old.epoch===data.epoch&&(data.revision<old.revision||(data.revision===old.revision&&projection!==attentionProjection)))throw Error('revision');
    const changed=!old||old.epoch!==data.epoch||old.revision!==data.revision;
    if(old&&old.epoch!==data.epoch){for(const group of Object.keys(attentionLimits))attentionLimits[group]=6;const focused=document.activeElement;if($('attention-overview').contains(focused))focused.blur();}
    attentionData=data;attentionProjection=projection;attentionAccepted=performance.now();if(changed)attentionRender(focused);
    $('attention-source-status').textContent=(data.sources.task_registry.state==='fresh'?'Задачи: свежие данные':'Задачи: некоторые данные пока недоступны')+' · Наблюдение за сессиями пока недоступно · Сигналы сессий пока недоступны';
    $('attention-status').textContent='Показаны доступные данные'+(Object.values(data.sources).some(s=>['stale','incomplete','unavailable'].includes(s.state))?' · Некоторые данные пока недоступны':'');attentionAge();
  }catch(_){if(current()){attentionClear();$('attention-status').textContent='Обзор пока недоступен';}}
  finally{clearTimeout(timeout);if(current()){attentionFlight=null;$('attention-refresh').disabled=false;attentionControls();attentionRestoreFocus(focused);attentionTimer=setTimeout(attentionFetch,5000);}}
}
async function attentionNavigate(reason,button){
  if(button.disabled||!attentionFresh()||attentionFlight||attentionNavFlight)return;
  const auth=chatAuthGeneration,scope=attentionScope,sequence=attentionSequence,nav=++attentionNavigation,epoch=attentionData.epoch,revision=attentionData.revision,request=++tasksRequest;
  const current=()=>Boolean(csrf&&auth===chatAuthGeneration&&scope===attentionScope&&sequence===attentionSequence&&nav===attentionNavigation&&attentionData?.epoch===epoch&&attentionData?.revision===revision&&request===tasksRequest&&attentionFresh());
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),6000);attentionNavFlight=controller;button.dataset.navBusy='true';attentionControls();
  try{const data=await api('/api/tasks',undefined,controller.signal,current);if(!current())return;const target=reason.target,task=data.tasks?.find(t=>t.task_key===reason.task_key&&t.agent===target.agent&&t.unavailable!==true);let valid=false;
    if(task){if(reason.kind==='completed')valid=task.result?.generation===target.result_generation&&task.result.state==='requested'&&task.result.finalized===true;else{const q=task.questions?.find(q=>q.qid===target.qid);valid=Boolean(q&&(reason.kind==='delivery_pending'?q.answered===true&&q.pending_delivery===true:q.status==='open'&&q.answered===false&&q.kind===(reason.kind==='decision'?'permission':'info')));}}
    if(!valid)throw Error('stale');if(!current())return;renderTasks(data);
    const card=[...$('cards').querySelectorAll('article.card')].find(c=>c.dataset.agent===target.agent&&c.dataset.taskKey===reason.task_key);const dest=target.qid!==null?card?.querySelector('[data-qid="'+target.qid+'"]'):card?.querySelector('[data-result-generation="'+target.result_generation+'"]');if(!dest)throw Error('stale');if(!current())return;
    showTab('tasks',false);dest.tabIndex=-1;dest.scrollIntoView({block:'center'});dest.focus({preventScroll:true});
  }catch(_){if(current())$('attention-status').textContent='Задача изменилась. Обновите обзор';}
  finally{clearTimeout(timeout);if(attentionNavFlight===controller){attentionNavFlight=null;if(current()){delete button.dataset.navBusy;attentionControls();}}}
}
$('attention-refresh').addEventListener('click',attentionFetch);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState!=='visible'){attentionCancel();attentionControls();}else if(csrf)attentionFetch();});

$('login-form').addEventListener('submit',async event=>{event.preventDefault();if(busy)return;busy=true;const b=event.target.querySelector('button');b.disabled=true;notice('Входим…');try{const data=await api('/api/login',{password:$('password').value,totp:$('login-totp').value});csrf=data.csrf;$('password').value='';$('login-totp').value='';$('login').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;const link=parseDeepLink();if(link){showTab('sessions',false);await loadProjects();}else{showTab('tasks',false);updateUrl();await refresh();}}catch(err){notice(err.message);}finally{busy=false;b.disabled=false;}});
$('refresh').addEventListener('click',refresh);
$('logout').addEventListener('click',async()=>{attentionReset(false);try{await api('/api/logout',{});signedOut();drafts.clear();receipts.clear();latestAttempts.clear();historyData.clear();sessionRows=[];$('cards').replaceChildren();$('session-list').replaceChildren();clearHistoryView();updateUrl();notice('Вы вышли из Control.');}catch(err){notice(err.message);}});
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
document.addEventListener('wheel',noteHistoryScrollIntent,{passive:true});
document.addEventListener('touchstart',noteHistoryScrollIntent,{passive:true});
document.addEventListener('touchmove',noteHistoryScrollIntent,{passive:true});
document.addEventListener('keydown',noteHistoryScrollIntent);
document.addEventListener('pointerdown',noteHistoryScrollIntent,{passive:true});
document.addEventListener('pointerup',endHistoryScrollbarDrag,{passive:true});
document.addEventListener('pointercancel',endHistoryScrollbarDrag,{passive:true});
window.addEventListener('scroll',noteHistoryScrollPosition,{passive:true});

async function restoreSession(){if(busy)return;busy=true;const retry=$('session-retry');retry.hidden=true;retry.disabled=true;$('session-loading').hidden=false;$('login').hidden=true;$('workspace').hidden=true;$('logout').hidden=true;notice('Восстанавливаем сессию…');try{const data=await api('/api/session');if(typeof data.csrf!=='string'||!data.csrf)throw new Error(messages.unavailable);csrf=data.csrf;$('session-loading').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;notice('');const link=parseDeepLink();if(link){showTab('sessions',false);await loadProjects();}else{showTab('tasks',false);updateUrl();await refresh();}}catch(err){if(err.status===401){signedOut();notice('');}else{notice(err.message+' Повторите восстановление сессии.');retry.hidden=false;}}finally{busy=false;retry.disabled=false;}}
$('session-retry').addEventListener('click',restoreSession);
restoreSession();
