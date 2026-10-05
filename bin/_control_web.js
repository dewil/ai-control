'use strict';
const $ = id => document.getElementById(id);
let csrf = '';
let busy = false;
let taskLoaded = false;
const drafts = new Map();
const receipts = new Map();
const latestAttempts = new Map();
const sendsInFlight = new Set();
const statusChecks = new Set();
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
    if(text[i]==='<'&&/^<\/?[a-zA-Z!]/.test(text.slice(i,i+3)))return true;
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
async function api(path,body){let response;try{response=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});}catch(_){throw new Error(messages.unavailable);}let data;try{data=await response.json();}catch(_){throw new Error(messages.unavailable);}if(!response.ok){if(response.status===401&&path!=='/api/login')signedOut();const error=new Error(messages[data.error]||messages.unavailable);error.code=data.error;error.status=response.status;error.data=data;throw error;}return data;}
function signedOut(){csrf='';taskLoaded=false;stopPolling();selectionGeneration++;initialScrollTarget=null;clearHistoryScrollSlack();selectedSession=null;selectedProject='';projectNames=[];availableProjects=new Set();sessionRows=[];drafts.clear();receipts.clear();latestAttempts.clear();historyData.clear();$('session-loading').hidden=true;$('workspace').hidden=true;$('login').hidden=false;$('logout').hidden=true;$('session-list').replaceChildren();$('cards').replaceChildren();updateUrl();syncCurrentSessionControls();}
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
let selectionGeneration=0;
let initialScrollTarget=null;
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
let pollTimer=null;
const UUID_RE=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
function chatKey(project,sid){return project+'\u0000'+sid;}
function ensureReceipts(key){if(!receipts.has(key))receipts.set(key,new Map());return receipts.get(key);}
function queryPath(path,values){const params=new URLSearchParams();for(const [k,v] of Object.entries(values)){if(v!==undefined&&v!==null)params.set(k,String(v));}return path+'?'+params.toString();}
function activeSelection(project=selectedProject,sid=selectedSession&&selectedSession.sid,generation=selectionGeneration){return Boolean(csrf&&currentTab==='sessions'&&selectedSession&&selectedProject===project&&selectedSession.sid===sid&&selectionGeneration===generation);}
function updateUrl(){const params=new URLSearchParams();if(selectedProject)params.set('project',selectedProject);if(selectedSession)params.set('sid',selectedSession.sid);const query=params.toString();history.replaceState(null,'',location.pathname+(query?'?'+query:''));}
function parseDeepLink(){const params=new URLSearchParams(location.search);if(params.getAll('project').length>1||params.getAll('sid').length>1)return null;const project=params.get('project')||'';const sid=params.get('sid')||'';if(!project&&!sid)return null;if(!project||!UUID_RE.test(sid))return null;return {project,sid};}
function stopPolling(){if(pollTimer!==null){clearInterval(pollTimer);pollTimer=null;}}
function startPolling(){stopPolling();if(currentTab==='sessions'&&selectedSession&&document.visibilityState==='visible'&&csrf)pollTimer=setInterval(()=>{if(document.visibilityState==='visible'&&selectedSession)loadHistory(false);},5000);}
function currentSessionKey(){return selectedProject&&selectedSession?chatKey(selectedProject,selectedSession.sid):null;}
function syncCurrentSessionControls(){const key=currentSessionKey();const historyBusy=Boolean(key&&historyFlights.has(key));const state=key&&historyData.get(key);const hasOlder=Boolean(state&&state.olderAnchors.some(anchor=>!anchor.error));$('chat-send').disabled=!csrf||currentTab!=='sessions'||!key||sendsInFlight.has(key);$('chat-refresh').disabled=!key||historyBusy;$('history-older').disabled=!key||historyBusy||!hasOlder;if(key){const attempt=latestAttempts.get(key);$('send-status').textContent=attempt?(attempt.localError||statusText(attempt.status)):'';}else $('send-status').textContent='';}
function showTab(tab,load=true){currentTab=tab;const tasks=tab==='tasks';if(tasks)clearHistoryScrollSlack();$('tab-tasks').setAttribute('aria-selected',String(tasks));$('tab-sessions').setAttribute('aria-selected',String(!tasks));$('tasks-panel').hidden=!tasks;$('sessions-panel').hidden=tasks;syncCurrentSessionControls();if(tasks){stopPolling();if(load&&!taskLoaded)refresh();}else{if(load&&!projectNames.length)loadProjects();else if(load&&!selectedProject)loadSessionList(0,false);startPolling();}}
function setSessionStatus(text){$('session-list-status').textContent=text;}
function clearUnavailableProject(name,select){stopPolling();selectionGeneration++;initialScrollTarget=null;selectedProject=name||'';selectedSession=null;sessionRows=[];sessionPage=0;sessionsHaveMore=false;clearHistoryView();$('session-list').replaceChildren();$('sessions-more').hidden=true;if(select)select.value=name||'';updateUrl();syncCurrentSessionControls();}
function projectChanged(){const select=$('project-select');selectedProject=select.value;if(selectedProject&&!availableProjects.has(selectedProject)){clearUnavailableProject(selectedProject,select);setSessionStatus('Проект недоступен. Выберите другой проект.');return;}sessionPage=0;sessionRows=[];selectedSession=null;selectionGeneration++;initialScrollTarget=null;clearHistoryView();$('session-list').replaceChildren();updateUrl();stopPolling();if(selectedProject)loadSessionList(0,false);else setSessionStatus('Выберите проект, чтобы увидеть сессии.');}
async function loadProjects(){if(!csrf)return;const generation=selectionGeneration;setSessionStatus('Загружаем проекты…');$('project-select').disabled=true;$('projects-refresh').disabled=true;try{const data=await api('/api/session-projects');if(!csrf||generation!==selectionGeneration)return;const entries=Array.isArray(data.projects)?data.projects.filter(x=>x&&typeof x.name==='string'):[];projectNames=entries.map(x=>x.name);availableProjects=new Set(entries.filter(x=>x.unavailable!==true).map(x=>x.name));const select=$('project-select');select.replaceChildren(node('option','Выберите проект'));select.firstElementChild.value='';for(const entry of entries){const unavailable=entry.unavailable===true;const option=node('option',unavailable?entry.name+' — недоступен':entry.name);option.value=entry.name;option.disabled=unavailable;select.append(option);}select.disabled=false;const link=parseDeepLink();if(link){const linked=entries.find(entry=>entry.name===link.project);if(!linked){clearUnavailableProject('',select);setSessionStatus('Проект из ссылки недоступен. Выберите доступный проект.');return;}selectedProject=link.project;select.value=selectedProject;if(linked.unavailable===true){clearUnavailableProject(link.project,select);setSessionStatus('Проект недоступен. Выберите другой проект.');return;}await loadSessionList(0,false,link.sid);updateUrl();return;}const selected=entries.find(entry=>entry.name===selectedProject);if(selected){select.value=selected.name;if(selected.unavailable===true){clearUnavailableProject(selected.name,select);setSessionStatus('Проект недоступен. Выберите другой проект.');return;}await loadSessionList(0,false);}else{const hadSelection=Boolean(selectedProject||selectedSession);clearUnavailableProject('',select);setSessionStatus(hadSelection?'Выбранный проект больше недоступен. Выберите доступный проект.':projectNames.length?'Выберите проект, чтобы увидеть сессии.':'Нет доступных проектов.');}updateUrl();}catch(_){if(generation===selectionGeneration)setSessionStatus('Список проектов недоступен. Нажмите «Обновить проекты», чтобы повторить.');$('project-select').disabled=false;}finally{$('projects-refresh').disabled=false;}}
async function loadSessionList(page=0,append=false,deepSid=null){const project=selectedProject;if(!project||!availableProjects.has(project))return;const generation=selectionGeneration;setSessionStatus(deepSid?'Ищем выбранную сессию…':'Загружаем сессии…');$('sessions-more').disabled=true;try{const data=await api(queryPath('/api/sessions',{project,page}));if(project!==selectedProject||generation!==selectionGeneration)return;const rows=Array.isArray(data.rows)?data.rows:[];sessionPage=page;sessionsHaveMore=data.has_more===true;sessionRows=append?sessionRows.concat(rows):rows;renderSessions();$('sessions-more').hidden=!sessionsHaveMore;if(deepSid){const found=rows.find(row=>row&&row.sid===deepSid);if(found){openChat(found);return;}if(sessionsHaveMore&&page<99)return loadSessionList(page+1,false,deepSid);setSessionStatus('Сессия из ссылки не найдена среди доступных сессий. Выберите другую из списка.');}else setSessionStatus(sessionRows.length?'Выберите сессию для переписки.':'В этом проекте пока нет доступных сессий.');}catch(_){if(project===selectedProject&&generation===selectionGeneration)setSessionStatus('Список сессий недоступен. Попробуйте ещё раз.');}finally{$('sessions-more').disabled=false;}}
function renderSessions(){const list=$('session-list');const frag=document.createDocumentFragment();for(const row of sessionRows){if(!row||typeof row.sid!=='string'||!UUID_RE.test(row.sid))continue;const b=node('button',undefined,'session-choice'+(selectedSession&&selectedSession.sid===row.sid?' selected':''));b.type='button';b.setAttribute('aria-pressed',String(Boolean(selectedSession&&selectedSession.sid===row.sid)));b.append(node('span',row.title||'Codex','session-title'));b.append(node('span',statusLabel(row.status),'meta'));if(row.needs_native_attention===true)b.append(node('span','Нужно действие в клиенте Codex; ответы из панели пока недоступны.','attention-inline'));b.addEventListener('click',()=>openChat(row));frag.append(b);}list.replaceChildren(frag);}
function statusLabel(status){const labels={active:'Работает',idle:'Ожидает',notLoaded:'Недоступна',systemError:'Ошибка',completed:'Завершён',interrupted:'Прерван',failed:'Ошибка',inProgress:'Выполняется'};return labels[status]||'Состояние неизвестно';}
function chatError(err){if(err&&err.code==='stale')return 'Сессия устарела или изменилась. Обновите список и выберите её снова.';return err&&err.message||messages.unavailable;}
function clearHistoryScrollSlack(){historyScrollSlack=0;pinnedHistoryScope=null;historyScrollIntent=false;historyTouchY=null;historyScrollbarStartY=null;if(historyScrollSpacer){historyScrollSpacer.remove();historyScrollSpacer=null;}}
function setHistoryScrollSlack(height){const bounded=Math.max(0,Math.min(window.innerHeight,Math.ceil(height)));historyScrollSlack=bounded;if(!bounded){clearHistoryScrollSlack();return;}if(!historyScrollSpacer){historyScrollSpacer=node('li',undefined,'history-scroll-slack');historyScrollSpacer.setAttribute('aria-hidden','true');historyScrollSpacer.append(document.createElementNS('http://www.w3.org/2000/svg','svg'));}const svg=historyScrollSpacer.firstElementChild;svg.setAttribute('width','0');svg.setAttribute('height',String(bounded));svg.setAttribute('focusable','false');const list=$('chat-items');if(historyScrollSpacer.parentNode!==list)list.append(historyScrollSpacer);}
function clearHistoryView(){clearHistoryScrollSlack();historyData.delete(chatKey(selectedProject,selectedSession&&selectedSession.sid||''));$('chat-panel').hidden=true;$('chat-items').replaceChildren();$('receipt-list').replaceChildren();$('history-status').textContent='';$('send-status').textContent='';$('history-truncated').hidden=true;$('native-attention').hidden=true;$('chat-draft').value='';}
function openChat(row){if(!row||!UUID_RE.test(row.sid))return;stopPolling();clearHistoryScrollSlack();selectionGeneration++;selectedSession={sid:row.sid,title:typeof row.title==='string'?row.title:'Codex',needs:row.needs_native_attention===true};initialScrollTarget={project:selectedProject,sid:row.sid,generation:selectionGeneration};$('chat-title').textContent=selectedSession.title;$('chat-panel').hidden=false;$('history-status').textContent='Загружаем переписку…';$('chat-items').replaceChildren();$('receipt-list').replaceChildren();$('history-truncated').hidden=true;$('native-attention').hidden=!selectedSession.needs;$('chat-draft').value=drafts.get(chatKey(selectedProject,row.sid))||'';updateUrl();renderSessions();renderReceipts();syncCurrentSessionControls();loadHistory(false);startPolling();}
function normalizeHistoryState(key){if(!historyData.has(key))historyData.set(key,{turns:new Map(),order:[],olderAnchors:[],initialized:false,truncated:false,attention:false,paginationError:''});return historyData.get(key);}
function validHistoryId(value){return typeof value==='string'&&value.length>0&&value.length<=500;}
function mergeHistory(key,data,olderAnchor){const state=normalizeHistoryState(key);const incoming=Array.isArray(data.turns)?data.turns:[];const chronological=incoming.slice().reverse().filter(turn=>turn&&validHistoryId(turn.id));const incomingIds=new Set(chronological.map(turn=>turn.id));const existingIds=new Set(state.order);const hadOverlap=chronological.some(turn=>existingIds.has(turn.id));for(const turn of chronological){const previous=state.turns.get(turn.id);const itemMap=new Map();for(const item of (previous&&previous.items)||[])if(validHistoryId(item&&item.id))itemMap.set(item.id,item);for(const item of (Array.isArray(turn.items)?turn.items:[])){if(item&&validHistoryId(item.id))itemMap.set(item.id,item);}state.turns.set(turn.id,{...turn,items:[...itemMap.values()]});}
  const ids=chronological.map(turn=>turn.id).filter((id,i,a)=>a.indexOf(id)===i);if(olderAnchor){const anchorIndex=state.olderAnchors.indexOf(olderAnchor);const originalOrder=state.order;const overlapId=ids.find(id=>existingIds.has(id));const boundaryId=overlapId||olderAnchor.afterId;const boundaryIndex=boundaryId===null?-1:originalOrder.indexOf(boundaryId);const insertAt=boundaryIndex<0?0:originalOrder.slice(0,boundaryIndex).filter(id=>!incomingIds.has(id)).length;state.order=originalOrder.filter(id=>!incomingIds.has(id));state.order.splice(insertAt,0,...ids.filter(id=>!state.order.includes(id)));if(anchorIndex>=0){if(data.next_cursor){if(olderAnchor.seen.has(data.next_cursor)){olderAnchor.error=true;state.paginationError='Продолжение истории недоступно: сервер повторил cursor.';}else{state.olderAnchors[anchorIndex]={cursor:data.next_cursor,afterId:ids[0]||olderAnchor.afterId,seen:new Set([...olderAnchor.seen,data.next_cursor]),error:false};}}else state.olderAnchors.splice(anchorIndex,1);}}else{state.order=[...state.order.filter(id=>!incomingIds.has(id)),...ids];if(!state.initialized){state.olderAnchors=[];if(data.next_cursor)state.olderAnchors.push({cursor:data.next_cursor,afterId:ids[0]||state.order[0]||null,seen:new Set([data.next_cursor]),error:false});state.initialized=true;}else if(data.next_cursor&&!hadOverlap&&!state.olderAnchors.some(anchor=>anchor.cursor===data.next_cursor)){state.olderAnchors.push({cursor:data.next_cursor,afterId:ids[0]||state.order[0]||null,seen:new Set([data.next_cursor]),error:false});}}
  state.paginationError=state.olderAnchors.some(anchor=>anchor.error)?'Продолжение истории недоступно: сервер повторил cursor.':'';
  state.truncated=state.truncated||data.truncated===true;state.attention=data.needs_native_attention===true;for(const receipt of Array.isArray(data.recent_sends)?data.recent_sends:[])applyReceipt(key,receipt);return state;}
