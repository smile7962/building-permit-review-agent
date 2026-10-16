'use strict';
const $ = id => document.getElementById(id);
let current = null;
let definitions = [];
let dirty = false;
let saveTimer = null;
let saveQueue = Promise.resolve();
let selectedDoc = null;
let lastRequest = 0;

async function api(path, {method='GET', json, raw}={}) {
  const options = {method, headers:{}};
  if (json !== undefined) {options.headers['Content-Type']='application/json';options.body=JSON.stringify(json);}
  if (raw !== undefined) {options.headers['Content-Type']='application/octet-stream';options.body=raw;}
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `요청 실패 (${response.status})`;
    try {message = (await response.json()).error || message;} catch {}
    throw new Error(message);
  }
  return response.json();
}
function notify(message, isError=false) {
  const toast=$('toast');toast.textContent=message;toast.classList.toggle('error',isError);toast.hidden=false;
  clearTimeout(toast._timer);toast._timer=setTimeout(()=>{toast.hidden=true;},4000);
}
function indicator(message, type='') {
  const el=$('saveIndicator');el.textContent='● '+message;el.className='save-indicator'+(type?' '+type:'');
}
function valuesFromForm() {
  const obj={};for(const spec of definitions)obj[spec.key]=$('field_'+spec.key)?.value || '';
  return obj;
}
function markDirty() {
  dirty=true;
  if(current){current.confirmed_at=null; updateSummary();}
  indicator('수정 내용 저장 중','pending');
  clearTimeout(saveTimer);saveTimer=setTimeout(()=>{persist().catch(e=>notify(e.message,true));},650);
}
async function persist() {
  clearTimeout(saveTimer);
  if (!dirty) return saveQueue;
  const values=valuesFromForm();dirty=false;
  saveQueue = saveQueue.catch(()=>{}).then(async()=>{
    const data=await api('/api/save',{method:'POST',json:{values}});
    current=data.case;
    indicator('로컬 자동저장 완료');
    updateSummary();
  }).catch(error=>{dirty=true;indicator('저장 실패','error');throw error;});
  return saveQueue;
}
function create(tag, className, text) {
  const el=document.createElement(tag);if(className)el.className=className;
  if(text!==undefined)el.textContent=text;return el;
}
function fieldElement(spec) {
  const block=create('div', 'field'+(spec.type==='textarea'?' wide':''));
  const head=create('div','field-label');
  const label=create('label','',spec.label + (spec.required?' *':''));label.htmlFor='field_'+spec.key;
  head.append(label);block.append(head);
  let input;
  if(spec.type==='select'){
    input=create('select');for(const option of spec.options || []){
      const el=create('option','',option || '선택하세요');el.value=option;input.append(el);
    }
  } else if(spec.type==='textarea') input=create('textarea');
  else {input=create('input');input.type='text';input.inputMode=(spec.type==='number'||spec.type==='integer')?'decimal':'text';}
  input.id='field_'+spec.key;
  input.value=current.values?.[spec.key] || '';
  input.addEventListener('input',()=>{markDirty();updateCounts();});
  input.addEventListener('change',()=>{markDirty();});
  block.append(input);
  const prov=create('div','provenance');
  const source=current.sources?.[spec.key];
  if(source && source.line && source.document_id){
    const ref=create('button','source-ref', `${source.filename} · ${source.where} · ${source.line}번 줄`);
    ref.type='button';ref.addEventListener('click',()=>showDocument(source.document_id,source.line));prov.append(ref);
  } else if(source){prov.append(create('span','source-ref disabled','⚠ 추출값 원문 출처 확인 필요'));}
  else {prov.append(create('span','source-ref disabled','— 원문 출처 없음'));}
  if(source?.edited_by_user) prov.append(create('span','edited','직접 수정'));
  block.append(prov);
  return block;
}
function updateCounts() {
  const values=valuesFromForm();
  const count=Object.values(values).filter(x=>x.trim()).length;
  $('completeCount').textContent=String(count);
  $('totalCount').textContent=String(definitions.length);
  const required=definitions.filter(x=>x.required && !values[x.key].trim());
  const lack=definitions.length-count;
  const val=$('validationResult');val.replaceChildren();
  const add=(text,cls)=>{const div=create('div',cls,text);val.append(div);};
  add(`입력 완료: ${count}개 / ${definitions.length}개`,'ok');
  if(required.length) add('필수값 누락: '+required.map(x=>x.label).join(', '),'warning');
  else add('필수 항목 입력 완료','ok');
  if(lack) add('확인 필요 항목: '+lack+'개','warning');
  if((current?.documents||[]).length && !values.building_count?.trim())
    add('건축물 동수 미확인: 첫 장의 주건축물수를 대조해 직접 입력하세요. 동별 개요로 임의 계산하지 않습니다.','warning');
  const unsupported = Object.values(current?.sources||{}).filter(s=>s.method==='외부 AI 초안'&&!s.line).length;
  if(unsupported) add('출처 미확인 AI 항목: '+unsupported+'개','warning');
  add('법령 적용·건폐율 적법성 등은 이 단계에서 판단하지 않습니다.','');
}
function updateSummary() {
  if(!current)return;
  const vals=current.values||{};
  $('caseTitle').textContent=vals.site_address || '새 사건';
  $('caseId').textContent=current.case_id.slice(0,8);
  const confirmed=Boolean(current.confirmed_at);
  $('reviewStatus').textContent=confirmed?'담당자 검토 확정':'검토·확인 필요';
  $('reviewStatus').classList.toggle('confirmed',confirmed);
  $('step1Mark').textContent=confirmed?'✓':'●';
  const list=$('historyItems');list.replaceChildren();
  for(const h of current.history||[]){
    const row=create('div','history-item');row.append(create('b','',h.action+' · '+h.happened_at.replace('T',' ').slice(0,16)));
    row.append(create('span','',h.detail));list.append(row);
  }
  updateCounts();
}
// A separate, source-linked draft. Only whitelisted edits are sent to the server.
async function updateDetail(section,index,part,key,value) {
  try {
    await persist();
    indicator("상세정보 저장 중");
    const result=await api("/api/detail-update",{method:"POST",json:{section,index,part,field:key,value}});
    current=result.case;
    indicator("상세정보 저장됨");
    renderDetails();updateSummary();
  }catch(e){indicator("상세정보 저장 실패");notify(e.message,true);}
}
function detailEditor(section,index,part,key,value,source) {
  const cell=create("td");
  const input=create("input","detail-input");
  input.setAttribute("aria-label", section+" "+(index+1)+" "+part+" "+key);
  input.value=value||"";
  input.addEventListener("change",()=>{if(input.value!==(value||""))updateDetail(section,index,part,key,input.value);});
  cell.append(input);
  if(source?.edited_by_user)cell.append(create("small","edited","담당자 수정"));
  return cell;
}
function sourceButton(source) {
  const cell=create("td");
  if(source?.document_id && source?.line) {
    const b=create("button","source-ref","원문 "+source.where+" #"+source.line);
    b.addEventListener("click",()=>showDocument(source.document_id,source.line).catch(e=>notify(e.message,true)));
    cell.append(b);
  }else cell.append(create("span","source-ref disabled","출처 확인 필요"));
  return cell;
}
function bValue(row,part,key) {return row?.[part]?.[key]?.value||"";}
function renderDetails() {
  const details=current?.application_details;
  $("detailsPanel").hidden=!details;
  if(!details)return;
  const currentWork=current.values.work_type;
  $("detailStatus").textContent=currentWork?"건축구분: "+currentWork:"건축구분 확인 필요";
  const warn=$("detailWarnings");warn.replaceChildren();
  for(const w of details.warnings||[]) {
    if(currentWork && w.includes("건축구분"))continue;
    warn.append(create("p","",w));
  }
  const bbody=$("buildingRows"); bbody.replaceChildren();
  for(const [idx,row] of (details.buildings||[]).entries()) {
    const tr=create("tr");
    tr.append(detailEditor("buildings",idx,"meta","building_name",row.building_name));
    for(const [part,key] of [["existing","main_use"],["proposed","main_use"],
                ["existing","floor_area_m2"],["proposed","floor_area_m2"],["proposed","structure"]]) {
      tr.append(detailEditor("buildings",idx,part,key,bValue(row,part,key),row[part]?.[key]));
    }
    tr.append(sourceButton(row.source));bbody.append(tr);
  }
  if(!details.buildings?.length){const tr=create("tr");const td=create("td","empty","동별 표를 자동 인식하지 못했습니다.");td.colSpan=7;tr.append(td);bbody.append(tr);}
  const fbody=$("floorRows");fbody.replaceChildren();
  for(const [idx,row] of (details.floors||[]).entries()) {
    const tr=create("tr");
    tr.append(detailEditor("floors",idx,"meta","building_name",row.building_name));
    tr.append(detailEditor("floors",idx,"meta","floor",row.floor));
    tr.append(detailEditor("floors",idx,"meta","work_type",row.work_type));
    tr.append(detailEditor("floors",idx,"existing","area_m2",row.existing?.area_m2));
    tr.append(detailEditor("floors",idx,"proposed","area_m2",row.proposed?.area_m2));
    tr.append(detailEditor("floors",idx,"proposed","use",row.proposed?.use));
    tr.append(sourceButton(row.area_source||row.source));fbody.append(tr);
  }
  if(!details.floors?.length){const tr=create("tr");const td=create("td","empty","층별 표를 자동 인식하지 못했습니다.");td.colSpan=7;tr.append(td);fbody.append(tr);}
}
function render() {
  if(!current)return;
  const grid=$('fieldGrid');grid.replaceChildren();
  for(const spec of definitions)grid.append(fieldElement(spec));
  updateSummary();
  renderDetails();renderAiReview();
  const selector=$('documentSelector');selector.replaceChildren();
  const docs=current.documents || [];
  $('sourceEmpty').hidden=docs.length>0;
  $('sourceContent').hidden=docs.length===0;
  for(const doc of docs){const op=create('option','',doc.filename);op.value=doc.id;selector.append(op);}
  indicator('로컬 작업공간 저장됨');
  if(docs.length){showDocument(docs[0].id).catch(e=>notify(e.message,true));}
  else{$('sourceLines').replaceChildren();selectedDoc=null;}
}
async function showDocument(id, targetLine=null) {
  selectedDoc=Number(id);
  const requestId=++lastRequest;
  const doc=current.documents.find(d=>d.id===selectedDoc);
  if(!doc)return;
  $('documentSelector').value=String(id);
  $('downloadOriginal').href='/api/document?id='+encodeURIComponent(id);
  const data=await api('/api/document-lines?id='+encodeURIComponent(id));
  if(requestId!==lastRequest)return;
  const wrap=$('sourceLines');wrap.replaceChildren();
  const lines=data.lines||[];
  let start=0,end=Math.min(lines.length,260);
  if(targetLine){const i=lines.findIndex(x=>x.n===Number(targetLine));if(i>=0){start=Math.max(0,i-40);end=Math.min(lines.length,i+120);}}
  if(start>0)wrap.append(create('div','empty',`원문 ${start}줄 생략 · 선택한 원문 주변 표시`));
  for(const item of lines.slice(start,end)){
    const row=create('div','source-line'+(item.n===Number(targetLine)?' highlight':''));
    row.id='line_'+item.n;
    row.append(create('span','line-num', `${item.where} #${item.n}`));
    row.append(create('span','',item.text));wrap.append(row);
  }
  if(end<lines.length)wrap.append(create('div','empty',`나머지 ${lines.length-end}줄 생략`));
  if(targetLine) $('line_'+targetLine)?.scrollIntoView({block:'nearest',behavior:'smooth'});
}

