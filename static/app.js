const $ = id => document.getElementById(id);
let token = localStorage.getItem('finnal_token') || '';
let role = localStorage.getItem('finnal_role') || '';
let transactionCache = [];
let editingTransactionId = null;
let selectedAdvisorEmployeeId = null;

function money(paise) {
  return new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR', maximumFractionDigits:2}).format((Number(paise)||0)/100);
}
function rupees(value) { return Math.round((Number(value)||0)*100); }
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function message(id, text, isError=false) {
  const el=$(id); if(!el) return;
  el.textContent=text; el.classList.remove('hidden','error'); if(isError) el.classList.add('error');
}
function hideMessage(id) { const el=$(id); if(el) el.classList.add('hidden'); }
function localDate() {
  const d=new Date(); return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
}
function currentYM() { return localDate().slice(0,7); }
function jumpTo(id, button) {
  document.querySelectorAll('.nav-pills button').forEach(b=>b.classList.remove('active'));
  if(button) button.classList.add('active');
  $(id)?.scrollIntoView({behavior:'smooth',block:'start'});
}
async function api(path, options={}) {
  const headers={'Content-Type':'application/json', ...(options.headers||{})};
  if(token) headers.Authorization='Bearer '+token;
  const response=await fetch(path,{...options,headers});
  const data=await response.json().catch(()=>({detail:'Unexpected server response'}));
  if(!response.ok) throw new Error(data.detail || 'Request failed');
  return data;
}
function showAuth(mode) {
  ['login','register','employer'].forEach(x=>{
    $(x+'Form').classList.toggle('hidden',x!==mode);
    $(x+'Tab').className=x===mode?'active':'secondary';
  });
  hideMessage('authMessage');
}
function setSession(data) {
  token=data.access_token; role=data.role;
  localStorage.setItem('finnal_token',token); localStorage.setItem('finnal_role',role);
  openDashboard();
}
function bindAuth(formId,path) {
  $(formId).addEventListener('submit',async e=>{
    e.preventDefault(); const body=Object.fromEntries(new FormData(e.currentTarget));
    try { setSession(await api(path,{method:'POST',body:JSON.stringify(body)})); }
    catch(error) { message('authMessage',error.message,true); }
  });
}
bindAuth('loginForm','/api/login');
bindAuth('registerForm','/api/register');
bindAuth('employerForm','/api/bootstrap-employer');