function scrollScopeMatches(project,sid,generation){return activeSelection(project,sid,generation)&&document.visibilityState==='visible';}
function scrollToDocumentBottom(){clearHistoryScrollSlack();const root=document.documentElement;const body=document.body;const height=Math.max(root?root.scrollHeight:0,body?body.scrollHeight:0);window.scrollTo(0,Math.max(0,height-window.innerHeight));}
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
      return {context,occurrence,top:point.top};
    }
  }
  return null;
}
function resolveMarkdownAnchor(article,anchor){
  if(!anchor)return null;const content=markdownTextNodes(article);if(!content)return null;
  let index=-1;for(let i=0;i<=anchor.occurrence;i++){index=content.text.indexOf(anchor.context,index+1);if(index<0)return null;}
  const entry=content.entries.find(entry=>index>=entry.start&&index<entry.start+entry.node.length);
  return entry?markdownCharRange(entry.node,index-entry.start):null;
}
function captureHistoryScroll(project,sid,generation,older){if(!scrollScopeMatches(project,sid,generation))return null;const initial=initialScrollTarget&&initialScrollTarget.project===project&&initialScrollTarget.sid===sid&&initialScrollTarget.generation===generation;if(initial&&!older)return {kind:'bottom',initial:true};const distance=documentMaxScroll()-window.scrollY;const pinned=pinnedHistoryScope&&pinnedHistoryScope.project===project&&pinnedHistoryScope.sid===sid&&pinnedHistoryScope.generation===generation&&historyScrollSlack>0;if(!older&&(!pinned&&distance<=80||pinned&&historyScrollIntent&&distance<=80)){historyScrollIntent=false;return {kind:'bottom'};}historyScrollIntent=false;for(const article of $('chat-items').querySelectorAll('article.chat-message')){const rect=article.getBoundingClientRect();if(rect.bottom>0&&rect.top<window.innerHeight)return {kind:'anchor',turnId:article.dataset.turnId,itemId:article.dataset.itemId,top:rect.top,y:window.scrollY,inner:captureMarkdownAnchor(article)};}return {kind:'position',y:window.scrollY};}
function restoreHistoryScroll(decision,project,sid,generation){if(!decision||!scrollScopeMatches(project,sid,generation))return;if(decision.kind==='bottom'){scrollToDocumentBottom();if(decision.initial)initialScrollTarget=null;return;}const findAnchor=()=>decision.kind==='anchor'?[...$('chat-items').querySelectorAll('article.chat-message')].find(article=>article.dataset.turnId===decision.turnId&&article.dataset.itemId===decision.itemId):null;const article=findAnchor();const inner=article&&resolveMarkdownAnchor(article,decision.inner);const anchor=inner||article;const anchorTop=inner?decision.inner.top:decision.top;let target=anchor?Math.max(0,window.scrollY+anchor.getBoundingClientRect().top-anchorTop):Math.max(0,decision.y);const root=document.documentElement;const body=document.body;let maxHeight=Math.max(root?root.scrollHeight:0,body?body.scrollHeight:0);let naturalMax=Math.max(0,maxHeight-window.innerHeight-historyScrollSlack);setHistoryScrollSlack(Math.max(0,target-naturalMax));window.scrollTo(0,target);for(let i=0;i<3&&anchor;i++){const difference=anchor.getBoundingClientRect().top-anchorTop;if(Math.abs(difference)<=0.5)break;target=Math.max(0,window.scrollY+difference);maxHeight=Math.max(root?root.scrollHeight:0,body?body.scrollHeight:0);const maxScroll=Math.max(0,maxHeight-window.innerHeight);if(target>maxScroll&&historyScrollSlack<window.innerHeight)setHistoryScrollSlack(historyScrollSlack+Math.min(window.innerHeight-historyScrollSlack,target-maxScroll+1));window.scrollTo(0,target);}if(historyScrollSlack){pinnedHistoryScope={project,sid,generation};historyScrollIntent=false;}else pinnedHistoryScope=null;}
async function loadHistory(older=false){if(!selectedSession||!selectedProject)return;const project=selectedProject,sid=selectedSession.sid,key=chatKey(project,sid),generation=selectionGeneration;const existing=historyFlights.get(key);if(existing){if(existing.generation===generation)return existing.promise;await existing.promise;if(activeSelection(project,sid,generation))return loadHistory(older);return;}const state=normalizeHistoryState(key);const anchor=older?[...state.olderAnchors].reverse().find(candidate=>!candidate.error):null;if(older&&!anchor)return;const cursor=anchor?anchor.cursor:null;const path=queryPath('/api/session-history',{project,sid,cursor});$('chat-refresh').disabled=true;if(older)$('history-older').disabled=true;const promise=(async()=>{try{const data=await api(path);if(!activeSelection(project,sid,generation))return;const scrollDecision=captureHistoryScroll(project,sid,generation,older);mergeHistory(key,data,anchor);renderHistory(key);$('history-status').textContent=state.paginationError;historyFlights.delete(key);syncCurrentSessionControls();restoreHistoryScroll(scrollDecision,project,sid,generation);}catch(err){if(activeSelection(project,sid,generation))$('history-status').textContent=chatError(err)+' История и черновик сохранены.';}finally{historyFlights.delete(key);syncCurrentSessionControls();}})();historyFlights.set(key,{generation,promise});syncCurrentSessionControls();return promise;}
function renderHistory(key){const state=normalizeHistoryState(key);const list=$('chat-items');const frag=document.createDocumentFragment();let visible=0;for(const id of state.order){const turn=state.turns.get(id);if(!turn)continue;const group=node('li',undefined,'turn');const heading=node('p','Ход: '+statusLabel(turn.status),'turn-status');group.append(heading);for(const item of turn.items||[]){if(!item||typeof item.text!=='string'||!['user','assistant'].includes(item.role))continue;const article=node('article',undefined,'chat-message '+(item.role==='user'?'from-user':'from-assistant'));article.dataset.turnId=id;article.dataset.itemId=item.id;article.append(node('h3',item.role==='user'?'Вы':'Codex'));article.append(renderMarkdown(item.text));if(item.truncated===true)article.append(node('span','Сообщение сокращено','meta'));group.append(article);visible++;}frag.append(group);}if(!visible)frag.append(node('li','Пока нет отображаемых текстовых сообщений.','meta'));list.replaceChildren(frag);if(historyScrollSlack)setHistoryScrollSlack(historyScrollSlack);$('history-truncated').hidden=!(state.truncated||[...state.turns.values()].some(turn=>(turn.items||[]).some(item=>item.truncated===true)));$('history-older').hidden=!state.olderAnchors.length;$('history-older').disabled=!state.olderAnchors.some(anchor=>!anchor.error);$('native-attention').hidden=!(state.attention||(selectedSession&&selectedSession.needs));renderReceipts(key);}
function statusText(status){return status==='accepted'?'Сообщение принято Codex; работа может продолжаться.':status==='rejected'?'Codex отклонил сообщение; черновик сохранён.':status==='delivery_unknown'?'Доставка неизвестна. Проверьте статус вручную; отправка не повторяется автоматически.':status==='sending'?'Отправляем сообщение…':'Статус сообщения недоступен.';}
function renderReceipts(key=chatKey(selectedProject,selectedSession&&selectedSession.sid||'')){const list=$('receipt-list');if(!list||!selectedSession||key!==chatKey(selectedProject,selectedSession.sid))return;const records=ensureReceipts(key);list.replaceChildren();const heading=node('h3','Недавние отправки');list.append(heading);if(!records.size){list.append(node('p','Пока нет отправок для проверки.','meta'));return;}for(const [id,record] of [...records.entries()].slice(-8).reverse()){const row=node('div',undefined,'receipt-row');const label=node('span',statusText(record.status),'receipt-label');row.append(label);if(record.status==='delivery_unknown'){const check=node('button','Проверить доставку','secondary');check.type='button';check.disabled=statusChecks.has(key+'\u0000'+id);check.addEventListener('click',()=>checkDelivery(key,id));row.append(check);}list.append(row);}}
function hasUnknown(key){return [...ensureReceipts(key).values()].some(entry=>entry.status==='delivery_unknown');}
async function checkDelivery(key,id){if(statusChecks.has(key+'\u0000'+id))return;const [project,sid]=key.split('\u0000');if(project!==selectedProject||!selectedSession||sid!==selectedSession.sid)return;const generation=selectionGeneration,mark=key+'\u0000'+id;statusChecks.add(mark);renderReceipts(key);try{const data=await api(queryPath('/api/session-send-status',{project,sid,message_id:id}));if(!activeSelection(project,sid,generation))return;applyReceipt(key,data);const attempt=latestAttempts.get(key);$('send-status').textContent=attempt&&attempt.id===id?statusText(attempt.status):statusText(data.status);renderReceipts(key);}catch(err){if(activeSelection(project,sid,generation))$('send-status').textContent=err.code==='stale'?'Эта отправка больше недоступна для проверки. Черновик сохранён.':chatError(err)+' Повторите ручную проверку.';}finally{statusChecks.delete(mark);if(activeSelection(project,sid,generation))renderReceipts(key);}}
function applyReceipt(key,data){if(!data||!['accepted','delivery_unknown','rejected'].includes(data.status)||!UUID_RE.test(data.message_id||''))return;const id=data.message_id,map=ensureReceipts(key),existing=map.get(id),attempt=latestAttempts.get(key);const terminal=existing&&['accepted','rejected'].includes(existing.status)?existing:attempt&&attempt.id===id&&['accepted','rejected'].includes(attempt.status)?{status:attempt.status,turn_id:existing&&existing.turn_id||null}:null;if(terminal){map.set(id,terminal);if(attempt&&attempt.id===id)attempt.status=terminal.status;return;}const record={status:data.status,turn_id:data.turn_id||null};map.set(id,record);if(attempt&&attempt.id===id){attempt.status=data.status;delete attempt.localError;}else if(data.status==='delivery_unknown'&&!attempt)latestAttempts.set(key,{id,text:null,status:data.status});}
async function submitMessage(event){event.preventDefault();if(!selectedSession||!selectedProject)return;const project=selectedProject,sid=selectedSession.sid,key=chatKey(project,sid),generation=selectionGeneration,text=$('chat-draft').value;if(!text.trim()){$('send-status').textContent='Напишите сообщение перед отправкой.';return;}if(sendsInFlight.has(key))return;if(hasUnknown(key)){const attempt=latestAttempts.get(key);$('send-status').textContent=attempt&&attempt.text===text?'Для этой попытки уже сохранён ID. Проверьте доставку вручную.':'Сначала проверьте неизвестную доставку. Новый текст пока не отправлен.';renderReceipts(key);return;}let attempt=latestAttempts.get(key);if(!attempt||attempt.text!==text||['accepted','rejected'].includes(attempt.status)){attempt={id:crypto.randomUUID(),text,status:'sending'};latestAttempts.set(key,attempt);ensureReceipts(key).set(attempt.id,{status:'sending',turn_id:null});}else if(attempt.status==='delivery_unknown'){$('send-status').textContent='Проверьте доставку вручную; повторная отправка отключена.';return;}else{attempt.status='sending';}
  sendsInFlight.add(key);syncCurrentSessionControls();$('send-status').textContent='Отправляем сообщение…';renderReceipts(key);if(scrollScopeMatches(project,sid,generation))scrollToDocumentBottom();try{let result;try{result=await api('/api/session-send',{project,sid,message_id:attempt.id,text});}catch(err){if(!csrf)return;if(err.data&&['accepted','rejected','delivery_unknown'].includes(err.data.status))result=err.data;else if(['invalid_request','forbidden','unauthorized','stale'].includes(err.code)){attempt.status='rejected';attempt.localError=err.message+' Черновик сохранён; отправка не повторялась.';ensureReceipts(key).delete(attempt.id);if(activeSelection(project,sid,generation))$('send-status').textContent=attempt.localError;return;}else{result={status:'delivery_unknown',message_id:attempt.id,turn_id:null};}}if(!result.message_id)result.message_id=attempt.id;applyReceipt(key,result);if(!ensureReceipts(key).has(attempt.id))applyReceipt(key,{status:'delivery_unknown',message_id:attempt.id,turn_id:null});attempt.status=ensureReceipts(key).get(attempt.id).status;if(attempt.status==='accepted'&&drafts.get(key)===text){drafts.delete(key);if(activeSelection(project,sid,generation)&&$('chat-draft').value===text)$('chat-draft').value='';}if(activeSelection(project,sid,generation)){$('send-status').textContent=statusText(attempt.status);renderReceipts(key);}}finally{sendsInFlight.delete(key);syncCurrentSessionControls();}}