function renderAiReview(){
  const ai=current?.ai_review;
  $('aiReviewEmpty').hidden=Boolean(ai);
  $('aiReviewContent').hidden=!ai;
  const button=$('aiRunButton');
  button.disabled=!aiEnabled || !(current?.documents||[]).length;
  $('demoRunButton').disabled=current?.documents?.[0]?.sha256 !== demoSha256;
  if(!ai)return;
  const counts=ai.counts || {};
  $('aiReviewSummary').textContent=`${ai.mode==='demo'?'[실제 AI 아님] ':''}${ai.model} · 일치 ${counts.same||0} · 불일치 ${counts.different||0} · AI만 제안 ${counts.missing||0} · 근거 재확인 ${counts.needs_evidence||0}`;
  const tbody=$('aiComparisonRows');tbody.replaceChildren();
  for(const [key,info] of Object.entries(ai.suggestions||{})){
    const tr=create('tr');
    const td=create('td');const c=create('input');c.type='checkbox';c.className='ai-pick';c.value=key;
    c.disabled=!info.verified;
    td.append(c);tr.append(td);
    tr.append(create('td','',info.label));
    tr.append(create('td','',info.local_value||'—'));
    tr.append(create('td','',info.value));
    tr.append(create('td',info.verified?'':'ai-unverified',info.status));
    const source=create('td');
    if(info.source?.line && info.source?.document_id){
      const link=create('button','source-ref',`${info.source.where} #${info.source.line}`);
      link.type='button';link.addEventListener('click',()=>showDocument(info.source.document_id,info.source.line).catch(e=>notify(e.message,true)));
      source.append(link);
    }else source.append(create('span','source-ref disabled','근거 미확인'));
    tr.append(source);tbody.append(tr);
  }
}
let aiEnabled=false;
let demoSha256='';
async function runDemoReview(){
  const latest=current?.documents?.[0];
  if(!latest){notify('먼저 동봉된 모의 신청서를 업로드하세요.',true);return;}
  try{
    await persist();
    $('demoRunButton').disabled=true;indicator('모의 비교 중','pending');
    const res=await api('/api/demo-review',{method:'POST',json:{document_id:latest.id}});
    current=res.case;renderAiReview();updateSummary();indicator('모의 비교 초안 생성 완료');
    notify('모의 응답 비교표입니다. 실제 AI 모델은 호출하지 않았습니다.');
  }catch(e){indicator('모의 비교 실패','error');notify(e.message,true);}
  finally{renderAiReview();}
}
async function runAiReview(){
  if(!aiEnabled){notify('AI 모델이 설정되지 않았습니다. README의 환경변수 설정을 확인하세요.',true);return;}
  if(!$('externalAiConsent').checked){notify('모의·비식별 자료임을 확인하고 AI 분석 전송에 동의하세요.',true);return;}
  const latest=current?.documents?.[0];
  if(!latest){notify('신청서를 먼저 업로드하세요.',true);return;}
  try{
    await persist();
    $('aiRunButton').disabled=true;indicator('AI 비교 분석 중','pending');
    const res=await api('/api/ai-review',{method:'POST',json:{document_id:latest.id,consent:true}});
    current=res.case;renderAiReview();updateSummary();indicator('AI 초안 분석 완료');
    notify('AI 비교 초안 생성 완료. 원문과 대조한 후 필요한 항목만 선택하세요.');
  }catch(e){indicator('AI 분석 실패','error');notify(e.message,true);}
  finally{renderAiReview();}
}
async function applyAiReview(){
  const ai=current?.ai_review;
  const keys=Array.from(document.querySelectorAll('.ai-pick:checked')).map(x=>x.value);
  if(!ai || !keys.length){notify('반영할 AI 제안을 선택하세요.',true);return;}
  if(!confirm('선택한 AI 제안 '+keys.length+'개를 건축개요에 반영하고 기존 검토 확정을 해제할까요?'))return;
  try{
    await persist();
    const res=await api('/api/ai-apply',{method:'POST',json:{run_id:ai.run_id,keys}});
    current=res.case;render();notify('선택한 '+keys.length+'개 항목을 반영했습니다. 원문과 재대조 후 확정하세요.');
  }catch(e){notify(e.message,true);}
}

