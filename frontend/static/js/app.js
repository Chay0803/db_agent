/* ── Config ─────────────────────────────────────────────────────────────────── */
const API = '';  // same origin — FastAPI serves both

/* ── State ──────────────────────────────────────────────────────────────────── */
let allStudents = [];
let agentChartId = 0;

/* ── Boot ────────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', async () => {
  await checkDBStatus();
  loadStudents();
  loadAnalytics();
  loadRanking();
  loadAtRisk();
  loadCourses();
});

async function checkDBStatus() {
  try {
    await fetch(`${API}/api/analytics/summary`);
    document.getElementById('status-text').textContent = 'Database connected';
  } catch {
    document.getElementById('status-text').textContent = 'DB offline';
    document.querySelector('.status-dot').style.background = '#f43f5e';
  }
}

/* ── Navigation ──────────────────────────────────────────────────────────────── */
const VIEW_TITLES = {
  agent: 'AI Agent', students: 'Students', analytics: 'Analytics',
  ranking: 'Rankings', atrisk: 'At-Risk Students', courses: 'Courses',
};

function switchView(name, btn) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`view-${name}`).classList.add('active');
  btn.classList.add('active');
  document.getElementById('view-title').textContent = VIEW_TITLES[name] || name;
  if (name === 'students')  loadStudents();
  if (name === 'analytics') loadAnalytics();
  if (name === 'ranking')   loadRanking();
  if (name === 'atrisk')    loadAtRisk();
  if (name === 'courses')   loadCourses();
}

function refreshCurrentView() {
  loadStudents(); loadAnalytics(); loadRanking(); loadAtRisk(); loadCourses();
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

/* ── AI Agent ────────────────────────────────────────────────────────────────── */
function handleChatKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAgentMessage(); }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 140) + 'px';
}

function sendQuick(text) {
  document.getElementById('agent-input').value = text;
  switchView('agent', document.querySelector('[data-view="agent"]'));
  sendAgentMessage();
}