function historyChange(){if(document.visibilityState==='hidden')stopPolling();else startPolling();}
function historyPinActive(){return Boolean(historyScrollSlack&&pinnedHistoryScope&&selectedSession&&pinnedHistoryScope.project===selectedProject&&pinnedHistoryScope.sid===selectedSession.sid&&pinnedHistoryScope.generation===selectionGeneration);}
function noteHistoryScrollIntent(event){if(!historyPinActive())return;if(event.type==='wheel'){if(event.deltaY>0)historyScrollIntent=true;return;}if(event.type==='touchstart'){historyTouchY=event.touches&&event.touches.length?event.touches[0].clientY:null;return;}if(event.type==='touchmove'){const y=event.touches&&event.touches.length?event.touches[0].clientY:null;if(y!==null&&historyTouchY!==null&&y<historyTouchY)historyScrollIntent=true;historyTouchY=y;return;}if(event.type==='keydown'){const target=event.target;if(target&&(['INPUT','TEXTAREA','SELECT','BUTTON'].includes(target.tagName)||target.isContentEditable))return;if(!['ArrowDown','PageDown','End'].includes(event.key)&&!(event.key===' '&&!event.shiftKey))return;historyScrollIntent=true;return;}if(event.type==='pointerdown'&&event.clientX>=document.documentElement.clientWidth)historyScrollbarStartY=window.scrollY;}
function noteHistoryScrollPosition(){if(historyPinActive()&&historyScrollbarStartY!==null&&window.scrollY>historyScrollbarStartY)historyScrollIntent=true;}
function endHistoryScrollbarDrag(){historyScrollbarStartY=null;}