function logout() {
  token=''; role=''; selectedAdvisorEmployeeId=null;
  localStorage.removeItem('finnal_token'); localStorage.removeItem('finnal_role');
  $('dashboard').classList.add('hidden'); $('auth').classList.remove('hidden');
  $('headerUser').textContent='EMPLOYEE + EMPLOYER'; showAuth('login');
}
async function openDashboard() {
  try {
    const me=await api('/api/me');
    $('auth').classList.add('hidden'); $('dashboard').classList.remove('hidden');
    $('welcome').textContent='Hello, '+me.name;
    $('companyName').textContent=me.company;
    $('companyEyebrow').textContent=me.role==='advisor'?'FINNAL PROFESSIONAL DESK':me.role==='employer_admin'?'EMPLOYER / HR WORKSPACE':'YOUR FINANCIAL SPACE';
    $('headerUser').textContent=me.role==='employee'?'EMPLOYEE':me.role==='employer_admin'?'EMPLOYER ADMIN':'FINNAL PROFESSIONAL';
    $('employeeView').classList.toggle('hidden',me.role!=='employee');
    $('employerView').classList.toggle('hidden',me.role!=='employer_admin');
    $('professionalView').classList.toggle('hidden',me.role!=='advisor');
    if(me.role==='employee') {
      initMoneyForms();
      await Promise.all([refreshEmployee(),refreshBudgets(),refreshGoals(),refreshPayroll(),refreshProfile(),refreshAssets(),refreshAdvisories(),refreshOwnLoans()]);
    } else if(me.role==='employer_admin') {
      await refreshEmployer();
    } else if(me.role==='advisor') {
      await Promise.all([refreshAdvisorDirectory(),refreshAdvisorLoans()]);
    } else { throw new Error('Unknown account role'); }
  } catch(error) {
    logout(); message('authMessage',error.message,true);
  }
}
function initMoneyForms() {
  if($('budgetMonth') && !$('budgetMonth').value) $('budgetMonth').value=currentYM();
  if($('payMonth') && !$('payMonth').value) $('payMonth').value=currentYM();
  if($('txForm') && !$('txForm').elements.occurred_on.value) $('txForm').elements.occurred_on.value=localDate();
  if($('assetForm') && !$('assetForm').elements.as_of_date.value) $('assetForm').elements.as_of_date.value=localDate();
}
async function refreshEmployee() {
  const [summary,rows]=await Promise.all([api('/api/overview'),api('/api/transactions')]);
  transactionCache=rows;
  $('income').textContent=money(summary.income_paise);
  $('expenses').textContent=money(summary.expense_paise);
  $('net').textContent=money(summary.net_paise);
  $('transactions').innerHTML=rows.length?rows.map(r=>
    '<div class="list-row"><div><b>'+escapeHtml(r.description)+'</b><div class="sub">'+escapeHtml(r.category)+' · '+escapeHtml(r.occurred_on)+'</div></div>'+
    '<div style="text-align:right"><b class="money '+(r.kind==='income'?'positive':'negative')+'">'+(r.kind==='income'?'+':'−')+money(r.amount_paise)+'</b>'+
    '<div class="actions" style="justify-content:flex-end;margin-top:5px"><button type="button" class="tiny secondary" onclick="editTransaction('+r.id+')">Edit</button><button type="button" class="tiny danger" onclick="removeTransaction('+r.id+')">Remove</button></div></div></div>'
  ).join(''):'<p class="muted">No transactions yet. Add your first entry.</p>';
}
$('txForm').addEventListener('submit',async e=>{
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget));
  const payload={description:f.description,amount_paise:rupees(f.amount),kind:f.kind,category:f.category,occurred_on:f.occurred_on||localDate()};
  try {
    const path=editingTransactionId?'/api/transactions/'+editingTransactionId:'/api/transactions';
    await api(path,{method:editingTransactionId?'PUT':'POST',body:JSON.stringify(payload)});
    cancelTransactionEdit(); e.currentTarget.reset(); initMoneyForms(); await refreshEmployee(); await refreshBudgets();
  } catch(error) { alert(error.message); }
});
function editTransaction(id) {
  const tx=transactionCache.find(r=>r.id===id); if(!tx) return;
  editingTransactionId=id; const f=$('txForm');
  f.elements.description.value=tx.description; f.elements.amount.value=(tx.amount_paise/100).toFixed(2);
  f.elements.kind.value=tx.kind; f.elements.category.value=tx.category; f.elements.occurred_on.value=tx.occurred_on;
  f.querySelector('button[type="submit"]').textContent='Update transaction';
  $('cancelTxEdit').classList.remove('hidden'); f.scrollIntoView({behavior:'smooth',block:'center'});
}
function cancelTransactionEdit() {
  editingTransactionId=null; const form=$('txForm'); form.reset();
  form.querySelector('button[type="submit"]').textContent='Save transaction';
  $('cancelTxEdit').classList.add('hidden'); initMoneyForms();
}
async function removeTransaction(id) {
  if(!confirm('Remove this transaction? Budget spending will be recalculated.')) return;
  try { await api('/api/transactions/'+id,{method:'DELETE'}); await refreshEmployee(); await refreshBudgets(); }
  catch(error) { alert(error.message); }
}