async function uploadFile(file) {
  if(!file)return;
  if(file.size>15*1024*1024){notify('신청서는 15MB 이하로 등록하세요.',true);return;}
  if((current?.documents||[]).length && !confirm('새 신청서를 등록하면 건축개요 추출 초안이 교체됩니다. 기존 원본문서는 보존됩니다. 계속할까요?'))return;
  try{
    await persist();
    indicator('신청서 분석 중','pending');
    const url='/api/upload?name='+encodeURIComponent(file.name);
    const data=await api(url,{method:'POST',raw:await file.arrayBuffer()});
    current=data.case;dirty=false;render();
    notify(`${data.method} · ${data.found}개 항목 추출. 담당자 확인이 필요합니다.`);
    if(data.warning)notify(data.warning,true);
  }catch(e){indicator('분석 실패','error');notify(e.message,true);}
}
async function openCase(file){
  if(!file)return;
  if(!confirm('현재 사건의 임시 작업은 전환됩니다. .bcase를 내보내지 않았다면 먼저 저장하세요. 사건파일을 열까요?'))return;
  try{
    await persist();
    const data=await api('/api/open',{method:'POST',raw:await file.arrayBuffer()});
    current=data.case;dirty=false;render();notify('사건파일을 다시 열었습니다.');
  }catch(e){notify('열기 실패: '+e.message,true);}
}
async function exportCase(){
  try{
    await persist();
    const res=await fetch('/api/export');if(!res.ok)throw new Error('사건파일 생성 실패');
    const data=await res.blob();
    const disposition=res.headers.get('Content-Disposition')||'';
    const match=disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const fileName=match?decodeURIComponent(match[1]):'건축인허가.bcase';
    const url=URL.createObjectURL(data);const a=create('a');a.href=url;a.download=fileName;
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
    notify('사건파일이 다운로드되었습니다. 파일을 안전한 위치에 보관하세요.');
  }catch(e){notify(e.message,true);}
}
async function newCase(){
  if(!confirm('새 사건을 만들까요? 현재 사건은 .bcase로 저장해야 다른 PC에서 다시 열 수 있습니다.'))return;
  try{
    await persist();const data=await api('/api/new',{method:'POST'});
    current=data.case;dirty=false;render();notify('새 사건을 만들었습니다.');
  }catch(e){notify(e.message,true);}
}
async function confirmFields(){
  try{
    await persist();const data=await api('/api/confirm',{method:'POST'});
    current=data.case;render();notify('담당자 검토가 확정되었습니다. 이후 수정하면 다시 검토해야 합니다.');
  }catch(e){notify(e.message,true);}
}
function setup(){
  $('newButton').addEventListener('click',newCase);
  $('openButton').addEventListener('click',()=>$('caseInput').click());
  $('caseInput').addEventListener('change',e=>{openCase(e.target.files?.[0]);e.target.value='';});
  $('exportButton').addEventListener('click',exportCase);
  $('confirmButton').addEventListener('click',confirmFields);
  $('aiRunButton').addEventListener('click',runAiReview);
  $('demoRunButton').addEventListener('click',runDemoReview);
  $('aiApplyButton').addEventListener('click',applyAiReview);
  $('uploadButton').addEventListener('click',()=>$('applicationInput').click());
  $('applicationInput').addEventListener('change',e=>{uploadFile(e.target.files?.[0]);e.target.value='';});
  $('documentSelector').addEventListener('change',e=>showDocument(e.target.value).catch(err=>notify(err.message,true)));
  const dz=$('dropzone');
  dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('dragover');});
  dz.addEventListener('dragleave',()=>dz.classList.remove('dragover'));
  dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('dragover');uploadFile(e.dataTransfer.files[0]);});
  document.querySelectorAll('.step').forEach(s=>s.addEventListener('click',()=>{
    if(s.dataset.step!=='1')notify('해당 단계는 현재 개발 중입니다. Phase 1 검증 후 순차 구현합니다.');
  }));
  // Closing the tab does not destroy the local working copy, but export is needed for portability.
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
}
async function init(){
  setup();
  try{
    const data=await api('/api/state');current=data.case;definitions=data.fields;
    aiEnabled=Boolean(data.ai_available);demoSha256=data.demo_sha256||'';
    $('aiMode').textContent=aiEnabled?`${data.ai_mode==='local'?'로컬':'외부'} AI 연결 가능 · 별도 실행`:'AI 미연결 · 규칙 분석 가능';
    $('externalAiConsent').disabled=!aiEnabled;
    render();
  }catch(e){notify('초기화 실패: '+e.message,true);}
}
init();