async function sendAgentMessage() {
  const inp = document.getElementById('agent-input');
  const msg = inp.value.trim();
  if (!msg) return;
  inp.value = '';
  autoResize(inp);
  document.getElementById('send-btn').disabled = true;

  const welcome = document.querySelector('.chat-welcome');
  if (welcome) welcome.remove();

  appendChatMsg('user', msg);
  const thinkEl = appendThinking();

  try {
    const res = await fetch(`${API}/api/agent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
    });
    const data = await res.json();
    thinkEl.remove();
    appendAgentResponse(data.response, data.db_action);

    if (data.db_action && !data.db_action.error) {
      loadStudents(); loadAnalytics(); loadRanking(); loadAtRisk();
    }
  } catch {
    thinkEl.remove();
    appendAgentBubble('⚠️ Could not reach the backend. Make sure FastAPI is running on port 8000.');
  }

  document.getElementById('send-btn').disabled = false;
}

function appendChatMsg(role, text) {
  const container = document.getElementById('chat-container');
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  const bubble = document.createElement('div');
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;
  div.appendChild(bubble);
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function appendThinking() {
  const container = document.getElementById('chat-container');
  const div = document.createElement('div');
  div.className = 'chat-msg agent';
  div.innerHTML = `<div class="thinking-bubble"><span class="thinking-label">Agent is thinking</span><div class="dots"><span></span><span></span><span></span></div></div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function appendAgentBubble(html) {
  const container = document.getElementById('chat-container');
  const div = document.createElement('div');
  div.className = 'chat-msg agent';
  const bubble = document.createElement('div');
  bubble.className = 'bubble agent';
  bubble.innerHTML = html;
  div.appendChild(bubble);
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function appendAgentResponse(markdown, dbAction) {
  const container = document.getElementById('chat-container');
  const div = document.createElement('div');
  div.className = 'chat-msg agent';

  const bubble = document.createElement('div');
  bubble.className = 'bubble agent';
  bubble.innerHTML = renderMarkdown(markdown);
  div.appendChild(bubble);

  if (dbAction?.visualization) {
    renderAgentVisualization(div, dbAction.visualization);
  }

  if (dbAction && !dbAction.error) {
    const badge = document.createElement('div');
    const icons = { insert: '✦ Inserted', update: '✎ Updated', delete: '✕ Deleted' };
    badge.className = `db-action-badge ${dbAction.operation}`;
    badge.textContent = `${icons[dbAction.operation] || dbAction.operation} — ID ${dbAction.student_id}${dbAction.name ? ': ' + dbAction.name : ''}`;
    div.appendChild(badge);
  }

  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function renderAgentVisualization(container, visualization) {
  if (visualization.type === 'schema_relationships') {
    renderSchemaDiagram(container);
    return;
  }

  const supportedTypes = ['gpa_by_student', 'gpa_by_department', 'count_by_status'];
  if (!supportedTypes.includes(visualization.type) || !visualization.values?.length) return;

  const chartCard = document.createElement('div');
  chartCard.className = 'agent-chart-card';
  const title = document.createElement('div');
  title.className = 'agent-chart-title';
  title.textContent = visualization.title || 'Query results';
  const chartWrap = document.createElement('div');
  chartWrap.className = 'agent-chart-wrap';
  const canvas = document.createElement('canvas');
  canvas.id = `agent-chart-${++agentChartId}`;
  chartWrap.appendChild(canvas);
  chartCard.append(title, chartWrap);
  container.appendChild(chartCard);

  const isStatusChart = visualization.type === 'count_by_status';
  new Chart(canvas, {
    type: isStatusChart ? 'doughnut' : 'bar',
    data: {
      labels: visualization.labels,
      datasets: [{
        label: isStatusChart ? 'Students' : 'GPA',
        data: visualization.values,
        backgroundColor: isStatusChart
          ? ['rgba(5,150,105,0.8)', 'rgba(225,29,72,0.8)', 'rgba(2,132,199,0.8)']
          : 'rgba(99,102,241,0.72)',
        borderColor: isStatusChart ? ['#059669', '#e11d48', '#0284c7'] : '#6366f1',
        borderWidth: 1,
        borderRadius: isStatusChart ? 0 : 5,
        borderSkipped: false,
      }],
    },
    options: {
      indexAxis: isStatusChart ? 'x' : 'y',
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          display: !isStatusChart,
          min: 0,
          max: visualization.type === 'gpa_by_student' || visualization.type === 'gpa_by_department' ? 4 : undefined,
          grid: { color: 'rgba(0,0,0,0.05)' },
          ticks: { stepSize: 1, color: '#7c7892', font: { family: 'DM Sans', size: 11 } },
        },
        y: {
          display: !isStatusChart,
          grid: { display: false },
          ticks: { color: '#4b4760', font: { family: 'DM Sans', size: 11 } },
        },
      },
      plugins: {
        legend: { display: isStatusChart, position: 'bottom' },
        tooltip: { callbacks: { label: context => isStatusChart ? ` ${context.raw} students` : ` GPA ${context.raw.toFixed(1)}` } },
      },
    },
  });
}

function renderSchemaDiagram(container) {
  const diagram = document.createElement('div');
  diagram.className = 'schema-diagram';
  diagram.innerHTML = `
    <div class="agent-chart-title">Database relationships</div>
    <div class="schema-grid">
      <div class="schema-table">
        <strong>students</strong>
        <span>id · name · age · department</span>
        <span>gpa · email · enrollment_year</span>
        <span>status</span>
      </div>
      <div class="schema-table schema-table--wide">
        <strong>enrollments</strong>
        <span>id · student_id · course_id</span>
        <span>grade · semester</span>
      </div>
      <div class="schema-table">
        <strong>courses</strong>
        <span>id · name · department</span>
        <span>credits</span>
      </div>
    </div>
    <div class="schema-links">
      <div class="schema-link"><span>students.id</span><b>1 : many</b><span>enrollments.student_id</span></div>
      <div class="schema-link"><span>courses.id</span><b>1 : many</b><span>enrollments.course_id</span></div>
    </div>`;
  container.appendChild(diagram);
}

function renderMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);
  // code blocks
  html = html.replace(/```[\s\S]*?```/g, m => {
    const code = m.replace(/^```\w*\n?/, '').replace(/```$/, '');
    return `<pre><code>${code.trim()}</code></pre>`;
  });
  // inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // italic
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // markdown tables
  html = renderMDTables(html);
  // bullets
  html = html.replace(/^[•\-\*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>');
  // line breaks
  html = html.replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>');
  return html;
}

function renderMDTables(html) {
  return html.replace(/(\|.+\|\n\|[-| :]+\|\n(?:\|.+\|\n?)+)/g, match => {
    const lines = match.trim().split('\n').filter(l => l.trim());
    if (lines.length < 3) return match;
    const headers = lines[0].split('|').slice(1,-1).map(h => `<th>${h.trim()}</th>`).join('');
    const rows = lines.slice(2).map(line =>
      '<tr>' + line.split('|').slice(1,-1).map(c => `<td>${c.trim()}</td>`).join('') + '</tr>'
    ).join('');
    return `<table><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table>`;
  });
}

function escapeHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Students ────────────────────────────────────────────────────────────────── */
async function loadStudents() {
  try {
    const res = await fetch(`${API}/api/students`);
    allStudents = await res.json();
    renderStudentsTable(allStudents);
  } catch {}
}

function renderStudentsTable(students) {
  const tbody = document.getElementById('students-tbody');
  if (!tbody) return;
  tbody.innerHTML = students.map(s => `
    <tr>
      <td>${s.id}</td>
      <td><strong>${s.name}</strong></td>
      <td>${s.age}</td>
      <td>${s.department}</td>
      <td class="${gpaClass(s.gpa)}">${s.gpa.toFixed(1)}</td>
      <td>${s.enrollment_year}</td>
      <td><span class="badge ${s.status}">${s.status}</span></td>
      <td>
        <button class="btn-icon" onclick="openEditModal(${s.id})" title="Edit">✎</button>
        <button class="btn-icon btn-danger" onclick="deleteStudent(${s.id},'${s.name}')" title="Delete">✕</button>
        <button class="btn-icon" onclick="viewReport(${s.id})" title="Report">📋</button>
      </td>
    </tr>`).join('');
}

function gpaClass(gpa) {
  return gpa >= 3.5 ? 'gpa-high' : gpa >= 2.5 ? 'gpa-mid' : 'gpa-low';
}

function filterStudents() {
  const q = document.getElementById('student-search').value.toLowerCase();
  renderStudentsTable(allStudents.filter(s =>
    s.name.toLowerCase().includes(q) || s.department.toLowerCase().includes(q)
  ));
}

/* ── Analytics ───────────────────────────────────────────────────────────────── */
let deptChart = null;
let statusChart = null;
let gpaDistChart = null;

async function loadAnalytics() {
  try {
    const [summary, depts] = await Promise.all([
      fetch(`${API}/api/analytics/summary`).then(r => r.json()),
      fetch(`${API}/api/analytics/department`).then(r => r.json()),
    ]);

    // ── Metric Cards ──────────────────────────────────────────────────────────
    const grid = document.getElementById('metrics-grid');
    if (grid) {
      grid.innerHTML = [
        { label:'Total Students',  value: summary.total_students,           sub:'enrolled' },
        { label:'Average GPA',     value: summary.average_gpa?.toFixed(2),  sub:'across all departments' },
        { label:'Active',          value: summary.active,                   sub:'in good standing' },
        { label:'On Probation',    value: summary.probation,                sub:'need attention' },
        { label:'Graduated',       value: summary.graduated,                sub:'completed degree' },
        { label:'Top GPA',         value: summary.highest_gpa?.toFixed(1),  sub: summary.top_student },
      ].map(m => `
        <div class="metric-card">
          <div class="metric-label">${m.label}</div>
          <div class="metric-value">${m.value ?? '—'}</div>
          <div class="metric-sub">${m.sub}</div>
        </div>`).join('');
    }

    // ── Dept Table ────────────────────────────────────────────────────────────
    const tbody = document.getElementById('dept-tbody');
    if (tbody) {
      tbody.innerHTML = depts.map(d => `
        <tr>
          <td>${d.department}</td>
          <td>${d.count}</td>
          <td class="${gpaClass(d.avg_gpa)}">${d.avg_gpa?.toFixed(2)}</td>
          <td class="gpa-high">${d.max_gpa?.toFixed(1)}</td>
          <td class="gpa-low">${d.min_gpa?.toFixed(1)}</td>
        </tr>`).join('');
    }

    // ── Charts ────────────────────────────────────────────────────────────────
    renderDeptChart(depts);
    renderStatusChart(summary);
    renderGpaDistChart(depts);

  } catch(e) { console.error('Analytics error', e); }
}

function renderDeptChart(depts) {
  const ctx = document.getElementById('dept-chart');
  if (!ctx) return;
  if (deptChart) deptChart.destroy();

  const labels = depts.map(d => d.department.replace(' Engineering','').replace(' Science',''));
  const avgGpas = depts.map(d => d.avg_gpa);
  const maxGpas = depts.map(d => d.max_gpa);
  const minGpas = depts.map(d => d.min_gpa);

  deptChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Avg GPA',
          data: avgGpas,
          backgroundColor: 'rgba(99,102,241,0.75)',
          borderColor: 'rgba(99,102,241,1)',
          borderWidth: 2,
          borderRadius: 6,
          borderSkipped: false,
        },
        {
          label: 'Max GPA',
          data: maxGpas,
          backgroundColor: 'rgba(5,150,105,0.6)',
          borderColor: 'rgba(5,150,105,1)',
          borderWidth: 2,
          borderRadius: 6,
          borderSkipped: false,
        },
        {
          label: 'Min GPA',
          data: minGpas,
          backgroundColor: 'rgba(225,29,72,0.55)',
          borderColor: 'rgba(225,29,72,1)',
          borderWidth: 2,
          borderRadius: 6,
          borderSkipped: false,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { font: { family: 'DM Sans', size: 12 }, color: '#4b4760', boxWidth: 12, padding: 16 } },
        tooltip: { bodyFont: { family: 'DM Sans' }, titleFont: { family: 'DM Sans' } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { family: 'DM Sans', size: 11 }, color: '#7c7892' } },
        y: {
          min: 0, max: 4.2,
          grid: { color: 'rgba(0,0,0,0.05)' },
          ticks: { font: { family: 'DM Sans', size: 11 }, color: '#7c7892', stepSize: 0.5 },
        },
      },
    },
  });
}