async function refreshBudgets() {
  const month=$('budgetMonth').value||currentYM();
  const data=await api('/api/budgets?month='+encodeURIComponent(month));
  $('budgetsList').innerHTML=(data.budgets||[]).length?data.budgets.map(b=>{
    const pct=Math.min(100,Math.max(0,b.progress_pct||0)); const over=b.is_over_budget;
    return '<div class="money-card"><div class="list-row"><b>'+escapeHtml(b.category)+'</b><button class="tiny danger" onclick="deleteBudget('+b.id+')">Remove</button></div>'+
      '<div class="muted">'+money(b.spent_paise)+' spent of '+money(b.limit_paise)+'</div><div class="progress '+(over?'over':'')+'"><i style="width:'+pct+'%"></i></div>'+
      '<div class="metric-line"><span>'+(over?'Over budget by '+money(b.spent_paise-b.limit_paise):money(b.remaining_paise)+' remaining')+'</span><b>'+b.progress_pct+'%</b></div></div>';
  }).join(''):'<p class="muted">No budgets for this month. Add a category limit above.</p>';
}
$('budgetForm').addEventListener('submit',async e=>{
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget));
  try { await api('/api/budgets',{method:'POST',body:JSON.stringify({category:f.category,month:f.month,limit_paise:rupees(f.limit)})});
    e.currentTarget.elements.limit.value=''; message('budgetMessage','Budget saved. Spending will update as you record expenses.'); await refreshBudgets();
  } catch(error) { message('budgetMessage',error.message,true); }
});
$('budgetMonth').addEventListener('change',()=>refreshBudgets().catch(e=>message('budgetMessage',e.message,true)));
async function deleteBudget(id) {
  if(!confirm('Remove this monthly budget?')) return;
  try { await api('/api/budgets/'+id,{method:'DELETE'}); await refreshBudgets(); }
  catch(error) { message('budgetMessage',error.message,true); }
}

async function refreshGoals() {
  const data=await api('/api/savings-goals'); const goals=data.goals||[];
  $('goalsList').innerHTML=goals.length?goals.map(g=>{
    const pct=Math.min(100,Math.max(0,g.progress_pct));
    return '<div class="money-card"><div class="list-row"><b>'+escapeHtml(g.name)+'</b><button class="tiny danger" onclick="deleteGoal('+g.id+')">Remove</button></div>'+
      '<div class="muted">'+money(g.saved_paise)+' saved of '+money(g.target_paise)+'</div><div class="progress"><i style="width:'+pct+'%"></i></div>'+
      '<div class="metric-line"><span>'+(g.is_completed?'Goal completed':money(g.remaining_paise)+' to go')+'</span><b>'+pct+'%</b></div>'+
      (g.due_date?'<p class="muted">Target date: '+escapeHtml(g.due_date)+'</p>':'')+
      '<form class="inline-form" onsubmit="addContribution(event,'+g.id+')"><div class="field"><label>Contribution (₹)</label><input name="amount" type="number" min=".01" step=".01" required></div><div class="field"><label>Note</label><input name="note" maxlength="160" placeholder="Monthly saving"></div><button class="tiny">Add</button></form>'+
      '<button class="tiny secondary" style="margin-top:8px" onclick="toggleHistory('+g.id+')">Contribution history</button><div id="history-'+g.id+'" class="muted hidden"></div></div>';
  }).join(''):'<p class="muted">No savings goals yet. Create your first target.</p>';
}
$('goalForm').addEventListener('submit',async e=>{
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget));
  try { await api('/api/savings-goals',{method:'POST',body:JSON.stringify({name:f.name,target_paise:rupees(f.target),due_date:f.due_date||null})});
    e.currentTarget.reset(); message('goalMessage','Savings goal created.'); await refreshGoals();
  } catch(error) { message('goalMessage',error.message,true); }
});
async function deleteGoal(id) {
  if(!confirm('Remove this savings goal and contribution history?')) return;
  try { await api('/api/savings-goals/'+id,{method:'DELETE'}); await refreshGoals(); }
  catch(error) { message('goalMessage',error.message,true); }
}
async function addContribution(event,id) {
  event.preventDefault(); const form=event.currentTarget; const f=Object.fromEntries(new FormData(form));
  try { await api('/api/savings-goals/'+id+'/contributions',{method:'POST',body:JSON.stringify({amount_paise:rupees(f.amount),note:f.note||''})});
    await refreshGoals();
  } catch(error) { alert(error.message); }
}
async function toggleHistory(id) {
  const box=$('history-'+id);
  if(!box.classList.contains('hidden')) { box.classList.add('hidden'); return; }
  try { const data=await api('/api/savings-goals/'+id+'/contributions');
    box.innerHTML=(data.contributions||[]).length?data.contributions.map(c=>'<div class="metric-line"><span>'+escapeHtml(c.contributed_on)+' '+escapeHtml(c.note||'')+'</span><b class="positive">+'+money(c.amount_paise)+'</b></div>').join(''):'No contributions recorded.';
    box.classList.remove('hidden');
  } catch(error) { box.textContent=error.message; box.classList.remove('hidden'); }
}

