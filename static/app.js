'use strict';
const $ = id => document.getElementById(id);
let current = null;
let definitions = [];
let dirty = false;
let saveTimer = null;
let saveQueue = Promise.resolve();
let selectedDoc = null;
let lastRequest = 0;
let activeStep = 1;
let legalMaster = null;
let designFields=[];
let renderedEvidenceKey = null;
const legalOpenGroups = new Set(["대표 검토", "신청절차"]);

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
  renderLegal();
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
  renderDetails();renderAiReview();renderLegal();
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
let currentBenchmark=null;
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
function renderBenchmark(report, outputId='benchmarkOutput'){
  currentBenchmark=report;
  const box=$(outputId);box.replaceChildren();
  const heading=create('div','benchmark-header',
    `${report.rules.summary.cases}건 / 정답 ${report.rules.summary.expected_fields}항목 · ${report.practical?'실무형 PDF·XLSX 합성 검증':'합성 TXT 검증'}`);
  box.append(heading);
  for(const [mode,label] of [['rules','규칙 기반 분석'],['ai','실제 LLM 분석']]){
    if(!report[mode])continue;
    const result=report[mode],s=result.summary,c=s.counts;
    const panel=create('div','benchmark-summary');
    panel.append(create('strong','',`${label}${mode==='ai'?' · '+result.model:''}`));
    panel.append(create('span','benchmark-accuracy',`${s.accuracy}%`));
    panel.append(create('span','',`정확 ${c.correct} / 오답 ${c.wrong} / 누락 ${c.missing} / 근거미확인 ${c.unverified} / 공란 오입력 ${c.extra}`));
    box.append(panel);
    const details=create('details','benchmark-details');
    const summary=create('summary','',`${label} · 신청서별 세부 결과 펼치기`);
    details.append(summary);
    const table=create('table','benchmark-table');
    const thead=create('thead');const hrow=create('tr');
    for(const txt of ['시험 서식','정답 항목','정확','오답','누락','근거미확인'])hrow.append(create('th','',txt));
    thead.append(hrow);table.append(thead);
    const body=create('tbody');
    for(const row of result.cases){
      const tr=create('tr');const z=row.score.counts;
      for(const txt of [row.description,String(row.score.expected_fields),String(z.correct),String(z.wrong),String(z.missing),String(z.unverified)])tr.append(create('td','',txt));
      body.append(tr);
      const bad=row.score.fields.filter(x=>!['correct','empty_correct'].includes(x.status));
      if(bad.length){const errrow=create('tr');const cell=create('td','benchmark-issues',bad.map(x=>`${x.field}: ${x.status} (정답 ${x.expected??'공란'} / 결과 ${x.observed??'공란'})`).join(' · '));cell.colSpan=6;errrow.append(cell);body.append(errrow);}
    }
    table.append(body);details.append(table);box.append(details);
  }
  if(report.practical){
    const detail=report.details_summary;
    box.append(create('p','benchmark-disclaimer',`동별·층별·면적 구분 검증: ${detail.correct}/${detail.total}항목 일치. 실패한 항목은 아래에서 확인하세요.`));
    const exp=create('details','benchmark-details');
    exp.append(create('summary','','PDF·엑셀 상세정보 검증 펼치기'));
    const list=create('div','benchmark-practical-checks');
    for(const item of report.rules.cases){
      const heading=create('strong','',item.description);list.append(heading);
      for(const check of item.detail_score.checks){
        const label=create('p','',`${check.ok?'✓':'⚠'} ${check.item}: ${check.ok?'일치':'불일치'} (기대: ${JSON.stringify(check.expected)} / 분석: ${JSON.stringify(check.actual)})`);
        list.append(label);
      }
    }
    exp.append(list);box.append(exp);
  }
  box.append(create('p','benchmark-disclaimer',report.notice));
  if(report.mode==='rules')box.append(create('p','benchmark-disclaimer','실제 AI 결과는 아직 없습니다. 실제 AI 모델을 연결하면 같은 정답으로 비교할 수 있습니다.'));
}
async function runRealformBenchmark(){
 const btn=$('realformBenchButton');btn.disabled=true;
 try{
  const r=await api('/api/realform-benchmark',{method:'POST',json:{}});
  const box=$('realformBenchOutput');box.replaceChildren();
  const sum=r.summary;
  box.append(create('div','benchmark-header',`실무형 합성 PDF ${sum.cases}건 · 정확 ${sum.counts.correct}/${sum.expected_fields} · ${sum.accuracy}% · 누락 ${sum.counts.missing}`));
  for(const item of r.cases){
   const details=create('details','benchmark-details');
   details.append(create('summary','',`${item.id} · 정확 ${item.score.counts.correct}/${item.score.expected_fields} · 누락 ${item.score.counts.missing}`));
   const table=create('table','benchmark-table');const head=create('tr');
   for(const h of ['항목','판정','정답','추출값'])head.append(create('th','',h));table.append(head);
   for(const field of item.score.fields){const row=create('tr');
    for(const val of [field.field,field.status,field.expected??'공란',field.observed??'공란'])row.append(create('td','',String(val)));
    table.append(row);}
   details.append(table);box.append(details);
  }
  box.append(create('p','benchmark-disclaimer',r.notice));
  notify('실무형 합성 PDF 평가 완료');
 }catch(e){notify('실무형 평가 실패: '+e.message,true);}
 finally{btn.disabled=false;}
}
async function testApiConnection(){
  if(!aiEnabled){notify('먼저 AI 연결 실행 스크립트에서 API를 설정하세요.',true);return;}
  if(!confirm('문서를 전혀 보내지 않고 고정된 시험 문장으로 API를 1회 호출합니다. 소액 비용이 발생할 수 있습니다. 진행할까요?'))return;
  const btn=$('apiConnectTestButton');btn.disabled=true;
  const panel=$('apiConnectionResult');panel.textContent='AI 연결을 시험하고 있습니다...';
  try{
    const data=await api('/api/ai-connect-test',{method:'POST',json:{consent:true}});
    panel.textContent=`연결 성공 · 모델: ${data.result.model} · 문서 전송 없음 · 호출 ${data.result.requests}회${data.result.usage_tokens != null?' · 토큰 '+data.result.usage_tokens:''}. 실제 추출 성능은 별도로 평가합니다.`;
    notify('API 인증·통신 확인 완료. 다음으로 합성자료 성능 평가를 진행하세요.');
  }catch(e){panel.textContent='연결 실패: '+e.message;notify('AI API 연결 실패: '+e.message,true);}
  finally{btn.disabled=!aiEnabled;}
}
async function runBenchmark(mode){
  if(mode==='ai'){
    if(!aiEnabled){notify('실제 AI 모델 설정이 필요합니다.',true);return;}
    if(!$('externalAiConsent').checked){notify('합성 시험자료 전송 동의란을 먼저 체크하세요.',true);return;}
    if(!confirm('내장 합성 신청서 4건의 추출 텍스트만 AI 모델에 전송합니다. 모델 비용이 최대 4회 발생할 수 있습니다. 계속할까요?'))return;
  }
  const button=$(mode==='ai'?'benchAiButton':'benchRulesButton');
  const oldText=button.textContent;
  button.disabled=true;button.textContent='평가 진행 중...';
  try{
    const report=await api('/api/benchmark',{method:'POST',json:{mode,consent:mode==='ai'}});
    renderBenchmark(report);
    notify(mode==='ai'?'실제 AI 모델의 합성자료 성능 평가 완료':'로컬 규칙 분석 성능 평가 완료');
  }catch(e){notify('평가 실패: '+e.message,true);}
  finally{button.disabled=(mode==='ai'&&!aiEnabled);button.textContent=oldText;}
}
async function runPracticalBenchmark(mode){
  if(mode==='ai'){
    if(!aiEnabled){notify('Gemini 연결 설정이 필요합니다.',true);return;}
    if(!$('externalAiConsent').checked){notify('상단의 합성 시험자료 전송 동의를 선택하세요.',true);return;}
    if(!confirm('고정 합성 PDF·XLSX 4건의 추출 텍스트·표 셀 정보를 AI에 보냅니다. 원본 이미지는 보내지 않습니다. 최대 4회 호출을 진행할까요?'))return;
  }
  const button=$(mode==='ai'?'practicalAiButton':'practicalRulesButton');
  const oldText=button.textContent;button.disabled=true;button.textContent='실무형 서식 평가 중...';
  try{
    const report=await api('/api/practical-benchmark',{method:'POST',json:{mode,consent:mode==='ai'}});
    renderBenchmark(report,'practicalBenchmarkOutput');
    notify(mode==='ai'?'합성 PDF·엑셀 Gemini 평가 완료':'실무형 PDF·엑셀 규칙 평가 완료');
  }catch(e){notify('실무형 평가 실패: '+e.message,true);}
  finally{button.disabled=(mode==='ai'&&!aiEnabled);button.textContent=oldText;}
}