function renderStatusChart(summary) {
  const ctx = document.getElementById('status-chart');
  if (!ctx) return;
  if (statusChart) statusChart.destroy();

  statusChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Active', 'On Probation', 'Graduated'],
      datasets: [{
        data: [summary.active || 0, summary.probation || 0, summary.graduated || 0],
        backgroundColor: ['rgba(5,150,105,0.8)', 'rgba(225,29,72,0.8)', 'rgba(2,132,199,0.8)'],
        borderColor: ['#059669', '#e11d48', '#0284c7'],
        borderWidth: 2,
        hoverOffset: 6,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: '68%',
      plugins: {
        legend: { position: 'bottom', labels: { font: { family: 'DM Sans', size: 12 }, color: '#4b4760', boxWidth: 10, padding: 16 } },
        tooltip: { bodyFont: { family: 'DM Sans' }, titleFont: { family: 'DM Sans' } },
      },
    },
  });
}

function renderGpaDistChart(depts) {
  const ctx = document.getElementById('gpa-dist-chart');
  if (!ctx) return;
  if (gpaDistChart) gpaDistChart.destroy();

  const labels = depts.map(d => d.department.replace(' Engineering','').replace(' Science',''));
  const counts = depts.map(d => d.count);

  gpaDistChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Students',
        data: counts,
        backgroundColor: [
          'rgba(99,102,241,0.75)', 'rgba(124,58,237,0.75)', 'rgba(2,132,199,0.75)',
          'rgba(217,119,6,0.75)', 'rgba(5,150,105,0.75)',
        ],
        borderColor: [
          'rgba(99,102,241,1)', 'rgba(124,58,237,1)', 'rgba(2,132,199,1)',
          'rgba(217,119,6,1)', 'rgba(5,150,105,1)',
        ],
        borderWidth: 2,
        borderRadius: 6,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: { bodyFont: { family: 'DM Sans' }, titleFont: { family: 'DM Sans' } },
      },
      scales: {
        x: { grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { font: { family: 'DM Sans', size: 11 }, color: '#7c7892', stepSize: 1 } },
        y: { grid: { display: false }, ticks: { font: { family: 'DM Sans', size: 11 }, color: '#7c7892' } },
      },
    },
  });
}