async function refreshPayroll() {
  const data=await api('/api/payroll'); const entries=data.entries||[];
  $('salaryDeposited').textContent=money(entries.length?entries[0].deposited_paise:0);
  $('salaryMonthLabel').textContent=entries.length?'Latest: '+entries[0].month:'No deposits recorded';
  $('payrollList').innerHTML=entries.length?entries.map(p=>
    '<div class="money-card"><div class="list-row"><div><b>'+escapeHtml(p.month)+'</b><div class="sub">Manual entry · unverified</div></div><b class="money positive">'+money(p.deposited_paise)+' deposited</b></div>'+
    '<div class="metric-line"><span>Gross earnings</span><b>'+money(p.gross_salary_paise)+'</b></div>'+
    '<div class="metric-line"><span>PF · tax · other deductions</span><b class="negative">−'+money(p.total_deductions_paise)+'</b></div>'+
    '<div class="metric-line"><span>Calculated net salary</span><b>'+money(p.net_salary_paise)+'</b></div>'+
    '<div class="metric-line"><span>Deposit date</span><b>'+escapeHtml(p.deposit_date||'Not entered')+'</b></div>'+
    (p.notes?'<p class="muted">'+escapeHtml(p.notes)+'</p>':'')+
    '<div class="actions"><button class="tiny danger" onclick="deletePayroll('+p.id+')">Remove record</button></div></div>'
  ).join(''):'<p class="muted">No salary records yet. Add a manual payslip entry.</p>';
}
$('payrollForm').addEventListener('submit',async e=>{
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget));
  const payload={month:f.month,base_salary_paise:rupees(f.base),other_earnings_paise:rupees(f.other),overtime_paise:rupees(f.overtime),
    pf_deduction_paise:rupees(f.pf),tax_deduction_paise:rupees(f.tax),other_deductions_paise:rupees(f.other_ded),
    deposited_paise:rupees(f.deposited),deposit_date:f.deposit_date||null,notes:f.notes||''};
  try { const result=await api('/api/payroll',{method:'POST',body:JSON.stringify(payload)});
    message('payrollMessage','Salary record saved for '+result.month+'. Employee-entered and unverified.');
    await refreshPayroll();
  } catch(error) { message('payrollMessage',error.message,true); }
});
async function deletePayroll(id) {
  if(!confirm('Delete this payroll record?')) return;
  try { await api('/api/payroll/'+id,{method:'DELETE'}); await refreshPayroll(); }
  catch(error) { message('payrollMessage',error.message,true); }
}

async function refreshProfile() {
  const p=await api('/api/financial-profile'); const f=$('profileForm');
  f.elements.essentials.value=(p.monthly_essential_paise/100).toFixed(2);
  f.elements.emergency.value=(p.emergency_fund_paise/100).toFixed(2);
  f.elements.dependents.value=p.dependents_count; f.elements.risk.value=p.risk_appetite;
  f.elements.goal.value=p.primary_goal||''; f.elements.consent.checked=!!p.share_with_advisor;
  $('consentStatus').textContent=p.share_with_advisor?'Professional sharing is ON. You can withdraw consent by unchecking and saving.':'Your financial details are private from FINNAL professionals until you explicitly enable sharing.';
}
$('profileForm').addEventListener('submit',async e=>{
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget)); const checked=e.currentTarget.elements.consent.checked;
  try { const p=await api('/api/financial-profile',{method:'PUT',body:JSON.stringify({
    monthly_essential_paise:rupees(f.essentials),emergency_fund_paise:rupees(f.emergency),dependents_count:Number(f.dependents),
    risk_appetite:f.risk,primary_goal:f.goal||'',share_with_advisor:checked
  })});
    message('profileMessage',checked?'Profile saved. You have consented to professional access.':'Profile saved. Professional access is switched off.');
    $('consentStatus').textContent=p.share_with_advisor?'Professional sharing is ON.':'Professional sharing is OFF.';
  } catch(error) { message('profileMessage',error.message,true); }
});