$('login-form').addEventListener('submit',async event=>{event.preventDefault();if(busy)return;busy=true;const b=event.target.querySelector('button');b.disabled=true;notice('Входим…');try{const data=await api('/api/login',{password:$('password').value,totp:$('login-totp').value});csrf=data.csrf;$('password').value='';$('login-totp').value='';$('login').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;const link=parseDeepLink();if(link){showTab('sessions',false);await loadProjects();}else{showTab('tasks',false);updateUrl();await refresh();}}catch(err){notice(err.message);}finally{busy=false;b.disabled=false;}});
$('refresh').addEventListener('click',refresh);
$('logout').addEventListener('click',async()=>{try{await api('/api/logout',{});signedOut();drafts.clear();receipts.clear();latestAttempts.clear();historyData.clear();sessionRows=[];$('cards').replaceChildren();$('session-list').replaceChildren();clearHistoryView();updateUrl();notice('Вы вышли из Control.');}catch(err){notice(err.message);}});
$('tab-tasks').addEventListener('click',()=>showTab('tasks'));
$('tab-sessions').addEventListener('click',()=>showTab('sessions'));
$('project-select').addEventListener('change',projectChanged);
$('projects-refresh').addEventListener('click',()=>{projectNames=[];loadProjects();});
$('sessions-more').addEventListener('click',()=>{if(sessionsHaveMore)loadSessionList(sessionPage+1,true);});
$('chat-refresh').addEventListener('click',()=>loadHistory(false));
$('history-older').addEventListener('click',()=>loadHistory(true));
$('chat-form').addEventListener('submit',submitMessage);
$('chat-draft').addEventListener('input',()=>{if(selectedSession){const key=chatKey(selectedProject,selectedSession.sid);drafts.set(key,$('chat-draft').value);if(hasUnknown(key))$('send-status').textContent='Есть отправка с неизвестным статусом. Сначала проверьте её вручную.';}});
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