function chooseBox(options,value){
  const sel=create('select','legal-input');
  for(const name of options){const option=create('option','',name);option.value=name;sel.append(option);}
  sel.value=value||options[0];return sel;
}
function legalGroup(item){ return item.level==='대표항목'?'대표 검토':item.group; }
function refreshLegalGroups(){
  const select=$('legalGroupFilter');
  const prev=select.value;
  select.replaceChildren();
  for(const group of ['전체', '대표 검토',...new Set((legalMaster?.items||[]).filter(x=>x.level==='세부항목').map(x=>x.group))]){
    const option=create('option','',group==='전체'?'전체 분야':group);option.value=group;select.append(option);
  }
  select.value=[...select.options].some(o=>o.value===prev)?prev:'전체';
}
function matchesLegal(item){
  const group=$('legalGroupFilter').value,stage=$('legalReviewFilter').value;
  const term=$('legalSearch').value.trim().toLocaleLowerCase('ko');
  if(group!=='전체' && legalGroup(item)!==group)return false;
  if(stage==='사건별' && item.screening?.status!=='검토대상' && item.progress==='미착수')return false;
  if(stage==='자료필요' && item.screening?.status!=='자료필요')return false;
  if(stage==='낮음' && item.screening?.status!=='우선낮음')return false;
  if(stage==='우선' && item.priority!=='우선 확인')return false;
  if(stage==='미검토' && item.progress==='검토기록완료')return false;
  if(stage==='완료' && item.progress!=='검토기록완료')return false;
  if((stage==='대표항목'||stage==='세부항목')&&item.level!==stage)return false;
  if(term && ![item.id,item.title,item.group,item.basis,item.question,...(item.required_docs||[])].join(' ').toLocaleLowerCase('ko').includes(term))return false;
  return true;
}
function renderLegal(){
  if(!legalMaster || !current)return;
  renderDesignEvidence();
  const state=current.legal_review,container=$('legalItems');container.replaceChildren();
  const confirmEl=$('legalConfirmButton');
  const needsRefresh=Boolean(state?.outdated || state?.screening_needs_refresh || (state && !current.confirmed_at));
  $('legalVersion').textContent=`임시 검토 마스터: ${legalMaster.version} · 기준일 ${legalMaster.as_of} · ${legalMaster.items.length}개 후보`;
  $('legalStatus').textContent=state?.confirmed_at&&!needsRefresh?'담당자 검토기록 확정':state?'확인·기록 필요':'검토 전';
  $('legalStatus').classList.toggle('confirmed',Boolean(state?.confirmed_at&&!needsRefresh));
  $('step2Mark').textContent=state?.confirmed_at&&!needsRefresh?'✓':state?'●':'○';
  let message='';
  if(!current.confirmed_at)message='STEP 01 건축개요를 먼저 확정하세요.';
  else if(needsRefresh)message='건축개요·원문 또는 검토마스터가 변경됐습니다. 기존 이력은 사건파일에 보존됩니다. 재생성 전 저장한 검토의견을 확인하세요.';
  else if(!state)message='확정된 신청정보를 바탕으로 검토 후보를 생성하세요.';
  else message='사건별 검토 후보만 우선 표시합니다. 판별 자료가 부족한 항목은 ‘추가자료 필요’ 탭에서 확인하세요. 이 결과는 적법·위법 판정이 아닙니다.';
  $('legalWarning').textContent=message;
  if(!state){$('legalProgress').textContent=`대표 14개 + 세부 ${legalMaster.items.length-14}개 후보 · 사건별 검토 전`;confirmEl.disabled=true;$('legalFilterInfo').textContent='먼저 체크리스트를 생성하세요.';return;}
  const completed=state.items.filter(i=>i.progress==='검토기록완료').length;
  const sc=state.screening_summary||{};
  $('legalProgress').textContent=`사건별 검토 대상 ${sc['검토대상']||0}개 · 확인자료 필요 ${sc['자료필요']||0}개 · 현 단계 우선낮음 ${sc['우선낮음']||0}개 · 담당자 기록완료 ${completed}개`; 
  confirmEl.disabled=needsRefresh || !current.confirmed_at || state.items.some(i=>i.progress!=='검토기록완료' || i.applicability==='미확인' || !i.note.trim());
  const selected=state.items.filter(matchesLegal);
  $('legalFilterInfo').textContent=`현재 표시 ${selected.length}개 · 총 ${state.items.length}개 중 조건에 따라 선별. ‘자료필요’ 항목을 자동 비적용 처리하지 않습니다.`;
  const grouped=new Map();
  for(const item of selected){const group=legalGroup(item);if(!grouped.has(group))grouped.set(group,[]);grouped.get(group).push(item);}
  const labels=Object.fromEntries(definitions.map(d=>[d.key,d.label]));
  const autoOpen=!!$('legalSearch').value.trim() || $('legalGroupFilter').value!=='전체' || $('legalReviewFilter').value!=='전체';
  for(const [group,items] of grouped){
    const section=create('details','legal-group');section.open=autoOpen||legalOpenGroups.has(group)||$('legalReviewFilter').value==='사건별';
    const title=create('summary','legal-group-title',`${group} · ${items.length}개 표시 · 검토기록 완료 ${items.filter(x=>x.progress==='검토기록완료').length}`);
    section.append(title);section.addEventListener('toggle',()=>{if(section.open)legalOpenGroups.add(group);else legalOpenGroups.delete(group);});
    const stack=create('div','legal-group-items');
    for(const item of items){
      const block=create('article','legal-item');
      const title=create('div','legal-item-head');
      const h=create('div');h.append(create('strong','',`${item.id} · ${item.title}`));
      h.append(create('small','',`${item.screening?.status||'자료필요'} · ${item.priority}`));title.append(h);
      const link=create('a','textlink','근거법령 원문 ↗');link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';title.append(link);block.append(title);
      block.append(create('p','legal-basis',item.basis));
      block.append(create('p','legal-question',item.question));
      const screen=item.screening||{};
      block.append(create('p','legal-screen-reason','선별 근거: '+(screen.reason||'추가자료 확인 필요')));
      if(screen.missing_inputs?.length)block.append(create('p','legal-missing','필요 자료: '+screen.missing_inputs.join(' · ')));
      if(screen.check)block.append(create('p','legal-check','설계값·기준 비교: '+screen.check.result));
      if(item.required_docs?.length){block.append(create('p','legal-docs','확인자료: '+item.required_docs.join(' · ')));}
      if(item.reference_status){block.append(create('p','legal-reference','법령 검증 상태: '+item.reference_status));}
      const facts=create('div','legal-facts');
      for(const [key,value] of Object.entries(item.facts||{}))facts.append(create('span','',`${labels[key]||key}: ${value||'미입력'}`));
      block.append(facts);
      const editor=create('div','legal-editors');
      const ap=chooseBox(['미확인','적용','비적용'],item.applicability,'legal-input');
      const pr=chooseBox(['미착수','검토중','검토기록완료'],item.progress,'legal-input');
      const note=create('textarea','legal-note');note.rows=3;note.maxLength=2500;note.placeholder='담당자가 조례·시행일·도면 근거, 적용 또는 비적용 사유를 기록하세요.';note.value=item.note||'';
      const aLabel=create('label','','적용 여부');aLabel.append(ap);const pLabel=create('label','','진행 상태');pLabel.append(pr);
      const nLabel=create('label','legal-note-label','담당자 검토의견');nLabel.append(note);
      editor.append(aLabel,pLabel,nLabel);block.append(editor);
      const save=create('button','btn outline','이 항목 저장');save.type='button';save.disabled=needsRefresh || !current.confirmed_at;
      save.addEventListener('click',async()=>{
        save.disabled=true;
        try{
          await persist();
          const data=await api('/api/legal-update',{method:'POST',json:{id:item.id,applicability:ap.value,progress:pr.value,note:note.value}});
          current=data.case;renderLegal();updateSummary();notify(`${item.id} 검토의견 저장 완료`);
        }catch(e){notify(e.message,true);save.disabled=false;}
      });
      const actions=create('div','legal-actions');actions.append(save);
      if(item.reviewed_at)actions.append(create('span','',`마지막 기록: ${item.reviewed_at.slice(0,16).replace('T',' ')}`));
      block.append(actions);stack.append(block);
    }
    section.append(stack);container.append(section);
  }
}
function renderDesignEvidence(){
  const container=$('designEvidenceFields');if(!container)return;
  const ev=current?.legal_review?.design_evidence||{};
  const signature=(current?.case_id||'')+JSON.stringify(ev)+Boolean(current?.legal_review);
  if(renderedEvidenceKey===signature && container.childElementCount===designFields.length){
    $('designEvidenceSave').disabled=!current?.legal_review||Boolean(current?.legal_review?.outdated)||!current?.confirmed_at;
    return;
  }
  renderedEvidenceKey=signature;
  container.replaceChildren();
  for(const spec of designFields){
    const outer=create('label','design-evidence-field');
    outer.append(create('span','',spec.label));
    let field;
    if(spec.kind==='select'){
      field=create('select','legal-input');
      for(const name of spec.options||[]){const op=create('option','',name||'선택하세요');op.value=name;field.append(op);}
    }else{
      field=create('input','legal-input');field.type=spec.kind==='number'?'number':'text';
      if(spec.kind==='number'){field.step='any';field.min='0';}
    }
    field.id='design_'+spec.key;field.value=ev[spec.key]||'';
    outer.append(field,create('small','',spec.hint||''));container.append(outer);
  }
  $('designEvidenceSave').disabled=!current?.legal_review||Boolean(current?.legal_review?.outdated)||!current?.confirmed_at;
}
async function saveDesignEvidence(){
  const values={};for(const spec of designFields)values[spec.key]=$('design_'+spec.key)?.value||'';
  const btn=$('designEvidenceSave');btn.disabled=true;
  try{
    const response=await api('/api/design-evidence',{method:'POST',json:{values}});
    current=response.case;renderLegal();updateSummary();
    notify('설계도서 값 저장 및 사건별 검토항목 재선별 완료. 기존 확정 검토기록은 다시 확인해야 합니다.');
  }catch(e){notify(e.message,true);btn.disabled=false;}
}
async function buildLegal(){
  if(!current?.confirmed_at){notify('STEP 01 건축개요 검토확정 후 사용하세요.',true);return;}
  if(current.legal_review&&!confirm('기존 항목별 검토의견이 초기화됩니다. 계속할까요?'))return;
  try{
    await persist();
    const d=await api('/api/legal-build',{method:'POST',json:{init:true}});
    current=d.case;renderLegal();updateSummary();notify('신청정보별 조건 분석 완료');
  }catch(e){notify(e.message,true);}
}
async function confirmLegal(){
  try{
    const d=await api('/api/legal-confirm',{method:'POST',json:{confirm:true}});
    current=d.case;renderLegal();updateSummary();notify('담당자 검토기록 확정 · 적법성 자동판정 아님');
  }catch(e){notify(e.message,true);}
}
async function switchStep(n){
  if(n!==1&&n!==2)return;
  if(n===2){try{await persist();}catch(e){notify(e.message,true);return;}}
  activeStep=n;
  $('phase1Screen').hidden=n!==1;
  $('phase2Screen').hidden=n!==2;
  document.querySelectorAll('.step').forEach(b=>b.classList.toggle('current',Number(b.dataset.step)===n));
  document.querySelector('.sidebar-caption span').textContent=String(n).padStart(2,'0')+' / 09';
  document.querySelector('.assistant-heading small').textContent=n===1?'현재 단계 · 신청서 분석':'현재 단계 · 건축법 검토';
  if(n===2)renderLegal();
  document.querySelector('main.main').scrollTop=0;
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
  $('legalBuildButton').addEventListener('click',buildLegal);
  $('designEvidenceSave').addEventListener('click',saveDesignEvidence);
  $('legalGroupFilter').addEventListener('change',renderLegal);
  $('legalReviewFilter').addEventListener('change',renderLegal);
  $('legalSearch').addEventListener('input',renderLegal);
  $('legalConfirmButton').addEventListener('click',confirmLegal);
  $('aiRunButton').addEventListener('click',runAiReview);
  $('demoRunButton').addEventListener('click',runDemoReview);
  $('benchRulesButton').addEventListener('click',()=>runBenchmark('rules'));
  $('realformBenchButton').addEventListener('click',runRealformBenchmark);
  $('benchAiButton').addEventListener('click',()=>runBenchmark('ai'));
  $('practicalRulesButton').addEventListener('click',()=>runPracticalBenchmark('rules'));
  $('practicalAiButton').addEventListener('click',()=>runPracticalBenchmark('ai'));
  $('apiConnectTestButton').addEventListener('click',testApiConnection);
  $('aiApplyButton').addEventListener('click',applyAiReview);
  $('uploadButton').addEventListener('click',()=>$('applicationInput').click());
  $('applicationInput').addEventListener('change',e=>{uploadFile(e.target.files?.[0]);e.target.value='';});
  $('documentSelector').addEventListener('change',e=>showDocument(e.target.value).catch(err=>notify(err.message,true)));
  const dz=$('dropzone');
  dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('dragover');});
  dz.addEventListener('dragleave',()=>dz.classList.remove('dragover'));
  dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('dragover');uploadFile(e.dataTransfer.files[0]);});
  document.querySelectorAll('.step').forEach(s=>s.addEventListener('click',()=>{
    if(s.dataset.step==='1'||s.dataset.step==='2')switchStep(Number(s.dataset.step));
    else notify('STEP 03~09는 다음 개발 대상입니다.');
  }));
  // Closing the tab does not destroy the local working copy, but export is needed for portability.
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
}
async function init(){
  setup();
  try{
    const data=await api('/api/state');current=data.case;definitions=data.fields;legalMaster=data.legal_master;designFields=data.design_fields||[];refreshLegalGroups();
    aiEnabled=Boolean(data.ai_available);demoSha256=data.demo_sha256||'';
    $('benchAiButton').disabled=!aiEnabled;
    $('practicalAiButton').disabled=!aiEnabled;
    $('apiConnectTestButton').disabled=!aiEnabled;
    $('aiConnectionModel').textContent=aiEnabled?'연결 설정 완료 · '+(data.ai_provider==='gemini'?'Google Gemini':data.ai_provider==='openai'?'OpenAI':'호환 API')+' · '+(data.ai_model||'모델 미지정'):'AI 서버 미연결 · 기본 서비스 Gemini · 로컬 규칙 분석 가능';
    $('aiMode').textContent=aiEnabled?`${data.ai_mode==='local'?'로컬':'외부'} AI 연결 가능 · 별도 실행`:'AI 미연결 · 규칙 분석 가능';
    $('externalAiConsent').disabled=!aiEnabled;
    render();
  }catch(e){notify('초기화 실패: '+e.message,true);}
}
init();