async function refreshAssets() {
  const data=await api('/api/portfolio/assets'); const assets=data.assets||[];
  $('portfolioTotal').innerHTML='<small>Recorded portfolio value</small><strong>'+money(assets.reduce((sum,a)=>sum+a.current_value_paise,0))+'</strong><em>'+assets.length+' recorded items · employee-entered</em>';
  $('assetsList').innerHTML=assets.length?assets.map(a=>
    '<div class="list-row"><div><b>'+escapeHtml(a.name)+'</b><div class="sub">'+escapeHtml(a.asset_type.replace('_',' '))+' · '+escapeHtml(a.institution||'Institution not entered')+'</div><div class="sub">Invested '+money(a.invested_paise)+' · As of '+escapeHtml(a.as_of_date)+'</div></div>'+
    '<div style="text-align:right"><b class="money">'+money(a.current_value_paise)+'</b><div class="sub">'+escapeHtml(a.risk_band)+'</div><button class="tiny danger" onclick="deleteAsset('+a.id+')">Remove</button></div></div>'
  ).join(''):'<p class="muted">No holdings recorded. Add a mutual fund, deposit, stock, gold or cash balance.</p>';
}
$('assetForm').addEventListener('submit',async e=>{
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget));
  try { await api('/api/portfolio/assets',{method:'POST',body:JSON.stringify({
    asset_type:f.asset_type,risk_band:f.risk_band,name:f.name,institution:f.institution||'',
    invested_paise:rupees(f.invested),current_value_paise:rupees(f.current),as_of_date:f.as_of_date||localDate()
  })});
    message('assetMessage','Portfolio item saved.'); e.currentTarget.reset(); initMoneyForms(); await refreshAssets();
  } catch(error) { message('assetMessage',error.message,true); }
});
async function deleteAsset(id) {
  if(!confirm('Remove this portfolio item?')) return;
  try { await api('/api/portfolio/assets/'+id,{method:'DELETE'}); await refreshAssets(); }
  catch(error) { message('assetMessage',error.message,true); }
}

async function refreshAdvisories() {
  const data=await api('/api/advisories'); const rows=data.messages||[];
  $('advisoriesList').innerHTML=rows.length?rows.map(m=>
    '<div class="message-card"><div class="list-row"><h4>'+escapeHtml(m.title)+'</h4><span class="pill">'+escapeHtml(m.topic)+'</span></div>'+
    '<p>'+escapeHtml(m.message)+'</p><div class="sub" style="margin-top:8px">'+escapeHtml(m.created_at.slice(0,10))+(m.read?' · Read':' · New')+'</div>'+
    (!m.read?'<button class="tiny secondary" style="margin-top:8px" onclick="markAdvisoryRead('+m.id+')">Mark as read</button>':'')+'</div>'
  ).join(''):'<p class="muted">No professional guidance received yet.</p>';
}
async function markAdvisoryRead(id) {
  try { await api('/api/advisories/'+id+'/read',{method:'POST'}); await refreshAdvisories(); }
  catch(error) { alert(error.message); }
}
$('loanForm').addEventListener('submit',async e=>{
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget));
  try { await api('/api/loan-requests',{method:'POST',body:JSON.stringify({requested_amount_paise:rupees(f.amount),purpose:f.purpose,notes:f.notes||''})});
    message('loanMessage','Request submitted for preliminary review. This is not a loan approval.');
    e.currentTarget.reset(); await refreshOwnLoans();
  } catch(error) { message('loanMessage',error.message,true); }
});
async function refreshOwnLoans() {
  const data=await api('/api/loan-requests'); const rows=data.requests||[];
  $('loanRequestsList').innerHTML=rows.length?rows.map(r=>
    '<div class="message-card"><div class="list-row"><b>'+money(r.requested_amount_paise)+' requested</b><span class="pill">'+escapeHtml(r.status.replace('_',' '))+'</span></div>'+
    '<p>'+escapeHtml(r.purpose)+'</p>'+(r.indicative_amount_paise!==null?'<p class="muted">Indicative amount: '+money(r.indicative_amount_paise)+'</p>':'')+
    (r.advisor_note?'<p class="muted">Professional note: '+escapeHtml(r.advisor_note)+'</p>':'')+'</div>'
  ).join(''):'<p class="muted">No credit requests submitted.</p>';
}