/* ── Ranking ─────────────────────────────────────────────────────────────────── */
async function loadRanking() {
  try {
    const ranking = await fetch(`${API}/api/analytics/ranking`).then(r => r.json());
    const tbody = document.getElementById('ranking-tbody');
    if (!tbody) return;
    tbody.innerHTML = ranking.map(r => `
      <tr>
        <td><strong>#${r.rank}</strong></td>
        <td>${r.name}</td>
        <td>${r.department}</td>
        <td class="${gpaClass(r.gpa)}">${r.gpa.toFixed(1)}</td>
        <td>${r.rank === 1 ? '🥇' : r.rank === 2 ? '🥈' : r.rank === 3 ? '🥉' : ''}</td>
      </tr>`).join('');
  } catch {}
}

/* ── At-Risk ─────────────────────────────────────────────────────────────────── */
async function loadAtRisk() {
  try {
    const students = await fetch(`${API}/api/analytics/at-risk`).then(r => r.json());
    const container = document.getElementById('atrisk-container');
    if (!container) return;
    if (!students.length) {
      container.innerHTML = '<p style="color:var(--t3);padding:20px">No at-risk students found. 🎉</p>';
      return;
    }
    container.innerHTML = `<div class="risk-grid">${students.map(s => `
      <div class="risk-card">
        <div class="risk-name">${s.name}</div>
        <div class="risk-meta">
          ID: ${s.id}<br>
          Department: ${s.department}<br>
          GPA: <span class="gpa-low">${s.gpa.toFixed(1)}</span><br>
          Status: <span class="badge ${s.status}">${s.status}</span>
        </div>
        <div class="risk-reason">⚠ ${s.risk_reason}</div>
      </div>`).join('')}</div>`;
  } catch {}
}

