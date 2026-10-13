"use strict";

const el = id => document.getElementById(id);
let state = null, fields = [], dirty = false, saveTimer = null, pendingSave = Promise.resolve();

async function api(path, options={}) {
  const init={method:options.method || "GET"};
  if(options.json !== undefined) {
    init.headers={"Content-Type":"application/json"};
    init.body=JSON.stringify(options.json);
  } else if(options.raw !== undefined) {
    init.headers={"Content-Type":"application/octet-stream"};
    init.body=options.raw;
  }
  const response=await fetch(path,init);
  if(!response.ok) {
    let reason="요청 오류 ("+response.status+")";
    try{reason=(await response.json()).error || reason;}catch(_){}
    throw new Error(reason);
  }
  return response.json();
}
function message(value,error=false) {
  const box=el("toast");
  box.textContent=value;box.hidden=false;box.classList.toggle("error",error);
  clearTimeout(box._timer);box._timer=setTimeout(()=>{box.hidden=true;},4500);
}
function indicator(value) {el("saveIndicator").textContent="● "+value;}
function node(tag,className,text) {
  const n=document.createElement(tag);
  if(className)n.className=className;
  if(text!==undefined)n.textContent=text;
  return n;
}
function formValues() {
  const values={};
  for(const spec of fields)values[spec.key]=el("field_"+spec.key).value;
  return values;
}
function counts() {
  const values=formValues();
  const completed=Object.values(values).filter(v=>v.trim()).length;
  el("completeCount").textContent=completed;
  el("totalCount").textContent=fields.length;
  const missing=fields.filter(f=>f.required && !values[f.key].trim()).map(f=>f.label);
  const output=el("validationResult");output.replaceChildren();
  output.append(node("div","ok","입력 "+completed+"개 / "+fields.length+"개"));
  if(missing.length)output.append(node("div","warning","필수값 누락: "+missing.join(", ")));
  else output.append(node("div","ok","필수 항목 입력 완료"));
  if(completed<fields.length)output.append(node("div","warning","추가 확인 항목: "+(fields.length-completed)+"개"));
  output.append(node("div","","법령 적합성은 이 단계에서 자동 판단하지 않습니다."));
}
function summary() {
  if(!state)return;
  el("caseTitle").textContent=state.values.site_address || "새 사건";
  el("caseId").textContent=state.case_id.slice(0,8);
  const confirmed=Boolean(state.confirmed_at);
  el("reviewStatus").textContent=confirmed?"담당자 검토 확정":"검토·확인 필요";
  el("reviewStatus").classList.toggle("confirmed",confirmed);
  el("step1Mark").textContent=confirmed?"✓":"●";
  const area=el("historyItems");area.replaceChildren();
  for(const item of state.history || []) {
    const row=node("div","history-item");
    row.append(node("b","",item.action+" · "+item.happened_at.replace("T"," ").slice(0,16)));
    row.append(node("span","",item.detail));area.append(row);
  }
  counts();
}
function edit() {
  dirty=true;
  if(state)state.confirmed_at=null;
  summary();indicator("변경사항 저장 중");
  clearTimeout(saveTimer);
  saveTimer=setTimeout(()=>persist().catch(e=>message(e.message,true)),650);
}
async function persist() {
  clearTimeout(saveTimer);
  if(!dirty)return pendingSave;
  const values=formValues();
  dirty=false;
  pendingSave=pendingSave.catch(()=>{}).then(async()=>{
    const result=await api("/api/save",{method:"POST",json:{values}});
    state=result.case;indicator("로컬 자동저장 완료");summary();
  }).catch(e=>{dirty=true;indicator("저장 실패");throw e;});
  return pendingSave;
}
function field(spec) {
  const wrap=node("div","field"+(spec.type==="textarea"?" wide":""));
  const head=node("div","field-label");
  const label=node("label","",spec.label+(spec.required?" *":""));
  label.htmlFor="field_"+spec.key;head.append(label);wrap.append(head);
  let input;
  if(spec.type==="textarea")input=node("textarea");
  else if(spec.type==="select") {
    input=node("select");
    for(const value of spec.options || []) {
      const option=node("option","",value || "선택하세요");option.value=value;input.append(option);
    }
  } else {
    input=node("input");input.type="text";
    if(spec.type==="number" || spec.type==="integer")input.inputMode="decimal";
  }
  input.id="field_"+spec.key;
  input.value=state.values[spec.key] || "";
  input.addEventListener("input",edit);
  wrap.append(input);
  const provenance=node("div","provenance");
  const source=state.sources[spec.key];
  if(source && source.line && source.document_id) {
    const button=node("button","source-ref",source.filename+" · "+source.where+" · "+source.line+"번 줄");
    button.type="button";
    button.addEventListener("click",()=>showSource(source.document_id,source.line));
    provenance.append(button);
  } else provenance.append(node("span","source-ref disabled",source?"⚠ 원문 근거 확인 필요":"— 원문 출처 없음"));
  if(source && source.edited_by_user)provenance.append(node("span","edited","담당자 수정"));
  wrap.append(provenance);
  return wrap;
}
function render() {
  const grid=el("fieldGrid");grid.replaceChildren();
  for(const spec of fields)grid.append(field(spec));
  const selector=el("documentSelector");selector.replaceChildren();
  const docs=state.documents || [];
  el("sourceEmpty").hidden=docs.length>0;
  el("sourceContent").hidden=docs.length===0;
  for(const item of docs) {
    const option=node("option","",item.filename);option.value=item.id;selector.append(option);
  }
  if(docs.length)showSource(docs[0].id).catch(e=>message(e.message,true));
  else el("sourceLines").replaceChildren();
  dirty=false;indicator("로컬 작업공간 저장됨");summary();
}
async function showSource(id,highlight=null) {
  const docId=Number(id);
  el("documentSelector").value=String(docId);
  el("downloadOriginal").href="/api/document?id="+encodeURIComponent(docId);
  const result=await api("/api/document-lines?id="+encodeURIComponent(docId));
  const lines=result.lines || [];
  const box=el("sourceLines");box.replaceChildren();
  let start=0,end=Math.min(260,lines.length);
  if(highlight) {
    const found=lines.findIndex(x=>x.n===Number(highlight));
    if(found>=0){start=Math.max(0,found-35);end=Math.min(lines.length,found+80);}
  }
  if(start)box.append(node("div","empty","앞쪽 원문 "+start+"줄 생략"));
  for(const line of lines.slice(start,end)) {
    const selected=line.n===Number(highlight);
    const item=node("div","source-line"+(selected?" highlight":""));
    item.id="source_"+line.n;
    item.append(node("span","line-num",line.where+" #"+line.n));
    item.append(node("span","",line.text));box.append(item);
  }
  if(end<lines.length)box.append(node("div","empty","이후 원문 "+(lines.length-end)+"줄 생략"));
  if(highlight)el("source_"+highlight)?.scrollIntoView({block:"nearest"});
}
async function upload(file) {
  if(!file)return;
  if(file.size>15*1024*1024){message("15MB 이하 파일만 허용됩니다.",true);return;}
  if((state.documents||[]).length && !confirm("새 파일은 현재 추출값을 대체하지만 기존 원본은 유지됩니다. 계속할까요?"))return;
  try{
    await persist();
    indicator("신청서 분석 중");
    const url="/api/upload?name="+encodeURIComponent(file.name)+"&consent="+String(el("externalAiConsent").checked);
    const result=await api(url,{method:"POST",raw:await file.arrayBuffer()});
    state=result.case;render();
    message(result.method+"으로 "+result.found+"개 항목을 추출했습니다. 검토 후 확정하세요.");
    if(result.warning)message(result.warning,true);
  }catch(e){indicator("분석 실패");message(e.message,true);}
}
async function openCase(file) {
  if(!file || !confirm("현재 사건은 .bcase로 저장해야 안전하게 보관됩니다. 기존 사건파일을 열까요?"))return;
  try{
    await persist();
    const result=await api("/api/open",{method:"POST",raw:await file.arrayBuffer()});
    state=result.case;render();message("사건파일을 불러왔습니다.");
  }catch(e){message(e.message,true);}
}
async function newCase() {
  if(!confirm("새 사건을 만드시겠습니까? 현재 사건을 먼저 .bcase로 저장하세요."))return;
  try{await persist();const r=await api("/api/new",{method:"POST"});state=r.case;render();message("새 사건 생성 완료");}
  catch(e){message(e.message,true);}
}
async function exportCase() {
  try{
    await persist();
    const response=await fetch("/api/export");
    if(!response.ok)throw new Error("사건파일 생성 실패");
    const blob=await response.blob();
    const disposition=response.headers.get("Content-Disposition") || "";
    const match=disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const name=match?decodeURIComponent(match[1]):"건축인허가.bcase";
    const url=URL.createObjectURL(blob);
    const link=node("a");link.href=url;link.download=name;
    document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),30000);
    message("사건파일을 다운로드했습니다. 안전한 위치에 보관하세요.");
  }catch(e){message(e.message,true);}
}
async function confirmValues() {
  try{await persist();const r=await api("/api/confirm",{method:"POST"});state=r.case;render();message("담당자 검토 확정 완료");}
  catch(e){message(e.message,true);}
}
async function init() {
  el("newButton").addEventListener("click",newCase);
  el("exportButton").addEventListener("click",exportCase);
  el("confirmButton").addEventListener("click",confirmValues);
  el("openButton").addEventListener("click",()=>el("caseInput").click());
  el("uploadButton").addEventListener("click",()=>el("applicationInput").click());
  el("applicationInput").addEventListener("change",e=>{upload(e.target.files[0]);e.target.value="";});
  el("caseInput").addEventListener("change",e=>{openCase(e.target.files[0]);e.target.value="";});
  el("documentSelector").addEventListener("change",e=>showSource(e.target.value).catch(err=>message(err.message,true)));
  const drop=el("dropzone");
  drop.addEventListener("dragover",e=>{e.preventDefault();drop.classList.add("dragover");});
  drop.addEventListener("dragleave",()=>drop.classList.remove("dragover"));
  drop.addEventListener("drop",e=>{e.preventDefault();drop.classList.remove("dragover");upload(e.dataTransfer.files[0]);});
  document.querySelectorAll(".step").forEach(b=>b.addEventListener("click",()=>{
    if(b.dataset.step!=="1")message("이 단계는 다음 버전에서 구현합니다.");
  }));
  window.addEventListener("beforeunload",e=>{if(dirty){e.preventDefault();e.returnValue="";}});
  try{
    const r=await api("/api/state");
    fields=r.fields;state=r.case;
    el("externalAiConsent").disabled=!r.ai_available;
    el("aiMode").textContent=r.ai_available?"외부 AI 연결 가능 · 사용 시 별도 동의":"외부 AI 미연결 · 로컬 분석";
    render();
  }catch(e){message("초기화 실패: "+e.message,true);}
}
init();