async function refreshEmployer() {
  const d=await api('/api/employer/overview');
  if(d.suppressed) {
    $('employerMetrics').innerHTML='<div class="notice">'+escapeHtml(d.message)+' Eligible employee count: '+d.employee_count+'.</div>'; return;
  }
  $('employerMetrics').innerHTML='<div class="stats"><div class="stat"><small>Employees</small><strong>'+d.employee_count+'</strong></div>'+
    '<div class="stat"><small>Employees with activity</small><strong>'+d.employees_with_activity+'</strong></div>'+
    '<div class="stat"><small>Activity rate</small><strong>'+d.activity_rate+'%</strong></div>'+
    '<div class="stat"><small>Budget adoption</small><strong>'+d.budget_adoption_rate+'%</strong></div></div>'+
    '<p class="muted">Savings-goal adoption: '+d.savings_goal_adoption_rate+'% · recorded transaction count: '+d.transaction_count+'</p>';
}
$('advisorCreateForm').addEventListener('submit',async e=>{
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget));
  try { const result=await api('/api/employer/advisors',{method:'POST',body:JSON.stringify(f)});
    message('advisorCreateMessage','Professional account created for '+result.email+'. Share the login credentials securely with the authorised professional.');
    e.currentTarget.reset();
  } catch(error) { message('advisorCreateMessage',error.message,true); }
});

