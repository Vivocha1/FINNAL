const $=id=>document.getElementById(id);
let token=localStorage.getItem('finnal_token')||'', role=localStorage.getItem('finnal_role')||'';
function money(paise){return new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format((paise||0)/100)}
function message(id,text,isError=false){$(id).textContent=text;$(id).classList.remove('hidden','error');if(isError)$(id).classList.add('error')}
function showAuth(mode){['login','register','employer'].forEach(x=>{$(x+'Form').classList.toggle('hidden',x!==mode);$(x+'Tab').className=x===mode?'active':'secondary'});$('authMessage').classList.add('hidden')}
async function api(path,options={}){const headers={'Content-Type':'application/json',...(options.headers||{})};if(token)headers.Authorization='Bearer '+token;const res=await fetch(path,{...options,headers});const data=await res.json().catch(()=>({detail:'Unexpected server response'}));if(!res.ok)throw Error(data.detail||'Request failed');return data}
function setSession(data){token=data.access_token;role=data.role;localStorage.setItem('finnal_token',token);localStorage.setItem('finnal_role',role);openDashboard()}
async function authSubmit(formId,path){const form=$(formId);form.addEventListener('submit',async e=>{e.preventDefault();const body=Object.fromEntries(new FormData(form));try{const data=await api(path,{method:'POST',body:JSON.stringify(body)});setSession(data)}catch(err){message('authMessage',err.message,true)}})}
authSubmit('loginForm','/api/login');authSubmit('registerForm','/api/register');authSubmit('employerForm','/api/bootstrap-employer');
function logout(){token='';role='';localStorage.removeItem('finnal_token');localStorage.removeItem('finnal_role');$('dashboard').classList.add('hidden');$('auth').classList.remove('hidden');$('headerUser').textContent='EMPLOYEE + EMPLOYER';showAuth('login')}
async function openDashboard(){try{const me=await api('/api/me');$('auth').classList.add('hidden');$('dashboard').classList.remove('hidden');$('welcome').textContent='Hello, '+me.name;$('companyName').textContent=me.company;$('headerUser').textContent=me.role==='employee'?'EMPLOYEE':'EMPLOYER ADMIN';$('employeeView').classList.toggle('hidden',me.role!=='employee');$('employerView').classList.toggle('hidden',me.role!=='employer_admin');if(me.role==='employee'){initMoneyForms();await refreshEmployee();await Promise.all([refreshBudgets(),refreshGoals()])}else await refreshEmployer()}catch(e){logout();message('authMessage',e.message,true)}}
let transactionCache = [];
let editingTransactionId = null;
async function refreshEmployee(){
  const [summary, rows] = await Promise.all([api('/api/overview'), api('/api/transactions')]);
  transactionCache = rows;
  $('income').textContent = money(summary.income_paise);
  $('expenses').textContent = money(summary.expense_paise);
  $('net').textContent = money(summary.net_paise);
  $('transactions').innerHTML = rows.length ? rows.map(r =>
    '<div class="tx"><div class="tx-main"><b>'+escapeHtml(r.description)+'</b><div class="muted">'+escapeHtml(r.category)+' · '+r.occurred_on+'</div></div>'+
    '<div class="tx-side"><b class="'+(r.kind==='income'?'positive':'negative')+'">'+(r.kind==='income'?'+':'−')+money(r.amount_paise)+'</b>'+
    '<div class="tx-actions"><button type="button" class="tiny secondary" onclick="editTransaction('+r.id+')">Edit</button><button type="button" class="tiny remove" onclick="removeTransaction('+r.id+')">Remove</button></div></div></div>'
  ).join('') : 'No transactions yet. Add your first entry.';
  if ($('budgetMonth') && $('budgetMonth').value) await refreshBudgets();
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
$('txForm').addEventListener('submit',async e=>{
  e.preventDefault();
  const f=Object.fromEntries(new FormData(e.target));
  const payload={description:f.description,amount_paise:Math.round(Number(f.amount)*100),kind:f.kind,category:f.category,occurred_on:f.occurred_on||localDate()};
  try{
    const path=editingTransactionId?'/api/transactions/'+editingTransactionId:'/api/transactions';
    await api(path,{method:editingTransactionId?'PUT':'POST',body:JSON.stringify(payload)});
    cancelTransactionEdit();e.target.reset();await refreshEmployee();
  }catch(err){alert(err.message)}
});
function localDate(){const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function editTransaction(id){
  const tx=transactionCache.find(row=>row.id===id);if(!tx)return;
  editingTransactionId=id;
  const form=$('txForm');
  form.elements.description.value=tx.description;
  form.elements.amount.value=(tx.amount_paise/100).toFixed(2);
  form.elements.kind.value=tx.kind;
  form.elements.category.value=tx.category;
  form.elements.occurred_on.value=tx.occurred_on;
  form.querySelector('button[type="submit"]').textContent='Update transaction';
  $('cancelTxEdit').classList.remove('hidden');
  form.scrollIntoView({behavior:'smooth',block:'center'});
}
function cancelTransactionEdit(){
  editingTransactionId=null;
  const form=$('txForm');
  if(form){form.reset();form.querySelector('button[type="submit"]').textContent='Save transaction'}
  if($('cancelTxEdit'))$('cancelTxEdit').classList.add('hidden');
}
async function removeTransaction(id){
  if(!confirm('Remove this transaction? Budget spending will be recalculated.'))return;
  try{await api('/api/transactions/'+id,{method:'DELETE'});await refreshEmployee()}
  catch(err){alert(err.message)}
}

async function refreshEmployer(){const d=await api('/api/employer/overview');if(d.suppressed){$('employerMetrics').innerHTML='<div class="notice">'+escapeHtml(d.message)+' Current eligible employee count: '+d.employee_count+'.</div>';return}$('employerMetrics').innerHTML='<div class="grid"><div class="stat"><small>Employees</small><strong>'+d.employee_count+'</strong></div><div class="stat"><small>Employees with activity</small><strong>'+d.employees_with_activity+'</strong></div><div class="stat"><small>Activity rate</small><strong>'+d.activity_rate+'%</strong></div></div><p class="muted">Recorded transactions: '+d.transaction_count+'</p>'}

function currentYM(){const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')}
function initMoneyForms(){
  const month=$('budgetMonth');
  if(month && !month.value) month.value=currentYM();
  if(month) $('budgetMonthLabel').textContent=month.value;
}
async function refreshBudgets(){
  const month=$('budgetMonth').value||currentYM();
  const data=await api('/api/budgets?month='+encodeURIComponent(month));
  $('budgetMonthLabel').textContent=month;
  const rows=data.budgets||[];
  $('budgetsList').innerHTML=rows.length?rows.map(b=>{
    const pct=Math.min(100,Math.max(0,b.progress_pct));
    const over=b.is_over_budget;
    return '<div class="money-card"><div class="row"><h3>'+escapeHtml(b.category)+'</h3><button class="tiny remove" onclick="deleteBudget('+b.id+')">Remove</button></div>'+
      '<div class="sub">'+money(b.spent_paise)+' spent of '+money(b.limit_paise)+'</div>'+
      '<div class="progress '+(over?'over':'')+'"><i style="width:'+pct+'%"></i></div>'+
      '<div class="row"><span class="budget-status '+(over?'over':'ok')+'">'+(over?'Over budget by '+money(b.spent_paise-b.limit_paise):money(b.remaining_paise)+' remaining')+'</span><span class="sub">'+b.progress_pct+'%</span></div></div>';
  }).join(''):'<p class="muted">No budgets for this month. Add your first category limit above.</p>';
}
async function refreshGoals(){
  const data=await api('/api/savings-goals');
  const goals=data.goals||[];
  $('goalsList').innerHTML=goals.length?goals.map(g=>{
    const pct=Math.min(100,Math.max(0,g.progress_pct));
    return '<div class="money-card"><div class="row"><h3>'+escapeHtml(g.name)+'</h3><div><button class="tiny secondary" onclick="toggleGoalEdit('+g.id+')">Edit</button> <button class="tiny remove" onclick="deleteGoal('+g.id+')">Remove</button></div></div>'+
      '<div class="sub">'+money(g.saved_paise)+' saved of '+money(g.target_paise)+'</div>'+
      '<div class="progress"><i style="width:'+pct+'%"></i></div>'+
      '<div class="row"><span class="budget-status ok">'+(g.is_completed?'Goal completed':money(g.remaining_paise)+' to go')+'</span><span class="sub">'+pct+'%</span></div>'+
      (g.due_date?'<div class="sub">Target date: '+g.due_date+'</div>':'')+
      '<form id="goal-edit-'+g.id+'" class="inline-form hidden" onsubmit="saveGoalEdit(event,'+g.id+')"><div class="field"><label>Goal name</label><input name="name" value="'+escapeHtml(g.name)+'" maxlength="120" required></div><div class="field"><label>Target (₹)</label><input name="target" type="number" min="1" step="0.01" value="'+(g.target_paise/100).toFixed(2)+'" required></div><div class="field"><label>Target date</label><input name="due_date" type="date" value="'+(g.due_date||'')+'"></div><button class="tiny">Save changes</button></form>'+
      '<form class="inline-form" onsubmit="addContribution(event,'+g.id+')"><div class="field"><label>Contribution (₹)</label><input name="amount" type="number" min="0.01" step="0.01" required></div><div class="field"><label>Note (optional)</label><input name="note" maxlength="160" placeholder="Monthly saving"></div><button class="tiny">Record contribution</button></form>'+
      '<button class="tiny secondary" style="margin-top:8px" onclick="toggleHistory('+g.id+')">Contribution history</button><div id="history-'+g.id+'" class="muted hidden" style="margin-top:7px"></div></div>';
  }).join(''):'<p class="muted">No savings goals yet. Create a goal to start tracking progress.</p>';
}
function toggleGoalEdit(id){$('goal-edit-'+id).classList.toggle('hidden')}
async function saveGoalEdit(event,id){
  event.preventDefault();
  const f=Object.fromEntries(new FormData(event.currentTarget));
  try{
    await api('/api/savings-goals/'+id,{method:'PUT',body:JSON.stringify({name:f.name,target_paise:Math.round(Number(f.target)*100),due_date:f.due_date||null})});
    await refreshGoals();
  }catch(e){alert(e.message)}
}
$('budgetForm').addEventListener('submit',async e=>{
  e.preventDefault();const f=Object.fromEntries(new FormData(e.target));
  try{
    await api('/api/budgets',{method:'POST',body:JSON.stringify({category:f.category,month:f.month,limit_paise:Math.round(Number(f.limit)*100)})});
    e.target.elements.limit.value='';message('budgetMessage','Budget saved. Existing category and month limits are updated.');
    await refreshBudgets();
  }catch(err){message('budgetMessage',err.message,true)}
});
$('budgetMonth').addEventListener('change',()=>refreshBudgets().catch(e=>message('budgetMessage',e.message,true)));
$('goalForm').addEventListener('submit',async e=>{
  e.preventDefault();const f=Object.fromEntries(new FormData(e.target));
  try{
    await api('/api/savings-goals',{method:'POST',body:JSON.stringify({name:f.name,target_paise:Math.round(Number(f.target)*100),due_date:f.due_date||null})});
    e.target.reset();message('goalMessage','Savings goal created. Start adding contributions below.');
    await refreshGoals();
  }catch(err){message('goalMessage',err.message,true)}
});
async function deleteBudget(id){
  if(!confirm('Remove this monthly budget?'))return;
  try{await api('/api/budgets/'+id,{method:'DELETE'});await refreshBudgets()}catch(e){message('budgetMessage',e.message,true)}
}
async function deleteGoal(id){
  if(!confirm('Remove this savings goal and its contribution history?'))return;
  try{await api('/api/savings-goals/'+id,{method:'DELETE'});await refreshGoals()}catch(e){message('goalMessage',e.message,true)}
}
async function addContribution(event,id){
  event.preventDefault();const form=event.currentTarget;
  const f=Object.fromEntries(new FormData(form));
  try{
    await api('/api/savings-goals/'+id+'/contributions',{method:'POST',body:JSON.stringify({amount_paise:Math.round(Number(f.amount)*100),note:f.note||''})});
    form.reset();await refreshGoals();
  }catch(e){alert(e.message)}
}
async function toggleHistory(id){
  const box=$('history-'+id);
  if(!box.classList.contains('hidden')){box.classList.add('hidden');return}
  try{
    const data=await api('/api/savings-goals/'+id+'/contributions');
    box.innerHTML=(data.contributions||[]).length?data.contributions.map(c=>'<div class="tx"><span>'+c.contributed_on+(c.note?' · '+escapeHtml(c.note):'')+'</span><span><b class="positive">+'+money(c.amount_paise)+'</b> <button class="tiny remove" onclick="removeContribution('+id+','+c.id+')">Remove</button></span></div>').join(''):'No contributions recorded yet.';
    box.classList.remove('hidden');
  }catch(e){box.textContent=e.message;box.classList.remove('hidden')}
}
async function removeContribution(goalId,contributionId){
  if(!confirm('Remove this contribution and reduce goal progress?'))return;
  try{
    await api('/api/savings-goals/'+goalId+'/contributions/'+contributionId,{method:'DELETE'});
    await refreshGoals();
    await toggleHistory(goalId);
  }catch(e){alert(e.message)}
}


if(token)openDashboard();
if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js').catch(() => {}); }