/* ── Courses ─────────────────────────────────────────────────────────────────── */
async function loadCourses() {
  try {
    const courses = await fetch(`${API}/api/courses`).then(r => r.json());
    const tbody = document.getElementById('courses-tbody');
    if (!tbody) return;
    tbody.innerHTML = courses.map(c => `
      <tr>
        <td>${c.id}</td>
        <td>${c.name}</td>
        <td>${c.department}</td>
        <td>${c.credits}</td>
      </tr>`).join('');
  } catch {}
}

/* ── Modal: Add / Edit ───────────────────────────────────────────────────────── */
function openAddModal() {
  document.getElementById('modal-title').textContent = 'Add Student';
  document.getElementById('modal-save-btn').textContent = 'Add Student';
  document.getElementById('edit-id').value = '';
  clearModalForm();
  document.getElementById('modal-overlay').classList.add('open');
}

async function openEditModal(id) {
  try {
    const s = await fetch(`${API}/api/students/${id}`).then(r => r.json());
    document.getElementById('modal-title').textContent = 'Edit Student';
    document.getElementById('modal-save-btn').textContent = 'Save Changes';
    document.getElementById('edit-id').value = s.id;
    document.getElementById('f-name').value = s.name;
    document.getElementById('f-age').value = s.age;
    document.getElementById('f-gpa').value = s.gpa;
    document.getElementById('f-department').value = s.department;
    document.getElementById('f-email').value = s.email;
    document.getElementById('f-year').value = s.enrollment_year;
    document.getElementById('f-status').value = s.status;
    document.getElementById('modal-overlay').classList.add('open');
  } catch {}
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

function clearModalForm() {
  ['f-name','f-age','f-gpa','f-email','f-year'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('f-department').value = 'Computer Science';
  document.getElementById('f-status').value = 'active';
}

async function saveStudent() {
  const editId = document.getElementById('edit-id').value;
  const payload = {
    name: document.getElementById('f-name').value,
    age: parseInt(document.getElementById('f-age').value),
    department: document.getElementById('f-department').value,
    gpa: parseFloat(document.getElementById('f-gpa').value),
    email: document.getElementById('f-email').value,
    enrollment_year: parseInt(document.getElementById('f-year').value),
    status: document.getElementById('f-status').value,
  };
  try {
    if (editId) {
      await fetch(`${API}/api/students/${editId}`, {
        method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
      });
    } else {
      await fetch(`${API}/api/students`, {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
      });
    }
    closeModal();
    loadStudents(); loadAnalytics(); loadRanking(); loadAtRisk();
  } catch (e) {
    alert('Error saving: ' + e.message);
  }
}

async function deleteStudent(id, name) {
  if (!confirm(`Delete ${name}? This cannot be undone.`)) return;
  try {
    await fetch(`${API}/api/students/${id}`, { method: 'DELETE' });
    loadStudents(); loadAnalytics(); loadRanking(); loadAtRisk();
  } catch {}
}

async function viewReport(id) {
  try {
    const r = await fetch(`${API}/api/students/${id}/report`).then(res => res.json());
    const s = r.student, a = r.analytics;
    const courses = r.enrollments.map(e => `${e.course} (${e.grade})`).join(', ') || 'None';
    alert(
      `📋 Report — ${s.name}\n\n` +
      `Department : ${s.department}\n` +
      `GPA        : ${s.gpa}  |  Status: ${s.status}\n` +
      `Age        : ${s.age}  |  Enrolled: ${s.enrollment_year}\n` +
      `Email      : ${s.email}\n\n` +
      `Overall Rank      : #${a.overall_rank}\n` +
      `Dept Avg GPA      : ${a.department_avg_gpa}\n` +
      `Courses Enrolled  : ${a.courses_enrolled}  (${a.total_credits} credits)\n\n` +
      `Courses: ${courses}`
    );
  } catch {}
}
/* ── Voice Assistant ───────────────────────────────────────────────────────────
   Push-to-talk: hold the mic button, speak, release. The clip is sent to
   /api/voice/converse which runs STT → RAG+Gemini → TTS in one round trip
   and returns the transcript, the answer text, and the answer as audio. */

const VOICE_SESSION_ID = (crypto.randomUUID ? crypto.randomUUID() : `sess-${Date.now()}-${Math.random().toString(36).slice(2)}`);

let voiceMediaRecorder = null;
let voiceAudioChunks = [];
let voiceIsRecording = false;

function appendVoiceMsg(role, text) {
  const container = document.getElementById('chat-container');
  const welcome = container.querySelector('.chat-welcome');
  if (welcome) welcome.remove();
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  const bubble = document.createElement('div');
  bubble.className = `bubble ${role}`;
  bubble.innerHTML = role === 'agent' ? renderMarkdown(text) : text;
  div.appendChild(bubble);
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function appendVoiceThinking() {
  const container = document.getElementById('chat-container');
  const div = document.createElement('div');
  div.className = 'chat-msg agent';
  div.innerHTML = `<div class="thinking-bubble"><span class="thinking-label">Listening / thinking</span><div class="dots"><span></span><span></span><span></span></div></div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

async function startRecording(evt) {
  if (evt) evt.preventDefault();
  if (voiceIsRecording) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    voiceAudioChunks = [];
    voiceMediaRecorder = new MediaRecorder(stream);
    voiceMediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) voiceAudioChunks.push(e.data); };
    voiceMediaRecorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      if (voiceAudioChunks.length) sendVoiceRecording(new Blob(voiceAudioChunks, { type: voiceMediaRecorder.mimeType || 'audio/webm' }));
    };
    voiceMediaRecorder.start();
    voiceIsRecording = true;
    document.getElementById('mic-btn').classList.add('recording');
    document.getElementById('mic-hint').textContent = 'Recording… release to send';
  } catch (err) {
    appendVoiceMsg('agent', '⚠️ Microphone access is required for voice chat: ' + err.message);
  }
}

function stopRecording(evt) {
  if (evt) evt.preventDefault();
  if (!voiceIsRecording || !voiceMediaRecorder) return;
  voiceIsRecording = false;
  document.getElementById('mic-btn').classList.remove('recording');
  document.getElementById('mic-hint').textContent = 'Hold to talk';
  voiceMediaRecorder.stop();
}

function cancelIfRecording() {
  if (voiceIsRecording) stopRecording();
}

async function sendVoiceRecording(blob) {
  const thinkEl = appendVoiceThinking();
  try {
    const form = new FormData();
    form.append('audio', blob, 'clip.webm');
    const res = await fetch(`${API}/api/voice/converse?session_id=${encodeURIComponent(VOICE_SESSION_ID)}`, {
      method: 'POST',
      body: form,
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    thinkEl.remove();
    appendVoiceMsg('user', data.transcript);
    appendVoiceMsg('agent', data.response);
    playBase64Audio(data.audio_b64);
  } catch (err) {
    thinkEl.remove();
    appendVoiceMsg('agent', '⚠️ Could not process that clip: ' + err.message);
  }
}

function playBase64Audio(b64) {
  if (!b64) return;
  const audio = new Audio(`data:audio/mpeg;base64,${b64}`);
  audio.play().catch(() => {});
}