async function refreshAdvisorDirectory() {
  const data=await api('/api/advisor/employees'); const rows=data.employees||[];
  $('advisorDirectory').innerHTML=rows.length?rows.map(e=>
    '<button class="directory-item '+(selectedAdvisorEmployeeId===e.id?'active':'')+'" onclick="selectAdvisorEmployee('+e.id+')"><b>'+escapeHtml(e.name)+'</b><small>'+escapeHtml(e.email)+'</small></button>'
  ).join(''):'<p class="muted">No employees have enabled professional sharing yet. Ask employees to review their Financial Profile consent setting.</p>';
  if(selectedAdvisorEmployeeId && !rows.some(e=>e.id===selectedAdvisorEmployeeId)) {
    selectedAdvisorEmployeeId=null; $('advisorClientName').textContent='Select a shared employee';
    $('advisorClientEmail').textContent='Their profile will load here.'; $('advisorClientDetail').textContent='No employee selected.';
    $('advisorySubmit').disabled=true;
  }
}
async function selectAdvisorEmployee(id) {
  selectedAdvisorEmployeeId=id; $('advisorySubmit').disabled=false;
  await refreshAdvisorDirectory();
  try {
    const d=await api('/api/advisor/employees/'+id);
    $('advisorClientName').textContent=d.employee.name; $('advisorClientEmail').textContent=d.employee.email+' · Active consent';
    const p=d.profile, gross=(d.payroll||[])[0];
    $('advisorClientDetail').innerHTML=
      '<div class="stats"><div class="stat"><small>Recorded income</small><strong>'+money(d.cashflow.income_paise)+'</strong></div>'+
      '<div class="stat"><small>Recorded expenses</small><strong>'+money(d.cashflow.expense_paise)+'</strong></div>'+
      '<div class="stat"><small>Emergency reserve</small><strong>'+money(p.emergency_fund_paise)+'</strong></div>'+
      '<div class="stat"><small>Monthly essentials</small><strong>'+money(p.monthly_essential_paise)+'</strong></div></div>'+
      '<div class="metric-line"><span>Risk comfort</span><b>'+escapeHtml(p.risk_appetite)+'</b></div>'+
      '<div class="metric-line"><span>Dependents</span><b>'+p.dependents_count+'</b></div>'+
      '<div class="metric-line"><span>Primary goal</span><b>'+escapeHtml(p.primary_goal||'Not entered')+'</b></div>'+
      (gross?'<h4 style="margin:16px 0 7px">Latest payroll · '+escapeHtml(gross.month)+'</h4><div class="metric-line"><span>Gross salary</span><b>'+money(gross.gross_salary_paise)+'</b></div><div class="metric-line"><span>Deductions</span><b>'+money(gross.total_deductions_paise)+'</b></div><div class="metric-line"><span>Deposited (employee-entered)</span><b>'+money(gross.deposited_paise)+'</b></div>':'<p class="muted">No payroll record shared.</p>')+
      '<h4 style="margin:16px 0 7px">Portfolio holdings</h4>'+
      ((d.assets||[]).length?d.assets.map(a=>'<div class="metric-line"><span>'+escapeHtml(a.name)+' · '+escapeHtml(a.asset_type)+'</span><b>'+money(a.current_value_paise)+'</b></div>').join(''):'<p class="muted">No holdings recorded.</p>')+
      '<p class="muted" style="margin-top:12px">Cash-flow entries: '+d.cashflow.transactions+'. Viewed access is recorded for audit purposes.</p>';
  } catch(error) {
    $('advisorClientDetail').textContent=error.message; $('advisorySubmit').disabled=true;
  }
}
$('advisoryForm').addEventListener('submit',async e=>{
  e.preventDefault(); if(!selectedAdvisorEmployeeId) return;
  const f=Object.fromEntries(new FormData(e.currentTarget));
  try { await api('/api/advisor/employees/'+selectedAdvisorEmployeeId+'/advisories',{method:'POST',body:JSON.stringify(f)});
    message('advisoryMessage','Guidance saved and made available in the employee app.'); e.currentTarget.elements.title.value=''; e.currentTarget.elements.message.value='';
  } catch(error) { message('advisoryMessage',error.message,true); }
});
async function refreshAdvisorLoans() {
  const data=await api('/api/advisor/loan-requests'); const rows=data.requests||[];
  $('advisorLoans').innerHTML=rows.length?rows.map(r=>
    '<div class="message-card"><div class="list-row"><div><b>'+escapeHtml(r.employee_name)+'</b><div class="sub">'+escapeHtml(r.purpose)+'</div></div><b>'+money(r.requested_amount_paise)+'</b></div>'+
    '<p class="muted">'+escapeHtml(r.notes||'No additional context')+' · '+escapeHtml(r.status)+'</p>'+
    '<form class="inline-form" onsubmit="reviewLoan(event,'+r.id+')"><div class="field"><label>Next step</label><select name="status"><option value="under_review">Under review</option><option value="refer_to_lender">Refer to lending partner</option><option value="not_proceeding">Not proceeding</option></select></div>'+
    '<div class="field"><label>Indicative amount (₹)</label><input name="indicative" type="number" min="0" step=".01" placeholder="Optional"></div>'+
    '<div class="field"><label>Professional note</label><input name="note" maxlength="1000" placeholder="Next steps / verification needed"></div><button class="tiny">Save review</button></form></div>'
  ).join(''):'<p class="muted">No loan requests are waiting for review.</p>';
}
async function reviewLoan(event,id) {
  event.preventDefault(); const f=Object.fromEntries(new FormData(event.currentTarget));
  try { await api('/api/advisor/loan-requests/'+id,{method:'PATCH',body:JSON.stringify({
    status:f.status,indicative_amount_paise:f.indicative===''?null:rupees(f.indicative),advisor_note:f.note||''
  })});
    await refreshAdvisorLoans(); alert('Preliminary review saved. This is not a loan approval.');
  } catch(error) { alert(error.message); }
}

if(token) openDashboard();
if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
