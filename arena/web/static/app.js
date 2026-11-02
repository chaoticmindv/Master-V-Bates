/* Arena.ai Desktop Client — Frontend */

let currentMode = 'battle';
let currentModality = 'auto';
let selectedModel = null;
let selectedModelB = null;
let models = [];
let isStreaming = false;
let isUploading = false;
let chatCounter = 0;
let isLoggedIn = false;
let accounts = [];
let loginAddMode = false;
let uploadedFiles = [];
let lastSentAttachments = [];
let currentChatId = null;
let streamAbort = null;

const MODE_NEEDS_MODEL = ['direct', 'side-by-side', 'agent'];
const MODE_LABELS = { battle: 'Battle', direct: 'Direct', 'side-by-side': 'Side by Side', agent: 'Agent' };

const ORG_LOGOS = {
  google: `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.96 10.96 0 0 0 1 12c0 1.77.42 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg>`,
  openai: `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M22.28 9.37a6.17 6.17 0 0 0-.53-5.07 6.24 6.24 0 0 0-6.73-2.98A6.2 6.2 0 0 0 10.36 0a6.24 6.24 0 0 0-5.95 4.33A6.17 6.17 0 0 0 .27 8.06a6.24 6.24 0 0 0 .77 7.32 6.17 6.17 0 0 0 .53 5.07 6.24 6.24 0 0 0 6.73 2.98A6.2 6.2 0 0 0 12.96 24a6.24 6.24 0 0 0 5.95-4.33 6.17 6.17 0 0 0 4.14-3.73 6.24 6.24 0 0 0-.77-6.57z" fill="#10B981"/></svg>`,
  anthropic: `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M13.83 2H16.7l6.3 20h-2.87l-1.46-4.83H12.6L14.04 14h4.5L15.27 4.37 10.15 22H7.28L13.83 2zM1 22L7.2 2h2.87l-1.85 5.97L4.69 22H1z" fill="#F97316"/></svg>`,
  xai: `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M3 3l7.5 9L3 21h2.2l6.3-7.56L17.8 21H21l-7.8-9.36L20.4 3h-2.2l-5.7 6.84L6.2 3H3z" fill="#D946EF"/></svg>`,
  meta: `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M6.91 4.24C5.21 4.24 3.76 5.6 2.73 7.74 1.46 10.38.87 13.59.87 15.46c0 2.74 1.16 4.3 3.24 4.3 1.62 0 3.15-1.34 4.88-4.28.73-1.23 1.44-2.67 2.15-4.28l.98-2.27c.89-2.04 1.92-3.87 3.12-5.14A5.87 5.87 0 0 1 19.35 2c2.39 0 3.78 1.74 3.78 4.45 0 3.09-1.4 6.63-3.52 8.92a8.97 8.97 0 0 1-2.8 2.22" fill="none" stroke="#06B6D4" stroke-width="2"/></svg>`,
  mistral: `<svg viewBox="0 0 24 24" width="18" height="18"><rect x="2" y="2" width="5" height="5" fill="#F7D046"/><rect x="9.5" y="2" width="5" height="5" fill="#F7D046"/><rect x="17" y="2" width="5" height="5" fill="#EF4444"/><rect x="2" y="9.5" width="5" height="5" fill="#F7D046"/><rect x="9.5" y="9.5" width="5" height="5" fill="#EF4444"/><rect x="17" y="9.5" width="5" height="5" fill="#F7D046"/><rect x="2" y="17" width="5" height="5" fill="#EF4444"/><rect x="9.5" y="17" width="5" height="5" fill="#F7D046"/><rect x="17" y="17" width="5" height="5" fill="#F7D046"/></svg>`,
  deepseek: `<svg viewBox="0 0 24 24" width="18" height="18"><circle cx="12" cy="12" r="10" fill="#3B82F6"/><text x="12" y="16" text-anchor="middle" fill="white" font-size="12" font-weight="700" font-family="sans-serif">D</text></svg>`,
  alibaba: `<svg viewBox="0 0 24 24" width="18" height="18"><circle cx="12" cy="12" r="10" fill="#F59E0B"/><text x="12" y="16" text-anchor="middle" fill="white" font-size="11" font-weight="700" font-family="sans-serif">Q</text></svg>`,
  nvidia: `<svg viewBox="0 0 24 24" width="18" height="18"><path d="M9.2 9.48v-.72c.04 0 .08 0 .14-.01 2.1-.14 3.66 1.71 3.66 1.71s-1.74 2.04-3.52 2.04c-.11 0-.2-.01-.28-.03V9.48zm0-2.97v1.68l.06-.01c2.68-.2 4.63 2.2 4.63 2.2s-2.35 2.72-4.47 2.72a2.5 2.5 0 0 1-.22-.01v1.1c.06 0 .13.01.2.01 2.54 0 4.42-1.3 6.22-2.82a17.4 17.4 0 0 1 1.37 1.12c-2.06 1.66-6.86 3.22-7.77 3.22h-.02v1.26C11.5 16.96 18 13.18 18 13.18a21.88 21.88 0 0 0-4.06-3.84c1.3-1.14 2.82-1.85 2.82-1.85A16.67 16.67 0 0 0 9.2 6.51z" fill="#76B900"/></svg>`,
};

function getOrgLogo(org) {
  const key = (org || '').toLowerCase();
  if (ORG_LOGOS[key]) return ORG_LOGOS[key];
  const initial = (org || '?')[0].toUpperCase();
  const colors = { minimax: '#14B8A6', zai: '#8B5CF6', stepfun: '#EC4899', bytedance: '#00D1FF', tencent: '#2B82EE', amazon: '#FF9900', microsoft: '#00BCF2', ibm: '#054ADA' };
  const color = colors[key] || '#C7C2BC';
  return `<svg viewBox="0 0 24 24" width="18" height="18"><circle cx="12" cy="12" r="10" fill="${color}"/><text x="12" y="16" text-anchor="middle" fill="white" font-size="11" font-weight="700" font-family="sans-serif">${initial}</text></svg>`;
}

document.addEventListener('DOMContentLoaded', () => {
  checkStatus();
  loadModels();
  loadChatHistory();
  loadAccounts();
  document.getElementById('chatInput').focus();
});

/* ── Custom title bar (the desktop window is frameless) ── */
const _tb = () => window.pywebview && window.pywebview.api;
function tbMinimize() { _tb()?.tb_minimize(); }
function tbToggleMaximize() { _tb()?.tb_toggle_maximize(); }
function tbClose() { _tb()?.tb_close(); }

/* Called by the shell when the window is maximized/restored, to swap the icon. */
function titlebarState(maximized) {
  const btn = document.getElementById('tbMaxBtn');
  if (!btn) return;
  btn.classList.toggle('minimized', !!maximized);
  btn.title = maximized ? 'Restore' : 'Maximize';
  btn.innerHTML = maximized
    ? '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3"><rect x="2" y="4" width="6" height="6" rx="1"/><path d="M4.2 4V2.6a1 1 0 0 1 1-1h4.2a1 1 0 0 1 1 1v4.2a1 1 0 0 1-1 1H8"/></svg>'
    : '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="2.5" y="2.5" width="7" height="7" rx="1"/></svg>';
}

/* ── API ── */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  return res.json();
}

/* ── Auth ── */
let statusTimer = null;
async function checkStatus(refresh) {
  clearTimeout(statusTimer);
  try {
    const s = await api('/api/status' + (refresh ? '?refresh=1' : ''));
    window.appState = s;
    hideSplash();
    permMode = s.permission_mode || 'default';
    updatePermUI();
    currentMode = s.mode || currentMode;
    currentModality = s.modality || currentModality;
    if (currentMode === 'agent' && currentModality !== 'auto') {
      currentModality = 'auto';
      api('/api/modality', { method: 'POST', body: JSON.stringify({ modality: 'auto' }) });
    }
    updateModeUI();
    updateModalityUI();
    if (modelsWanted !== apiModalityForUI()) loadModels();  // status restored a different modality than the first list
    const ws = document.getElementById('settingsWorkspace');
    if (ws) ws.textContent = s.workspace || '-';
    updateWsChip(s.workspace);
    const pd = document.getElementById('settingsProjects');
    if (pd) pd.textContent = s.projects_dir || '-';
    const el = document.getElementById('userEmail');
    const av = document.getElementById('userAvatar');
    const name = s.full_name || s.email;
    if (s.authenticated) {
      el.textContent = name || (s.loading ? 'Connecting...' : 'Guest session');
      av.textContent = '';
      if (s.avatar_url) {
        const img = new Image();
        img.className = 'avatar-img';
        img.alt = '';
        img.src = s.avatar_url;
        av.appendChild(img);
      } else {
        av.textContent = (name || 'U')[0].toUpperCase();
      }
      isLoggedIn = true;
      updateAuthUI(true, name || 'arena.ai user');
    } else {
      el.textContent = s.session_error ? 'Session expired: sign in' : 'Sign in';
      av.textContent = '?';
      isLoggedIn = false;
      updateAuthUI(false);
    }
    const eng = s.engine || {};
    updateConnectionBadge(eng.challenge ? 'check' : s.loading ? 'loading' : s.offline ? 'error'
      : s.authenticated ? 'connected' : s.session_error ? 'expired' : 'disconnected');
    if (s.loading || eng.challenge) statusTimer = setTimeout(checkStatus, 2500);
  } catch (e) {
    updateConnectionBadge('error');
    statusTimer = setTimeout(checkStatus, 5000);
  }
}

function updateConnectionBadge(state) {
  let badge = document.getElementById('connBadge');
  if (!badge) {
    badge = document.createElement('div');
    badge.id = 'connBadge';
    badge.className = 'conn-badge';
    const footer = document.querySelector('.input-footer');
    if (footer) footer.prepend(badge);
  }
  const labels = { connected: 'Connected', disconnected: 'Not signed in', expired: 'Session expired', error: 'Offline',
    loading: 'Connecting to arena.ai...', check: 'arena.ai needs a check: click' };
  badge.onclick = state === 'check' || state === 'loading' ? showEngine : null;
  badge.className = 'conn-badge ' + state;
  badge.textContent = labels[state] || state;
}

function updateAuthUI(loggedIn, email) {
  const settingsLogin = document.getElementById('settingsLoginBtn');
  const settingsLogout = document.getElementById('settingsLogoutBtn');
  const accountLogout = document.getElementById('accountLogoutBtn');
  const settingsAuth = document.getElementById('settingsAuthStatus');
  const settingsEmail = document.getElementById('settingsEmail');

  if (loggedIn) {
    if (settingsLogin) settingsLogin.style.display = 'none';
    if (accountLogout) accountLogout.style.display = '';
    if (settingsLogout) settingsLogout.style.display = '';
    if (settingsAuth) { settingsAuth.textContent = 'Logged in'; settingsAuth.style.color = 'var(--interactive-positive)'; }
    if (settingsEmail) settingsEmail.textContent = email || '—';
  } else {
    if (settingsLogin) settingsLogin.style.display = '';
    if (accountLogout) accountLogout.style.display = 'none';
    if (settingsLogout) settingsLogout.style.display = 'none';
    if (settingsAuth) { settingsAuth.textContent = 'Not logged in'; settingsAuth.style.color = 'var(--text-muted)'; }
    if (settingsEmail) settingsEmail.textContent = '—';
  }
}

/* ── Accounts ── */
async function loadAccounts() {
  try {
    const r = await api('/api/accounts');
    accounts = Array.isArray(r.accounts) ? r.accounts : [];
    renderAccountMenu();
  } catch (_) {}
}

function renderAccountMenu() {
  const list = document.getElementById('accountList');
  if (!list) return;
  if (!accounts.length) {
    list.innerHTML = '<div class="account-empty">No saved accounts</div>';
  } else {
    list.innerHTML = accounts.map(a => {
      const initial = (a.email || '?')[0].toUpperCase();
      const avatar = a.avatar_url
        ? `<img src="${attr(safeUrl(a.avatar_url))}" alt="">`
        : esc(initial);
      return `<button type="button" class="account-item${a.active ? ' active' : ''}" data-account="${attr(a.id)}">
        <span class="account-avatar">${avatar}</span>
        <span class="account-info"><span class="account-email">${esc(a.email || 'Account')}</span>${a.name ? `<span class="account-name">${esc(a.name)}</span>` : ''}</span>
        ${a.active ? '<span class="account-check">current</span>' : '<span class="account-remove" data-remove="1" title="Remove account">&times;</span>'}
      </button>`;
    }).join('');
    list.querySelectorAll('.account-item').forEach(btn => {
      btn.onclick = e => {
        const id = btn.dataset.account;
        if (e.target.closest('[data-remove]')) removeAccount(id);
        else switchAccount(id);
      };
    });
  }
  const logout = document.getElementById('accountLogoutBtn');
  if (logout) logout.style.display = accounts.some(a => a.active) ? '' : 'none';
}

function toggleAccountMenu(e) {
  if (e) e.stopPropagation();
  if (!isLoggedIn && !accounts.length) { showLogin(false); return; }
  const menu = document.getElementById('accountMenu');
  const wrap = menu.parentElement;
  const open = menu.classList.toggle('open');
  wrap.classList.toggle('open', open);
  if (open) loadAccounts();
}

function closeAccountMenu() {
  const menu = document.getElementById('accountMenu');
  if (!menu) return;
  menu.classList.remove('open');
  menu.parentElement.classList.remove('open');
}

async function switchAccount(id) {
  closeAccountMenu();
  const target = accounts.find(a => a.id === id);
  if (target && target.active) return;
  if (isStreaming) await stopStreaming();
  notice(`Switching to ${(target && target.email) || 'account'}...`);
  const r = await api('/api/accounts/switch', { method: 'POST', body: JSON.stringify({ id }) });
  if (!r || !r.ok) return notice((r && r.error) || 'Could not switch account.', 'err');
  await checkStatus(true);
  await newChat();
  await loadAccounts();
  notice(`Switched to ${r.email || 'account'}.`, 'ok');
}

async function removeAccount(id) {
  const a = accounts.find(x => x.id === id);
  if (!a) return;
  if (!confirm(`Remove ${a.email || 'this account'} from this app?\n\nIts saved session will be forgotten here.`)) return;
  const r = await api('/api/accounts/remove', { method: 'POST', body: JSON.stringify({ id }) });
  if (!r || !r.ok) return notice((r && r.error) || 'Could not remove account.', 'err');
  if (a.active) {
    if (isStreaming) await stopStreaming();
    await checkStatus(true);
    await newChat();
  }
  await loadAccounts();
  notice(r.switched_to ? `Removed. Switched to ${r.switched_to}.` : 'Account removed.', 'ok');
}

let loginPoll = null;

async function showLogin(add) {
  loginAddMode = !!add;
  closeAccountMenu();
  if (isStreaming) await stopStreaming();
  if (loginAddMode) await loadAccounts();
  document.getElementById('loginModal').classList.add('open');
  setLoginStatus('');
  const desktop = !!(window.appState && window.appState.desktop);
  const hasAccounts = accounts.length > 0;
  const blockedByCurrentAccount = loginAddMode && hasAccounts;
  document.getElementById('loginTitle').textContent = loginAddMode && hasAccounts ? 'Add another arena.ai account' : 'Sign in to arena.ai';
  document.getElementById('windowLoginBtn').style.display = desktop && !blockedByCurrentAccount ? '' : 'none';
  document.getElementById('windowLoginNote').style.display = !desktop && !blockedByCurrentAccount ? '' : 'none';
  document.getElementById('windowLoginIntro').style.display = desktop && !blockedByCurrentAccount ? '' : 'none';
  document.getElementById('addAccountNote').style.display = blockedByCurrentAccount ? '' : 'none';
}

function closeLogin() {
  document.getElementById('loginModal').classList.remove('open');
  clearInterval(loginPoll);
  loginPoll = null;
  loginAddMode = false;
}

function setLoginStatus(msg, kind = 'info') {
  document.getElementById('loginStatus').innerHTML = msg ? `<div class="status-msg ${kind}" style="white-space:pre-line">${esc(msg)}</div>` : '';
}

async function loginDone(r, how) {
  setLoginStatus(`${loginAddMode ? 'Added' : 'Signed in as'}${r.email ? ' ' + r.email : ''} (${how}).`, 'ok');
  await loadAccounts();
  setTimeout(() => { closeLogin(); checkStatus(true); loadModels(); newChat(); }, 900);
}

async function windowLogin() {
  const r = await api('/api/login', { method: 'POST', body: JSON.stringify({ method: 'window' }) });
  if (!r.ok) return setLoginStatus(r.error, 'err');
  setLoginStatus('The arena.ai window is open. Sign in there with Google or email. This box updates by itself.');
  clearInterval(loginPoll);
  loginPoll = setInterval(async () => {
    let p;
    try { p = await api('/api/login/poll'); } catch (_) { return; }
    if (p.ok) { clearInterval(loginPoll); loginPoll = null; loginDone(p, 'arena.ai window'); }
    else if (p.done) { clearInterval(loginPoll); loginPoll = null; setLoginStatus(p.error || p.hint || 'Sign-in did not finish.', 'err'); }
    else if (p.hint) setLoginStatus(p.hint);
  }, 2000);
}

async function copySnippet(btn) {
  try {
    await navigator.clipboard.writeText('copy(document.cookie)');
    btn.textContent = 'Copied';
  } catch (_) {
    btn.textContent = 'Copy it by hand';
  }
  setTimeout(() => { btn.textContent = 'Copy'; }, 1800);
}

async function clipboardLogin() {
  setLoginStatus('Reading the clipboard and checking the session with arena.ai...');
  const r = await api('/api/login', { method: 'POST', body: JSON.stringify({ method: 'clipboard' }) });
  if (r.ok) loginDone(r, 'clipboard'); else setLoginStatus(r.error, 'err');
}

async function autoLogin() {
  setLoginStatus('Looking for a signed-in arena.ai session in Chrome, Edge and Brave...');
  const r = await api('/api/login', { method: 'POST', body: JSON.stringify({ method: 'auto' }) });
  if (r.ok) loginDone(r, 'browser'); else setLoginStatus(r.error, 'err');
}

async function manualLogin() {
  const box = document.getElementById('cookieInput');
  const cookie = box.value.trim();
  if (!cookie) return setLoginStatus('Paste the cookie text first.', 'err');
  setLoginStatus('Checking the session with arena.ai...');
  const r = await api('/api/login', { method: 'POST', body: JSON.stringify({ method: 'manual', cookie }) });
  if (r.ok) { box.value = ''; loginDone(r, 'pasted cookies'); } else setLoginStatus(r.error, 'err');
}

async function logout() {
  const active = accounts.find(a => a.active);
  const who = active && active.email ? ` ${active.email}` : '';
  if (!confirm(`Sign out${who}? Its saved session will be removed from this app.`)) return;
  closeAccountMenu();
  if (isStreaming) await stopStreaming();
  const r = await api('/api/logout', { method: 'POST' });
  if (!r || !r.ok) return notice((r && r.error) || 'Could not sign out.', 'err');
  isLoggedIn = false;
  updateAuthUI(false);
  await checkStatus(true);
  await newChat();
  await loadAccounts();
  notice(r.switched_to ? `Signed out. Switched to ${r.switched_to}.` : 'Signed out.', 'ok');
}

/* ── Settings ── */
function showSettings(keepOpen) {
  const openPanel = document.getElementById('settingsPanel');
  if (!keepOpen && openPanel && openPanel.style.display !== 'none') return closeSettings();
  document.getElementById('settingsPanel').style.display = '';
  document.getElementById('welcome').style.display = 'none';
  document.getElementById('messages').style.display = 'none';
  document.getElementById('settingsMode').value = currentMode;
  const modSel = document.getElementById('settingsModality');
  if (modSel) modSel.value = currentModality;
}

function closeSettings() {
  document.getElementById('settingsPanel').style.display = 'none';
  const msgs = document.getElementById('messages');
  if (msgs.classList.contains('active')) {
    msgs.style.display = '';
  } else {
    document.getElementById('welcome').style.display = 'flex';
  }
}

function saveSetting(key, value) {
  api('/api/settings', { method: 'POST', body: JSON.stringify({ [key]: value }) });
}

async function clearAllChats() {
  if (!confirm('Clear all chat history? This cannot be undone.')) return;
  const chats = await api('/api/chats');
  if (Array.isArray(chats)) {
    for (const c of chats) await api('/api/chats/' + c.id + '/delete', { method: 'POST' });
  }
  document.getElementById('chatHistory').innerHTML = '';
  document.getElementById('starredChats').innerHTML = '';
  newChat();
  closeSettings();
}

/* ── Sidebar ── */
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.toggle('collapsed');
  document.querySelector('.app').classList.toggle('sidebar-collapsed', sidebar.classList.contains('collapsed'));
}

function toggleFolder(id) {
  const header = event.currentTarget;
  header.classList.toggle('collapsed');
  const items = header.nextElementSibling;
  items.style.display = items.style.display === 'none' ? '' : 'none';
}

function searchChats() {
  const q = prompt('Search chats:');
  if (!q) return;
  document.querySelectorAll('.history-item').forEach(el => {
    el.style.display = el.textContent.toLowerCase().includes(q.toLowerCase()) ? '' : 'none';
  });
}

/* ── Models ── */
let modelsRequest = 0;
let modelsWanted = null;
let modelsLoadedAt = 0;
function apiModalityForUI() {
  return {auto:'chat',text:'chat',code:'webdev',search:'search',image:'image',video:'video'}[currentModality] || 'chat';
}
async function loadModels(force = false) {
  const apiMod = apiModalityForUI();
  if (!force && apiMod === modelsWanted && Date.now() - modelsLoadedAt < 30000) return;
  const req = ++modelsRequest;  // a newer mode/modality wins even if an older request answers last
  const el = document.getElementById('modelList');
  modelsWanted = apiMod;
  el.innerHTML = '<div style="padding:12px"><div class="skeleton loading-bar"></div><div class="skeleton loading-bar"></div><div class="skeleton loading-bar"></div></div>';
  try {
    const data = await api(`/api/models?modality=${apiMod}${force ? '&refresh=1' : ''}`);
    if (req !== modelsRequest) return;
    if (Array.isArray(data)) {
      models = data;
      if (selectedModel && !data.some(m => m.id === selectedModel.id)) {
        selectedModel = null;
        document.getElementById('modelBtnText').textContent = 'Auto';
      }
      if (selectedModelB && !data.some(m => m.id === selectedModelB.id)) {
        selectedModelB = null;
        const btnB = document.getElementById('modelBtnTextB');
        if (btnB) btnB.textContent = 'Model B';
      }
      renderModelList(models);
      renderModelListB(models);
      if (document.getElementById('modelSearch').value) filterModels();
      if (document.getElementById('modelSearchB').value) filterModelsB();
      modelsLoadedAt = Date.now();
    } else {
      el.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:13px;text-align:center">Failed to load models</div>';
    }
  } catch (e) {
    if (req !== modelsRequest) return;
    el.innerHTML = '<div style="padding:12px;color:var(--interactive-negative);font-size:13px;text-align:center">Connection error</div>';
  }
}

// Keep the picker in step with arena's live catalog while the app stays open.
setInterval(() => { if (!document.hidden) loadModels(); }, 6 * 60 * 1000);
window.addEventListener('focus', () => loadModels());

function renderModelList(list) {
  const el = document.getElementById('modelList');
  el.innerHTML = '';
  if (!list.length) { el.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:13px;text-align:center">No models found</div>'; return; }
  list.forEach(m => {
    const div = document.createElement('div');
    div.className = 'dd-item' + (selectedModel && selectedModel.id === m.id ? ' sel' : '');
    div.innerHTML = `<span class="org-logo">${getOrgLogo(m.org)}</span><div class="model-info"><span class="model-name">${esc(m.name)}</span><span class="model-org-label">${esc(m.org_display || m.org)}</span></div>${m.rank ? `<span class="model-rank">#${m.rank}</span>` : ''}`;
    div.onclick = () => selectModel(m);
    el.appendChild(div);
  });
}

function filterModels() {
  const q = document.getElementById('modelSearch').value.toLowerCase();
  renderModelList(models.filter(m => m.name.toLowerCase().includes(q) || m.org.toLowerCase().includes(q)));
}

function selectModel(m) {
  selectedModel = m;
  document.getElementById('modelBtnText').textContent = m.name;
  closeAllDD();
}

function renderModelListB(list) {
  const el = document.getElementById('modelListB');
  if (!el) return;
  el.innerHTML = '';
  if (!list.length) { el.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:13px;text-align:center">No models found</div>'; return; }
  list.forEach(m => {
    const div = document.createElement('div');
    div.className = 'dd-item' + (selectedModelB && selectedModelB.id === m.id ? ' sel' : '');
    div.innerHTML = `<span class="org-logo">${getOrgLogo(m.org)}</span><div class="model-info"><span class="model-name">${esc(m.name)}</span><span class="model-org-label">${esc(m.org_display || m.org)}</span></div>${m.rank ? `<span class="model-rank">#${m.rank}</span>` : ''}`;
    div.onclick = () => selectModelB(m);
    el.appendChild(div);
  });
}

function filterModelsB() {
  const q = document.getElementById('modelSearchB').value.toLowerCase();
  renderModelListB(models.filter(m => m.name.toLowerCase().includes(q) || m.org.toLowerCase().includes(q)));
}

function selectModelB(m) {
  selectedModelB = m;
  document.getElementById('modelBtnTextB').textContent = m.name;
  closeAllDD();
}

/* ── Mode ── */
function selectMode(mode) {
  currentMode = mode;
  if (mode === 'agent') currentModality = 'auto';
  api('/api/mode', { method: 'POST', body: JSON.stringify({ mode }) });
  updateModeUI();
  updateModalityUI();
  loadModels();
  closeAllDD();
}

const MODE_ICONS = {
  battle: '<polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5"/><line x1="13" y1="19" x2="19" y2="13"/><line x1="16" y1="16" x2="20" y2="20"/><line x1="19" y1="21" x2="21" y2="19"/><polyline points="14.5 6.5 18 3 21 3 21 6 17.5 9.5"/><line x1="5" y1="14" x2="9" y2="18"/><line x1="7" y1="17" x2="4" y2="20"/><line x1="3" y1="19" x2="5" y2="21"/>',
  direct: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  'side-by-side': '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M12 3v18"/>',
  agent: '<path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
};

function updateModeUI() {
  const labels = { battle: 'Battle', direct: 'Direct', 'side-by-side': 'Side by Side', agent: 'Agent' };
  const isPrimary = currentMode === 'battle' || currentMode === 'direct';
  // Segmented toggle owns the two headline modes; everything else shows in the "More" menu.
  document.getElementById('segBattle')?.classList.toggle('active', currentMode === 'battle');
  document.getElementById('segDirect')?.classList.toggle('active', currentMode === 'direct');
  const moreText = document.getElementById('modeBtnText');
  if (moreText) moreText.textContent = isPrimary ? 'More' : (labels[currentMode] || currentMode);
  document.getElementById('modeBtn')?.classList.toggle('active', !isPrimary);
  document.querySelectorAll('#modeMenu .dd-item').forEach(el => {
    el.classList.toggle('sel', el.dataset.mode === currentMode);
  });

  const showModelA = MODE_NEEDS_MODEL.includes(currentMode);
  const showModelB = currentMode === 'side-by-side';
  document.getElementById('modelDropdown').style.display = showModelA ? 'inline-flex' : 'none';
  const ddB = document.getElementById('modelDropdownB');
  if (ddB) ddB.style.display = showModelB ? 'inline-flex' : 'none';
  if (showModelA) document.getElementById('modelBtnText').textContent = selectedModel ? selectedModel.name : (showModelB ? 'Model A' : 'Auto');
  if (showModelB && ddB) document.getElementById('modelBtnTextB').textContent = selectedModelB ? selectedModelB.name : 'Model B';
}

/* ── Modality ── */
function selectModality(mod) {
  if (currentMode === 'agent' && mod !== 'auto') {
    notice('Agent mode uses Auto only.', 'warn');
    updateModalityUI();
    return;
  }
  currentModality = mod;
  api('/api/modality', { method: 'POST', body: JSON.stringify({ modality: mod }) });
  updateModalityUI();
  loadModels();
  closeAllDD();
}

function updateModalityUI() {
  const labels = { auto: 'Auto', text: 'Text', code: 'Code', search: 'Web Search', image: 'Image', video: 'Video' };
  const agentOnly = currentMode === 'agent';
  document.getElementById('modalityBtnText').textContent = agentOnly ? 'Auto' : (labels[currentModality] || currentModality);
  document.querySelectorAll('#modalityMenu .dd-item').forEach(el => {
    const allowed = !agentOnly || el.dataset.modality === 'auto';
    el.classList.toggle('sel', el.dataset.modality === currentModality);
    el.style.display = allowed ? '' : 'none';
  });
  const sel = document.getElementById('settingsModality');
  if (sel) {
    Array.from(sel.options).forEach(o => { o.disabled = agentOnly && o.value !== 'auto'; });
    sel.value = agentOnly ? 'auto' : currentModality;
  }
}

/* ── File Upload ── */
const MAX_UPLOAD_MB = 15;
const MAX_UPLOAD_COUNT = 12;
const EXT_MIME = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp',
  bmp: 'image/bmp', svg: 'image/svg+xml', pdf: 'application/pdf', txt: 'text/plain', md: 'text/markdown',
  csv: 'text/csv', tsv: 'text/tab-separated-values', json: 'application/json', py: 'text/x-python',
  js: 'text/javascript', mjs: 'text/javascript', ts: 'text/typescript', tsx: 'text/typescript',
  html: 'text/html', htm: 'text/html', css: 'text/css', xml: 'application/xml', yaml: 'application/yaml',
  yml: 'application/yaml', mp4: 'video/mp4', mov: 'video/quicktime', webm: 'video/webm',
  mp3: 'audio/mpeg', wav: 'audio/wav', m4a: 'audio/mp4', zip: 'application/zip',
};
const TEXT_FILE_RE = /\.(txt|md|markdown|csv|tsv|json|jsonl|ya?ml|toml|ini|cfg|conf|log|py|js|mjs|cjs|jsx|ts|tsx|html?|css|scss|sass|less|xml|sql|sh|bash|bat|cmd|ps1|c|h|cc|cpp|hpp|cs|java|kt|go|rs|rb|php|swift|lua|r|m|mm|pl|vue|svelte|astro|env|gitignore|dockerfile|makefile)$/i;

function guessMime(name) {
  const ext = (name.split('.').pop() || '').toLowerCase();
  return EXT_MIME[ext] || '';
}

function isTextUpload(name, type) {
  return !type.startsWith('image/') && !type.startsWith('video/') && !type.startsWith('audio/')
    && (type.startsWith('text/') || ['application/json', 'application/xml', 'application/javascript'].includes(type)
      || TEXT_FILE_RE.test(name));
}

function addUploadedFile(name, type, size, data, path, binary) {
  if (uploadedFiles.length >= MAX_UPLOAD_COUNT) {
    notice(`Attach at most ${MAX_UPLOAD_COUNT} files at once.`, 'warn');
    return;
  }
  if (uploadedFiles.some(f => f.name === name && f.size === size && f.path === (path || null))) return;
  uploadedFiles.push({ name, type, size, data, path: path || null, binary: !!binary });
  renderUploadPreviews();
  updateSendBtn();
}

function addFiles(files) {
  files.forEach(file => {
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      notice(`${file.name} is larger than ${MAX_UPLOAD_MB} MB.`, 'warn');
      return;
    }
    const type = file.type || guessMime(file.name) || 'application/octet-stream';
    const binary = !isTextUpload(file.name, type);
    const reader = new FileReader();
    reader.onload = () => addUploadedFile(file.name, type, file.size, reader.result, null, binary);
    reader.onerror = () => notice(`Could not read ${file.name}.`, 'err');
    if (binary) reader.readAsDataURL(file);
    else reader.readAsText(file);
  });
}

async function openFileUpload() {
  if (window.pywebview && window.pywebview.api) {
    try {
      const paths = await window.pywebview.api.open_file_dialog([
        'Images (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)',
        'Documents (*.pdf;*.txt;*.md;*.csv)',
        'Code (*.py;*.js;*.ts;*.tsx;*.html;*.css;*.json)',
      ]);
      if (paths && paths.length) {
        for (const p of paths) {
          const name = p.split(/[\\/]/).pop();
          const type = guessMime(name) || 'application/octet-stream';
          addUploadedFile(name, type, 0, null, p, !isTextUpload(name, type));
        }
      }
      return;
    } catch (_) {}
  }
  document.getElementById('fileInput').click();
}

function handleFileUpload(e) {
  addFiles(Array.from(e.target.files));
  e.target.value = '';
}

function renderUploadPreviews() {
  const container = document.getElementById('uploadPreview');
  container.innerHTML = '';
  uploadedFiles.forEach((f, i) => {
    const thumb = document.createElement('div');
    thumb.className = 'upload-thumb';
    thumb.title = `${f.name}${f.size ? ` (${Math.max(1, Math.round(f.size / 1024))} KB)` : ''}`;
    if (f.type.startsWith('image/') && f.data) {
      thumb.innerHTML = `<img src="${f.data}" alt="${esc(f.name)}"><div class="remove-upload" onclick="removeUpload(${i})">&times;</div>`;
    } else {
      const label = f.type.startsWith('image/') ? 'Image' : 'File';
      thumb.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;background:var(--surface-tertiary);font-size:10px;color:var(--text-muted);padding:4px;text-align:center;word-break:break-all"><b>${label}</b>${esc(f.name)}</div><div class="remove-upload" onclick="removeUpload(${i})">&times;</div>`;
    }
    container.appendChild(thumb);
  });
}

function removeUpload(i) {
  uploadedFiles.splice(i, 1);
  renderUploadPreviews();
  updateSendBtn();
}

/* ── Chat ── */
async function newChat() {
  const r = await api('/api/new', { method: 'POST' });
  currentChatId = r.chat_id || null;
  document.getElementById('messages').innerHTML = '';
  document.getElementById('messages').classList.remove('active');
  document.getElementById('messages').style.display = '';
  document.getElementById('welcome').style.display = 'flex';
  document.getElementById('settingsPanel').style.display = 'none';
  uploadedFiles = [];
  lastSentAttachments = [];
  renderUploadPreviews();
  loadChatHistory();
  document.getElementById('chatInput').focus();
}

function handleKey(e) {
  const menu = document.getElementById('slashMenu');
  const open = menu && menu.classList.contains('open');
  if (open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    e.preventDefault();
    const n = menu.children.length;
    slashIdx = (slashIdx + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
    updateSlash();
    return;
  }
  if (open && !e.shiftKey && (e.key === 'Tab' || e.key === 'Enter')) {
    const item = menu.children[slashIdx];
    if (item) {
      e.preventDefault();
      completeSlash(item.querySelector('.slash-cmd').textContent, e.key === 'Enter');
      return;
    }
  }
  if (e.key === 'Tab' && e.shiftKey) { e.preventDefault(); cyclePerm(); return; }
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

function updateSendBtn() {
  const btn = document.getElementById('sendBtn');
  const val = document.getElementById('chatInput').value.trim();
  btn.disabled = isUploading || (!isStreaming && !val && !uploadedFiles.length);
  btn.classList.toggle('has-text', !isUploading && (!!val || uploadedFiles.length > 0));
  btn.classList.toggle('stop', isStreaming);
  btn.title = isStreaming ? 'Stop' : (isUploading ? 'Uploading...' : 'Send message');
  if (!btn.dataset.sendIcon) btn.dataset.sendIcon = btn.innerHTML;
  btn.innerHTML = isStreaming ? '<svg width="14" height="14" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>' : btn.dataset.sendIcon;
}

function useSuggestion(text) {
  document.getElementById('chatInput').value = text;
  autoResize(document.getElementById('chatInput'));
  updateSendBtn();
  sendMessage();
}

let lastSent = '';
async function sendMessage(retryText) {
  if (isStreaming) { stopStreaming(); return; }
  if (isUploading) return;
  const input = document.getElementById('chatInput');
  const isRetry = typeof retryText === 'string';
  const msg = (isRetry ? retryText : input.value).trim();
  if (!msg && !uploadedFiles.length && !(isRetry && lastSentAttachments.length)) return;
  if (!isRetry && msg.startsWith('/') && runSlash(msg)) {
    input.value = '';
    autoResize(input);
    hideSlash();
    updateSendBtn();
    return;
  }
  if (MODE_NEEDS_MODEL.includes(currentMode) && !selectedModel) {
    notice(`${MODE_LABELS[currentMode]} mode needs a model: pick one first. Battle picks two anonymous models for you.`, 'warn');
    return;
  }
  if (currentMode === 'side-by-side' && !selectedModelB) {
    notice('Side by Side needs a second model: pick one first.', 'warn');
    return;
  }
  if (!isRetry) { input.value = ''; input.style.height = 'auto'; }
  hideSlash();

  document.getElementById('welcome').style.display = 'none';
  document.getElementById('settingsPanel').style.display = 'none';
  const msgsEl = document.getElementById('messages');
  msgsEl.style.display = '';
  msgsEl.classList.add('active');

  const sentFiles = isRetry ? [] : [...uploadedFiles];
  let content = msg;
  let attachments = isRetry ? [...lastSentAttachments] : [];

  if (sentFiles.length) {
    isUploading = true;
    updateSendBtn();
    try {
      const resp = await fetch('/api/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: sentFiles.map(f => ({ name: f.name, type: f.type, data: f.data, path: f.path, size: f.size, binary: !!f.binary })),
        }),
      });
      let up = null;
      try { up = await resp.json(); } catch (_) {}
      if (!resp.ok) throw new Error((up && up.error) || `Upload failed (HTTP ${resp.status}).`);
      if (!up || up.error) throw new Error((up && up.error) || 'Upload failed.');
      const added = [];
      for (const f of up.files || []) {
        if (typeof f.text === 'string') content += `\n\nFile ${f.name}:\n\`\`\`\n${f.text}\n\`\`\``;
        if (f.attachment) added.push(f.attachment);
      }
      attachments = added;
    } catch (err) {
      isUploading = false;
      updateSendBtn();
      notice(err.message || 'Upload failed.', 'err');
      uploadedFiles = sentFiles;
      renderUploadPreviews();
      if (!isRetry) { input.value = msg; autoResize(input); }
      return;
    }
    isUploading = false;
    updateSendBtn();
  }

  appendMsg('user', msg + (sentFiles.length ? `\n\n[Attached: ${sentFiles.map(f => f.name).join(', ')}]` : ''));
  if (!isRetry) addToHistory(msg || sentFiles[0]?.name || 'File upload');
  uploadedFiles = [];
  renderUploadPreviews();
  lastSent = content;
  lastSentAttachments = attachments;

  isStreaming = true;
  updateSendBtn();
  const view = new ReplyView(appendMsg('assistant', ''));
  try {
    const body = { message: content, chat_id: currentChatId };
    if (attachments.length) body.attachments = attachments;
    if (selectedModel && currentMode !== 'battle') body.model_id = selectedModel.id;
    if (selectedModelB && currentMode === 'side-by-side') body.model_id_b = selectedModelB.id;
    streamAbort = new AbortController();
    const resp = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: streamAbort.signal });
    if (!resp.ok) {
      let e = {};
      try { e = await resp.json(); } catch (_) {}
      view.handle({ type: 'error', message: e.error || `Request failed (HTTP ${resp.status})`, code: e.code || (resp.status === 401 ? 'auth' : 'http'), retry: resp.status >= 500 });
    } else {
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop();
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith('data: ')) continue;
          let ev;
          try { ev = JSON.parse(line.slice(6)); } catch (_) { continue; }
          try { view.handle(ev); } catch (err) { console.error(err); }
        }
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') view.handle({ type: 'notice', text: 'Stopped.' });
    else view.handle({ type: 'error', code: 'network', retry: true, message: 'Lost the connection to the app: ' + err.message });
  }
  streamAbort = null;
  view.finish();
  isStreaming = false;
  updateSendBtn();
  input.focus();
  loadChatHistory();
}

function appendMsg(role, text, streaming = false) {
  const el = document.createElement('div');
  el.className = 'message from-' + role;
  el.innerHTML = `
    <div class="msg-header">
      <span class="msg-role ${role}">${role === 'user' ? 'You' : 'Arena AI'}</span>
    </div>
    <div class="msg-content">${text ? renderMd(text) : ''}</div>
    ${streaming ? '<div class="typing-dots"><span></span><span></span><span></span></div>' : ''}
  `;
  document.getElementById('messages').appendChild(el);
  scrollBottom();
  return el;
}

function scrollBottom() {
  const el = document.getElementById('messages');
  el.scrollTop = el.scrollHeight;
}

/* ── Chat history sidebar ── */
async function loadChatHistory() {
  try {
    const chats = await api('/api/chats');
    if (Array.isArray(chats)) renderChatHistory(chats);
  } catch (_) {}
}

function renderChatHistory(chats) {
  const hist = document.getElementById('chatHistory');
  const starred = document.getElementById('starredChats');
  hist.innerHTML = '';
  if (starred) starred.innerHTML = '';
  if (!chats.length) return;

  // Pinned chats live in the Starred folder; the rest are grouped by recency.
  const pinned = chats.filter(c => c.pinned);
  const rest = chats.filter(c => !c.pinned);
  if (starred) pinned.forEach(c => starred.appendChild(_chatHistoryItem(c, true)));

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const DAY = 86400000;
  const groups = [
    ['Today', c => _chatDate(c) >= startOfToday],
    ['Yesterday', c => _chatDate(c) >= startOfToday - DAY && _chatDate(c) < startOfToday],
    ['Previous 7 Days', c => _chatDate(c) >= startOfToday - 7 * DAY && _chatDate(c) < startOfToday - DAY],
    ['Older', c => _chatDate(c) < startOfToday - 7 * DAY],
  ];
  const seen = new Set();
  groups.forEach(([label, test]) => {
    const items = rest.filter(c => !seen.has(c.id) && test(c));
    if (!items.length) return;
    items.forEach(c => seen.add(c.id));
    const head = document.createElement('div');
    head.className = 'history-label';
    head.textContent = label;
    hist.appendChild(head);
    items.forEach(c => hist.appendChild(_chatHistoryItem(c, false)));
  });
}

function _chatDate(c) {
  const t = new Date(c.updated_at || 0).getTime();
  return Number.isFinite(t) ? t : 0;
}

function _chatHistoryItem(c, isStarred) {
  const item = document.createElement('div');
  item.className = 'history-item' + (c.id === currentChatId ? ' active' : '') + (c.pinned ? ' pinned' : '');
  const title = c.title || 'Untitled';
  const preview = title.length > 30 ? title.substring(0, 30) + '...' : title;
  const pinIcon = '<svg class="h-pin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5"/><path d="M9 10.8V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v4.8l2 2.2v2H7v-2z"/></svg>';
  item.innerHTML = `${pinIcon}<span class="h-text">${esc(preview)}</span>
    <button class="h-more" title="More options" onclick="event.stopPropagation(); openChatMenu(event, '${c.id}')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>
    </button>`;
  item.dataset.chatId = c.id;
  item.dataset.pinned = c.pinned ? '1' : '';
  item.dataset.title = title;
  item.onclick = () => loadChat(c.id);
  return item;
}

/* ── Chat more-options menu (rename / pin / delete) ── */
function openChatMenu(e, chatId) {
  e.stopPropagation();
  const menu = document.getElementById('chatMenu');
  const row = e.currentTarget.closest('.history-item');
  if (!menu || !row) return;
  const pinned = !!row.dataset.pinned;
  menu.dataset.chatId = chatId;
  menu.querySelector('[data-act="pin"] span').textContent = pinned ? 'Unpin' : 'Pin';
  const r = e.currentTarget.getBoundingClientRect();
  menu.classList.add('open');
  const mw = menu.offsetWidth, mh = menu.offsetHeight;
  menu.style.left = Math.max(8, Math.min(r.right - mw, window.innerWidth - mw - 8)) + 'px';
  menu.style.top = (r.bottom + mh > window.innerHeight - 8 ? r.top - mh - 4 : r.bottom + 4) + 'px';
}

function closeChatMenu() { document.getElementById('chatMenu')?.classList.remove('open'); }

async function chatMenuAction(act) {
  const menu = document.getElementById('chatMenu');
  const chatId = menu?.dataset.chatId;
  closeChatMenu();
  if (!chatId) return;
  if (act === 'rename') return renameChat(chatId);
  if (act === 'delete') return deleteChat(chatId);
  if (act === 'pin') return togglePinChat(chatId);
}

async function renameChat(chatId) {
  const row = document.querySelector(`.history-item[data-chat-id="${chatId}"]`);
  const current = row?.dataset.title || 'Untitled';
  const title = prompt('Rename chat:', current);
  if (title === null) return;
  const trimmed = title.trim();
  if (!trimmed) return notice('A chat needs a name.', 'warn');
  const r = await api('/api/chats/' + chatId + '/update', { method: 'POST', body: JSON.stringify({ title: trimmed }) });
  if (!r.ok) return notice(r.error || 'Could not rename the chat.', 'err');
  loadChatHistory();
}

async function togglePinChat(chatId) {
  const row = document.querySelector(`.history-item[data-chat-id="${chatId}"]`);
  const pinned = !!row?.dataset.pinned;
  const r = await api('/api/chats/' + chatId + '/update', { method: 'POST', body: JSON.stringify({ pinned: !pinned }) });
  if (!r.ok) return notice(r.error || 'Could not update the chat.', 'err');
  loadChatHistory();
}

async function loadChat(chatId) {
  if (isStreaming) {
    await stopStreaming();
    notice('Stopped the running reply to open this chat.', 'warn');
  }
  try {
    const data = await api('/api/chats/' + chatId);
    if (data.error) return;
    currentChatId = chatId;
    document.getElementById('welcome').style.display = 'none';
    document.getElementById('settingsPanel').style.display = 'none';
    const msgsEl = document.getElementById('messages');
    msgsEl.innerHTML = '';
    msgsEl.style.display = '';
    msgsEl.classList.add('active');
    (data.messages || []).forEach(m => {
      if (m.role === 'user') {
        appendMsg('user', m.text);
      } else {
        if (m.text_b || m.tools?.some(t => t.lane === 'b') || m.sandbox?.some(r => r.model === 'b')) {
          const lt = l => (m.tools || []).filter(t => (t.lane || 'a') === l).map(toolCardHtml).join('')
            + (m.sandbox || []).filter(r => (r.model || 'a') === l).map(sandboxRow).join('');
          const el = appendMsg('assistant', '');
          el.innerHTML = `
            <div class="msg-header"><span class="msg-role assistant">Arena AI</span></div>
            <div class="sbs-container">
              <div class="sbs-column"><div class="sbs-header"><span class="sbs-badge a">A</span> ${esc(m.names?.a || 'Model A')}</div><div class="msg-content sbs-content">${lt('a')}${renderMd(m.text)}</div></div>
              <div class="sbs-column"><div class="sbs-header"><span class="sbs-badge b">B</span> ${esc(m.names?.b || 'Model B')}</div><div class="msg-content sbs-content">${lt('b')}${renderMd(m.text_b)}</div></div>
            </div>`;
          el.querySelectorAll('.sbs-content').forEach(c => { hlAll(c); addCopyBtns(c); });
        } else {
          const el = appendMsg('assistant', m.text || '');
          const content = el.querySelector('.msg-content');
          const role = el.querySelector('.msg-role');
          if (role && m.names?.a) role.textContent = m.names.a;
          if (m.tools?.length) content.insertAdjacentHTML('afterbegin', m.tools.map(toolCardHtml).join(''));
          if (m.sandbox?.length) content.insertAdjacentHTML('afterbegin', m.sandbox.map(sandboxRow).join(''));
          if (!m.text && m.error) content.insertAdjacentHTML('beforeend', `<div class="notice-line err">Not sent: ${esc(m.error)}</div>`);
          else if (!m.text && !m.tools?.length) content.insertAdjacentHTML('beforeend', '<div class="notice-line">No reply was received.</div>');
          hlAll(content); addCopyBtns(content);
        }
      }
    });
    scrollBottom();
    loadChatHistory();
  } catch (_) {}
}

async function deleteChat(chatId) {
  await api('/api/chats/' + chatId + '/delete', { method: 'POST' });
  if (chatId === currentChatId) newChat();
  loadChatHistory();
}

function addToHistory(text) {
  chatCounter++;
  loadChatHistory();
}

/* ── Webdev File Tree ── */
function _buildFileTree(files) {
  if (!files || !files.length) return '';
  return '<div class="wf-tree">' + files.map(f => {
    const name = f.path.split('/').pop();
    const ext = name.split('.').pop().toLowerCase();
    const iconColors = {html:'#E34C26',js:'#F7DF1E',jsx:'#61DAFB',tsx:'#3178C6',css:'#563D7C',json:'#292929',py:'#3572A5',sql:'#336791',md:'#083FA1',svg:'#FFB13B',toml:'#9C4121',yaml:'#CB171E',yml:'#CB171E',sh:'#89E051',txt:'var(--text-muted)'};
    const color = iconColors[ext] || 'var(--text-muted)';
    return `<div class="wf-file" title="${esc(f.path)}"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg><span>${esc(name)}</span></div>`;
  }).join('') + '</div>';
}

/* ── IDE File Manager ── */
let ideOpen = false;
let ideFiles = [];
let ideCwd = '.';

function toggleIDE() {
  const panel = document.getElementById('idePanel');
  ideOpen = !ideOpen;
  panel.classList.toggle('collapsed', !ideOpen);
  if (ideOpen) loadFileTree();
}

async function loadFileTree() {
  try {
    const data = await api('/api/files?path=' + encodeURIComponent(ideCwd));
    if (data.files) {
      ideFiles = data.files;
      renderFileTree(data.files, data.cwd);
    }
  } catch (e) {
    document.getElementById('fileTree').innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:12px">Could not load files</div>';
  }
}

function renderFileTree(files, cwd) {
  const tree = document.getElementById('fileTree');
  tree.innerHTML = '';
  if (cwd) {
    document.getElementById('ideCwd').textContent = cwd;
    const upItem = document.createElement('div');
    upItem.className = 'tree-item dir';
    upItem.innerHTML = '<svg class="tree-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg><span class="tree-name">..</span>';
    upItem.onclick = () => { ideCwd = cwd.split(/[\\/]/).slice(0, -1).join('/') || '.'; loadFileTree(); };
    tree.appendChild(upItem);
  }
  const dirs = files.filter(f => f.is_dir).sort((a, b) => a.name.localeCompare(b.name));
  const filesList = files.filter(f => !f.is_dir).sort((a, b) => a.name.localeCompare(b.name));
  dirs.forEach(f => {
    const item = document.createElement('div');
    item.className = 'tree-item dir';
    item.innerHTML = `<svg class="tree-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg><span class="tree-name">${esc(f.name)}</span>`;
    item.onclick = () => { ideCwd = f.path; loadFileTree(); };
    tree.appendChild(item);
  });
  filesList.forEach(f => {
    const item = document.createElement('div');
    item.className = 'tree-item';
    const ext = f.name.split('.').pop().toLowerCase();
    const iconColor = { py: '#3572A5', js: '#F7DF1E', html: '#E34C26', css: '#563D7C', json: '#292929', md: '#083FA1', txt: '#635E57' }[ext] || 'var(--text-muted)';
    item.innerHTML = `<svg class="tree-icon" viewBox="0 0 24 24" fill="none" stroke="${iconColor}" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg><span class="tree-name">${esc(f.name)}</span>`;
    item.onclick = () => openFile(f.path);
    tree.appendChild(item);
  });
  document.getElementById('ideFileCount').textContent = `${files.length} items`;
}

async function openFile(path) {
  try {
    const data = await api('/api/files/read?path=' + encodeURIComponent(path));
    if (data.content !== undefined) {
      document.getElementById('welcome').style.display = 'none';
      document.getElementById('settingsPanel').style.display = 'none';
      const msgsEl = document.getElementById('messages');
      msgsEl.style.display = '';
      msgsEl.classList.add('active');
      msgsEl.innerHTML = '';
      const el = document.createElement('div');
      el.className = 'message';
      const fileName = path.split(/[\\/]/).pop();
      el.innerHTML = `
        <div class="msg-header">
          <span class="msg-role user" style="font-family:'JetBrains Mono',monospace;font-size:12px">${esc(path)}</span>
          <div class="spacer" style="flex:1"></div>
          <button class="icon-btn" onclick="saveFileFromEditor('${esc(path).replace(/'/g, "\\'")}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg></button>
        </div>
        <div class="code-editor">
          <textarea id="editorContent" spellcheck="false">${esc(data.content)}</textarea>
        </div>
      `;
      msgsEl.appendChild(el);
    }
  } catch (e) {}
}

async function saveFileFromEditor(path) {
  const content = document.getElementById('editorContent')?.value;
  if (content === undefined) return;
  try {
    const r = await api('/api/files/write', { method: 'POST', body: JSON.stringify({ path, content }) });
    if (r.ok) {
      const el = document.createElement('div');
      el.className = 'status-msg ok';
      el.style.cssText = 'position:fixed;top:12px;right:12px;z-index:999;animation:fadeIn .15s';
      el.textContent = 'Saved';
      document.body.appendChild(el);
      setTimeout(() => el.remove(), 2000);
    }
  } catch (e) {}
}

async function ideNewFile() {
  const name = prompt('File name:');
  if (!name) return;
  const path = ideCwd === '.' ? name : ideCwd + '/' + name;
  await api('/api/files/write', { method: 'POST', body: JSON.stringify({ path, content: '' }) });
  loadFileTree();
}

async function ideNewFolder() {
  const name = prompt('Folder name:');
  if (!name) return;
  const path = ideCwd === '.' ? name : ideCwd + '/' + name;
  await api('/api/files/mkdir', { method: 'POST', body: JSON.stringify({ path }) });
  loadFileTree();
}

function ideRefresh() { loadFileTree(); }

/* ── Terminal ── */
let terminalOpen = false;

function toggleTerminal() {
  const panel = document.getElementById('terminalPanel');
  terminalOpen = !terminalOpen;
  panel.classList.toggle('collapsed', !terminalOpen);
  if (terminalOpen) document.getElementById('terminalInput').focus();
}

function clearTerminal() {
  document.getElementById('terminalOutput').innerHTML = '';
}

async function runCommand() {
  const input = document.getElementById('terminalInput');
  const cmd = input.value.trim();
  if (!cmd) return;
  input.value = '';
  const output = document.getElementById('terminalOutput');
  output.innerHTML += `<div style="color:var(--brand-green)">$ ${esc(cmd)}</div>`;
  try {
    const r = await api('/api/terminal', { method: 'POST', body: JSON.stringify({ command: cmd }) });
    if (r.output) output.innerHTML += `<div>${esc(r.output)}</div>`;
    if (r.error) output.innerHTML += `<div style="color:var(--interactive-negative)">${esc(r.error)}</div>`;
  } catch (e) {
    output.innerHTML += `<div style="color:var(--interactive-negative)">Error: ${esc(e.message)}</div>`;
  }
  output.scrollTop = output.scrollHeight;
}

/* ── Voting ── */
function castVote(btn, choice) {
  const row = btn.closest('.vote-row');
  row.querySelectorAll('.vote-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
  row.querySelector('.vote-label').textContent = choice === 'a' ? 'You picked Model A' : choice === 'b' ? 'You picked Model B' : choice === 'tie' ? 'You said it\'s a tie' : 'You said both were bad';
  row.classList.add('voted');
}

/* ── Markdown ── */
if (window.marked) marked.use({ renderer: { html(t) { return esc(typeof t === 'string' ? t : (t.raw || t.text || '')); } } });

function renderMd(text) {
  // Model output is untrusted: raw HTML is shown as text and only safe link schemes survive.
  if (!text) return '';
  let html;
  try { html = marked.parse(text, { breaks: true, gfm: true }); } catch (_) { return esc(text); }
  const tpl = document.createElement('template');
  tpl.innerHTML = html;
  tpl.content.querySelectorAll('[href],[src]').forEach(n => {
    for (const a of ['href', 'src']) {
      const v = n.getAttribute(a);
      if (v !== null && !/^(https?:|mailto:|#|data:image\/)/i.test(v.trim())) n.removeAttribute(a);
    }
  });
  tpl.content.querySelectorAll('a[href]').forEach(a => { a.target = '_blank'; a.rel = 'noopener noreferrer'; });
  return tpl.innerHTML;
}

function hlAll(container) {
  container.querySelectorAll('pre code').forEach(block => {
    try { hljs.highlightElement(block); } catch (_) {}
  });
}

function addCopyBtns(container) {
  container.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector('.copy-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.title = 'Copy';
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
    btn.onclick = () => {
      const code = pre.querySelector('code');
      navigator.clipboard.writeText(code ? code.textContent : pre.textContent);
      btn.classList.add('copied');
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
      }, 2000);
    };
    pre.appendChild(btn);
  });
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

/* ── Dropdowns ── */
function toggleDD(id) {
  const menu = document.getElementById(id);
  const wasOpen = menu.classList.contains('open');
  closeAllDD();
  if (!wasOpen) {
    menu.classList.add('open');
    menu.closest('.dropdown').querySelector('.sel-btn')?.classList.add('open');
    const searchInput = menu.querySelector('.dd-search input');
    if (searchInput) setTimeout(() => searchInput.focus(), 50);
    if (id === 'modelMenu' || id === 'modelMenuB') loadModels();
  }
}

function closeAllDD() {
  document.querySelectorAll('.dropdown-menu').forEach(m => m.classList.remove('open'));
  document.querySelectorAll('.sel-btn').forEach(b => b.classList.remove('open'));
}

document.addEventListener('click', e => {
  if (!e.target.closest('.dropdown')) closeAllDD();
  if (!e.target.closest('.sidebar-user-wrap')) closeAccountMenu();
});

document.getElementById('loginModal').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeLogin();
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeAllDD();
    closeAccountMenu();
    closeLogin();
    if (document.getElementById('settingsPanel').style.display !== 'none') closeSettings();
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault();
    const editor = document.getElementById('editorContent');
    if (editor) {
      const pathEl = document.querySelector('.msg-role.user');
      if (pathEl) saveFileFromEditor(pathEl.textContent);
    }
  }
});

/* Drag and drop files */
document.addEventListener('dragover', e => { e.preventDefault(); });
document.addEventListener('drop', e => {
  e.preventDefault();
  const files = Array.from(e.dataTransfer.files);
  if (files.length) addFiles(files);
});

/* ── Permission modes (Claude Code style) ── */
const PERM_LABELS = { default: 'Ask before edits', acceptEdits: 'Accept edits', auto: 'Auto', plan: 'Plan mode', bypassPermissions: 'Bypass permissions' };
const PERM_ORDER = ['default', 'acceptEdits', 'auto', 'plan', 'bypassPermissions'];
const PERM_HELP = {
  default: 'Asks before every file change and command. Reading inside the project folder is free.',
  acceptEdits: 'Creates and edits files without asking. Deletes and commands still ask.',
  auto: 'Works freely inside the project folder. Risky commands and anything outside the folder ask.',
  plan: 'Read only. The model looks around and proposes a plan; nothing changes.',
  bypassPermissions: 'Never asks. Catastrophic commands (format, rm -rf /, ...) stay blocked.',
};
let permMode = 'default';

function updatePermUI() {
  const label = document.getElementById('permLabel');
  if (label) {
    label.textContent = PERM_LABELS[permMode];
    label.hidden = (permMode === 'default');
  }
  document.getElementById('permBtn')?.setAttribute('data-perm', permMode);
  document.querySelectorAll('#permMenu .dd-item').forEach(i => i.classList.toggle('sel', i.dataset.perm === permMode));
  const sel = document.getElementById('settingsPerm');
  if (sel) sel.value = permMode;
}

function toggleAdv() {
  const m = document.getElementById('permMenu');
  if (!m) return;
  const wasOpen = m.classList.contains('open');
  closeAllDD();
  if (!wasOpen) m.classList.add('open');
}

function closeAdv() { document.getElementById('permMenu')?.classList.remove('open'); }

document.addEventListener('click', e => {
  if (!e.target.closest('.dropdown')) closeAllDD();
  if (!e.target.closest('.adv-wrap')) closeAdv();
  if (!e.target.closest('.h-menu')) closeChatMenu();
  if (!e.target.closest('.sidebar-user-wrap')) closeAccountMenu();
});

async function setPerm(mode) {
  closeAllDD();
  if (mode === 'bypassPermissions' && permMode !== mode &&
      !confirm('Bypass permissions lets the model create, edit and delete files and run commands without asking. Only catastrophic commands stay blocked. Turn it on?')) {
    updatePermUI();
    return;
  }
  const r = await api('/api/permission-mode', { method: 'POST', body: JSON.stringify({ mode }) });
  if (!r.ok) return notice(r.error || 'Could not change the permission mode', 'err');
  permMode = r.mode;
  updatePermUI();
  notice('Permission mode: ' + PERM_LABELS[permMode]);
}

function cyclePerm() {
  // Shift+Tab, like Claude Code; bypass is only reachable on purpose
  const order = ['default', 'acceptEdits', 'auto', 'plan'];
  setPerm(order[(order.indexOf(permMode) + 1) % order.length]);
}

async function answerPermission(pid, decision, card) {
  card.querySelectorAll('button').forEach(b => { b.disabled = true; });
  try {
    const r = await api('/api/permissions/' + encodeURIComponent(pid), { method: 'POST', body: JSON.stringify({ decision }) });
    if (!r.ok) notice(r.error, 'warn');
  } catch (e) {
    notice('Could not send the answer: ' + e.message, 'err');
  }
}

/* ── arena.ai window (engine) ── */
async function showEngine() {
  const r = await api('/api/engine/show', { method: 'POST' });
  if (!r.ok) notice(r.error, 'warn');
}

async function stopStreaming() {
  try { await api('/api/stop', { method: 'POST' }); } catch (_) {}
  if (streamAbort) streamAbort.abort();  // frees the UI even when arena.ai is slow to stop
}

/* ── Toasts ── */
function notice(text, level = 'info') {
  const box = document.getElementById('toasts');
  if (!box || !text) return;
  const t = document.createElement('div');
  t.className = 'toast ' + level;
  t.textContent = text;
  box.appendChild(t);
  setTimeout(() => t.remove(), level === 'err' ? 9000 : 4500);
}

/* ── Slash commands ── */
const SLASH = [
  ['/new', 'Start a new chat'], ['/clear', 'Clear the screen'], ['/help', 'Commands and shortcuts'],
  ['/settings', 'Open settings'], ['/login', 'Sign in to arena.ai'], ['/logout', 'Sign out'],
  ['/mode', 'battle | direct | side-by-side | agent'], ['/modality', 'auto | text | code | search | image | video'],
  ['/model', 'Pick a model by name'], ['/perm', 'default | acceptEdits | auto | plan | bypassPermissions'],
  ['/plan', 'Turn on plan mode (read only)'], ['/folder', 'Set the agent project folder'],
  ['/doctor', 'Check the connection to arena.ai'], ['/arena', 'Show the arena.ai window'], ['/stop', 'Stop the reply'],
];
const SLASH_ARGS = ['/mode', '/modality', '/model', '/perm', '/folder'];
let slashIdx = 0;

function updateSlash() {
  const v = document.getElementById('chatInput').value;
  const menu = document.getElementById('slashMenu');
  if (!menu) return;
  const m = v.startsWith('/') && !/\s/.test(v) ? SLASH.filter(([c]) => c.startsWith(v.toLowerCase())) : [];
  if (!m.length) { menu.classList.remove('open'); return; }
  slashIdx = Math.min(slashIdx, m.length - 1);
  menu.innerHTML = m.map(([c, d], i) => `<div class="slash-item${i === slashIdx ? ' sel' : ''}" onmousedown="event.preventDefault();completeSlash('${c}', true)"><span class="slash-cmd">${c}</span><span class="slash-desc">${esc(d)}</span></div>`).join('');
  menu.classList.add('open');
}

function hideSlash() { document.getElementById('slashMenu')?.classList.remove('open'); }

function completeSlash(cmd, run) {
  const input = document.getElementById('chatInput');
  hideSlash();
  if (run && !SLASH_ARGS.includes(cmd)) {
    input.value = '';
    runSlash(cmd);
  } else {
    input.value = cmd + ' ';
  }
  autoResize(input);
  updateSendBtn();
  input.focus();
}

function runSlash(text) {
  const [cmd, ...rest] = text.trim().split(/\s+/);
  const arg = rest.join(' ');
  const low = arg.toLowerCase();
  switch (cmd.toLowerCase()) {
    case '/new': newChat(); return true;
    case '/clear': document.getElementById('messages').innerHTML = ''; return true;
    case '/help': case '/?': showHelp(); return true;
    case '/settings': showSettings(); return true;
    case '/login': showLogin(); return true;
    case '/logout': logout(); return true;
    case '/doctor': runDoctor(true); return true;
    case '/arena': showEngine(); return true;
    case '/stop': stopStreaming(); return true;
    case '/plan': setPerm('plan'); return true;
    case '/perm':
      if (PERM_ORDER.includes(arg)) setPerm(arg); else notice('Permission modes: ' + PERM_ORDER.join(', '), 'warn');
      return true;
    case '/mode':
      if (MODE_LABELS[low]) selectMode(low); else notice('Modes: battle, direct, side-by-side, agent', 'warn');
      return true;
    case '/modality':
      if (['auto', 'text', 'code', 'search', 'image', 'video'].includes(low)) selectModality(low);
      else notice('Modalities: auto, text, code, search, image, video', 'warn');
      return true;
    case '/folder':
      if (arg) setWorkspace(arg); else chooseWorkspace();
      return true;
    case '/model': {
      const m = low && models.find(x => (x.name || '').toLowerCase().includes(low) || x.id === arg);
      if (m) { selectModel(m); notice('Model: ' + m.name); } else notice(low ? `No model matches "${arg}"` : 'Usage: /model <name>', 'warn');
      return true;
    }
  }
  if (/^\/[a-z?]+$/i.test(cmd)) { notice(`Unknown command ${cmd}. Type /help for the list.`, 'warn'); return true; }
  return false;
}

/* ── Help ── */
function showHelp() {
  const keys = [['Enter', 'Send'], ['Shift+Enter', 'New line'], ['Shift+Tab', 'Cycle permission mode'], ['Tab', 'Complete a / command'],
    ['F1', 'Help'], ['Ctrl+,', 'Settings'], ['Ctrl+N', 'New chat'], ['Esc', 'Close menus and dialogs']];
  document.getElementById('helpBody').innerHTML = `
    <h3>Getting started</h3><ol class="settings-note help-steps">
      <li>Press <b>Sign in</b> and log in on the arena.ai page that opens inside the app. The app picks up your arena.ai session by itself.</li>
      <li>Pick a mode and a model, then type your message.</li>
      <li>For <b>Agent</b>, pick a project folder (Settings, Workspace) and a permission mode. The agent reads and writes files only in that folder, and uses the <b>Auto</b> modality only.</li></ol>
    <h3>Commands</h3><div class="help-grid">${SLASH.map(([c, d]) => `<code>${c}</code><span>${esc(d)}</span>`).join('')}</div>
    <h3>Shortcuts</h3><div class="help-grid">${keys.map(([k, d]) => `<kbd>${k}</kbd><span>${d}</span>`).join('')}</div>
    <h3>Chat modes</h3><div class="help-grid">
      <b>Battle</b><span>Two anonymous models answer; vote for the better one.</span>
      <b>Side by Side</b><span>Two models you pick answer the same message.</span>
      <b>Direct</b><span>One model you pick.</span>
      <b>Agent</b><span>One model you pick works in your project folder with file and command tools, under the permission mode.</span></div>
    <h3>Permission modes</h3><div class="help-grid">${PERM_ORDER.map(m => `<b>${PERM_LABELS[m]}</b><span>${PERM_HELP[m]}</span>`).join('')}</div>
    <h3>Code answers</h3><p class="settings-note">Code mode answers are written to a local project folder (one per model), so you keep real files. Use Open folder, Download zip or Local preview on the answer.</p>
    <h3>Human checks</h3><p class="settings-note">When arena.ai asks for a reCAPTCHA or Cloudflare check, the app opens arena.ai in a pane on the right of this window so you can finish it there. The app never solves checks for you.</p>
    <p class="settings-note">Unofficial client. Your use of arena.ai falls under arena.ai's Terms of Use, Privacy Policy and Cookie Policy, linked at the bottom of arena.ai.</p>
    <div class="card-actions"><button class="btn btn-secondary" onclick="closeHelp();runDoctor(true)">Run diagnostics</button><button class="btn btn-secondary" onclick="closeHelp();showLogin()">Sign in</button><a class="btn btn-secondary" href="https://arena.ai" target="_blank" rel="noopener">Open arena.ai</a></div>`;
  document.getElementById('helpModal').classList.add('open');
}

function closeHelp() { document.getElementById('helpModal')?.classList.remove('open'); }

/* ── Diagnostics and workspace ── */
async function runDoctor(open) {
  if (open) showSettings(true);
  const out = document.getElementById('doctorOut');
  if (!out) return;
  out.innerHTML = '<div class="thinking"><div class="spinner"></div> Checking...</div>';
  out.scrollIntoView({ block: 'nearest' });
  try {
    const r = await api('/api/doctor');
    out.innerHTML = r.checks.map(c => {
      const cls = c.ok === true ? 'ok' : c.ok === false ? 'bad' : 'warn';
      return `<div class="diag-row ${cls}"><span class="st">${c.ok === true ? '&#10003;' : c.ok === false ? '&#10007;' : '!'}</span><b>${esc(c.name)}</b><span class="dd">${esc(c.detail)}</span></div>`;
    }).join('');
  } catch (e) {
    out.innerHTML = `<div class="diag-row bad"><span class="st">&#10007;</span><span class="dd">Diagnostics failed: ${esc(e.message)}</span></div>`;
  }
}

async function setWorkspace(path) {
  const r = await api('/api/workspace/set', { method: 'POST', body: JSON.stringify({ path }) });
  if (!r.ok) return notice(r.error, 'err');
  const el = document.getElementById('settingsWorkspace');
  if (el) el.textContent = r.workspace;
  updateWsChip(r.workspace);
  notice('Agent project folder: ' + r.workspace, 'ok');
}

async function chooseWorkspace() {
  let path = null;
  if (window.pywebview?.api?.choose_folder) path = await window.pywebview.api.choose_folder();
  else path = prompt('Full path of the project folder for Agent mode:');
  if (path) setWorkspace(path);
}

function hideSplash() {
  const b = document.getElementById('bootSplash');
  if (!b) return;
  b.classList.add('gone');
  setTimeout(() => b.remove(), 300);
}
setTimeout(hideSplash, 8000);

function toolCardHtml(t) {
  const st = t.diff ? diffStats(t.diff) : null;
  return `<div class="card tool ${t.ok ? 'ok' : 'err'}${st ? ' has-diff' : ''}"><div class="card-head"><span class="tag">${esc(KIND_LABEL[t.tool] || t.tool)}</span><span class="card-sub">${esc(t.summary || '')}</span>`
    + (st ? `<span class="diff-stat"><b class="add">+${st.add}</b> <b class="del">-${st.del}</b></span>` : '')
    + `<span class="tool-state">${t.ok ? 'done' : esc(t.status || 'failed')}</span></div>`
    + (t.diff ? `<details class="diff-drop"><summary>Show changes</summary><pre class="diff">${diffHtml(t.diff)}</pre></details>` : '') + '</div>';
}

function toggleArenaPane() {
  return document.body.classList.contains('arena-pane') ? closeArenaPane() : showEngine();
}

function updateWsChip(path) {
  const name = document.getElementById('wsChipName'), chip = document.getElementById('wsChip');
  if (!name || !chip) return;
  const parts = String(path || '').split(/[\\/]/).filter(Boolean);
  name.textContent = parts.length ? parts[parts.length - 1] : 'Pick folder';
  chip.title = path ? `Project folder: ${path}\nClick to change` : 'Pick a project folder for Agent mode';
}

/* Called by the desktop shell when the arena.ai pane opens or closes inside this window. */
function arenaPane(open, share) {
  if (share) document.documentElement.style.setProperty('--pane-w', (share * 100).toFixed(2) + 'vw');
  document.body.classList.toggle('arena-pane', !!open);
}

async function closeArenaPane() {
  arenaPane(false);
  await api('/api/engine/hide', { method: 'POST' });
}

function diffStats(d) {
  let add = 0, del = 0;
  for (const l of String(d || '').split('\n')) {
    if (l.startsWith('+') && !l.startsWith('+++')) add++;
    else if (l.startsWith('-') && !l.startsWith('---')) del++;
  }
  return { add, del };
}

async function openFolder(path) {
  const r = await api('/api/workspace/open', { method: 'POST', body: JSON.stringify({ path }) });
  if (!r.ok) notice(r.error, 'warn');
}

async function saveWebdev(chatId, lane, btn, card) {
  btn.disabled = true;
  const r = await api('/api/workspace/save', { method: 'POST', body: JSON.stringify({ chat_id: chatId, lane }) });
  if (!r.ok) { btn.disabled = false; return notice(r.error, 'err'); }
  card.classList.add('ok');
  card.querySelector('.card-title').textContent = 'Saved on this computer';
  btn.remove();
  if (r.preview) {
    const b = document.createElement('button');
    b.className = 'btn btn-secondary';
    b.textContent = 'Local preview';
    b.onclick = () => window.open(r.preview, '_blank');
    card.querySelector('.card-actions').appendChild(b);
  }
  notice(`Saved ${r.written} file(s) to ${r.root}`, 'ok');
}

async function saveMedia(url, btn) {
  btn.disabled = true;
  const r = await api('/api/media/save', { method: 'POST', body: JSON.stringify({ url }) });
  btn.disabled = false;
  if (!r.ok) return notice(r.error, 'err');
  btn.textContent = 'Saved';
  notice('Saved to ' + r.path, 'ok');
}

/* ── Reply view: renders one streamed answer ── */
const KIND_LABEL = { read_file: 'Read', ls: 'List', search: 'Search', write_file: 'Write', edit_file: 'Edit', mkdir: 'New folder', delete: 'Delete', run_cmd: 'Run', write_project: 'Save project' };
const ALWAYS_LABEL = { write_file: 'edits', edit_file: 'edits', mkdir: 'edits', write_project: 'edits', delete: 'deletes', run_cmd: 'commands', read_file: 'reads', ls: 'reads', search: 'reads' };
const ERR_TITLES = {
  network: 'Cannot reach arena.ai', cloudflare: 'Cloudflare check needed', challenge: 'Human check needed', auth: 'Not signed in',
  rate_limit: 'Too many messages', bad_request: 'arena.ai rejected the request', client_bug: 'App bug', eval_gone: 'Conversation expired',
  too_large: 'Message too large', server: 'arena.ai is having trouble', forbidden: 'arena.ai refused the request', model: 'The model stopped',
  internal: 'App error',
};

function attr(s) { return esc(String(s ?? '')).replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
function safeUrl(u) { u = String(u || ''); return /^(https?:|data:(image|video|audio)\/)/i.test(u) ? u : '#'; }
function stripTools(raw) { return raw.replace(/<tool\s+name\s*=\s*["']?[\w-]+["']?\s*>[\s\S]*?(?:<\/tool\s*>|$)/gi, '').replace(/```[\w-]*[ \t]*\n?\s*```/g, ''); }
function diffHtml(d) {
  return String(d || '').split('\n').map(l => {
    const cls = l.startsWith('+') && !l.startsWith('+++') ? 'add' : l.startsWith('-') && !l.startsWith('---') ? 'del' : l.startsWith('@@') ? 'hunk' : '';
    return `<span class="${cls}">${esc(l)}</span>`;
  }).join('');
}

// Activity rows for arena.ai's own sandbox steps ("Created src/App.tsx"), like arena.ai shows them.
const SB_ICONS = {
  write: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M12 18v-6M9 15h6"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  run: '<path d="m4 17 6-6-6-6M12 19h8"/>',
  read: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
};
function sandboxRowHtml(r) {
  const key = { write: r.verb === 'Created' ? 'write' : 'edit', edit: 'edit', download: 'write', delete: 'edit', touch: 'edit', run: 'run' }[r.kind] || 'read';
  const target = r.kind === 'run' ? (r.detail || '') : (r.path || r.detail || '');
  const stats = (r.add || r.del) ? `<span class="diff-stat"><b class="add">+${r.add || 0}</b> <b class="del">-${r.del || 0}</b></span>` : '';
  const note = r.error ? `<span class="sb-note warn-text">${esc(r.error)}</span>` : (r.abs ? '<span class="sb-note">on your PC</span>' : '');
  return `<svg class="sb-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${SB_ICONS[key]}</svg>`
    + `<span class="sb-verb">${esc(r.verb || r.kind)}</span><span class="sb-path">${esc(target)}</span>${stats}<span class="sb-state"></span>${note}`;
}
function sandboxRow(r) {
  return `<div class="sb-row${r.ok === false ? ' err' : r.ok ? ' ok' : ''}"${r.abs ? ` data-abs="${esc(r.abs)}"` : ''}>${sandboxRowHtml(r)}</div>`;
}
document.addEventListener('click', e => {
  const row = e.target.closest && e.target.closest('.sb-row[data-abs]');
  if (row) openFile(row.dataset.abs);
});

class ReplyView {
  constructor(el) {
    this.el = el;
    this.body = el.querySelector('.msg-content');
    this.lanes = {};
    this.tools = [];
    this.perms = {};
    this.sources = {};
    this.previews = {};
    this.mode = currentMode;
    this.failed = false;
    this.finished = false;
    this.body.innerHTML = '<div class="thinking"><div class="spinner"></div> Waiting for arena.ai...</div>';
  }

  setup(meta) {
    this.mode = meta.mode || this.mode;
    this.chatId = meta.chat_id || this.chatId;
    const dual = !!meta.dual;
    const name = l => this.mode === 'battle' ? 'Model ' + l.toUpperCase() : (meta.names?.[l] || (l === 'a' ? selectedModel : selectedModelB)?.name || 'Model ' + l.toUpperCase());
    this.body.innerHTML = dual
      ? `<div class="sbs-grid">${['a', 'b'].map(l => `<div class="sbs-col"><div class="sbs-head"><span class="sbs-badge ${l}">${l.toUpperCase()}</span>${esc(name(l))}</div><div class="lane" data-lane="${l}"></div></div>`).join('')}</div>`
      : '<div class="lane" data-lane="a"></div>';
    const role = this.el.querySelector('.msg-role');
    if (role && !dual && this.mode !== 'battle') role.textContent = name('a');
    this.lanes = {};
    for (const l of dual ? ['a', 'b'] : ['a']) this.lanes[l] = { root: this.body.querySelector(`.lane[data-lane="${l}"]`), seg: null, r: null };
  }

  lane(l) {
    if (!this.lanes.a) this.setup({});
    return this.lanes[l] || this.lanes.a;
  }

  add(l, cls, html) {
    const ln = this.lane(l);
    const d = document.createElement('div');
    d.className = cls;
    d.innerHTML = html;
    ln.root.appendChild(d);
    ln.seg = null;
    ln.r = null;
    scrollBottom();
    return d;
  }

  text(l, t) {
    const ln = this.lane(l);
    if (!ln.seg) {
      const seg = this.add(l, 'seg streaming-cursor', '');
      seg.raw = '';
      ln.seg = seg;
    }
    const seg = ln.seg;
    seg.raw += t;
    if (!seg.pending) {
      seg.pending = true;
      requestAnimationFrame(() => this.paint(seg));
    }
  }

  paint(seg) {
    seg.pending = false;
    seg.innerHTML = renderMd(stripTools(seg.raw || ''));
    scrollBottom();
  }

  reasoning(l, t) {
    const ln = this.lane(l);
    if (!ln.r) {
      const r = this.add(l, 'reasoning', '<details><summary>Thinking</summary><div class="r-body"></div></details>');
      ln.r = r;
    }
    ln.r.querySelector('.r-body').textContent += t;
  }

  handle(ev) {
    const l = ev.model || 'a';
    switch (ev.type) {
      case 'meta': this.setup(ev); break;
      case 'text': this.text(l, ev.text || ''); break;
      case 'reasoning': this.reasoning(l, ev.text || ''); break;
      case 'source': (this.sources[l] = this.sources[l] || []).push(ev.data); break;
      case 'agent': this.add('a', 'notice-line', `Files: <code>${esc(ev.root)}</code> &middot; ${esc(PERM_LABELS[ev.mode] || ev.mode)}${ev.dual ? ' &middot; A writes to option-a, B to option-b' : ''}`); break;
      case 'round': this.add('a', 'notice-line', `Round ${esc(ev.n)}`); break;
      case 'notice': this.add(l, 'notice-line', esc(ev.text)); break;
      case 'tool_call': this.toolCall(ev); break;
      case 'tool_result': this.toolResult(ev); break;
      case 'sandbox': this.sandbox(l, ev); break;
      case 'sandbox_done': this.sandboxDone(ev); break;
      case 'permission': this.permission(ev); break;
      case 'permission_done': this.permissionDone(ev); break;
      case 'webdev': this.webdev(l, ev); break;
      case 'files_written': this.files(l, ev); break;
      case 'preview': this.preview(l, ev); break;
      case 'media': this.media(l, ev); break;
      case 'challenge': this.challenge(ev); break;
      case 'challenge_done': this.challengeDone(); break;
      case 'error': this.error(ev); break;
      case 'done': this.done(ev); break;
    }
  }

  sandbox(l, ev) {
    const key = l + ':' + ev.id;
    const old = (this.rows = this.rows || {})[key];
    const row = old && ev.id ? old : this.add(l, 'sb-row', '');
    row.className = 'sb-row' + (ev.pending ? ' pending' : '');
    row.innerHTML = sandboxRowHtml(ev);
    if (ev.abs) row.dataset.abs = ev.abs;
    this.rows[key] = row;
  }

  sandboxDone(ev) {
    const row = (this.rows || {})[(ev.model || 'a') + ':' + ev.id];
    if (row) row.classList.add(ev.ok ? 'ok' : 'err');
  }

  toolCall(ev) {
    const st = ev.diff ? diffStats(ev.diff) : null;
    const card = this.add(ev.model || 'a', 'card tool' + (st ? ' has-diff' : ''), `<div class="card-head"><span class="tag">${esc(KIND_LABEL[ev.tool] || ev.tool)}</span><span class="card-sub">${esc(ev.summary || ev.rel || '')}</span>`
      + (st ? `<span class="diff-stat"><b class="add">+${st.add}</b> <b class="del">-${st.del}</b></span>` : '') + `<span class="tool-state">...</span></div>`
      + (ev.diff ? `<details class="diff-drop"><summary>Show changes</summary><pre class="diff">${diffHtml(ev.diff)}</pre></details>` : '')
      + '<div class="tool-out"></div>');
    this.tools.push(card);
  }

  toolResult(ev) {
    const card = this.tools.shift();
    if (!card) return;
    card.classList.add(ev.ok ? 'ok' : 'err');
    card.querySelector('.tool-state').textContent = ev.ok ? 'done' : (ev.status || 'failed');
    if (ev.output) card.querySelector('.tool-out').textContent = ev.output;
  }

  permission(ev) {
    const files = ev.files ? `<div class="file-list">${ev.files.map(esc).join('<br>')}</div>` : '';
    const outside = ev.inside === false ? `<div class="card-sub warn-text">Outside the project folder: ${esc(ev.path)}</div>` : '';
    const card = this.add(ev.model || 'a', 'card perm', `<div class="card-head"><span class="card-title">Allow this?</span><span class="tag">${esc(PERM_LABELS[ev.mode] || '')}</span></div>`
      + `<div class="card-sub">${esc(ev.summary || '')}</div>${outside}`
      + (ev.command ? `<pre class="diff">${esc(ev.command)}</pre>` : '') + (ev.diff ? `<pre class="diff">${diffHtml(ev.diff)}</pre>` : '') + files
      + `<div class="card-actions"><button class="btn btn-primary" data-d="allow">Allow</button><button class="btn btn-secondary" data-d="always">Always allow ${esc(ALWAYS_LABEL[ev.tool] || 'this')}</button><button class="btn btn-secondary" data-d="deny">Deny</button></div>`);
    card.querySelectorAll('[data-d]').forEach(b => { b.onclick = () => answerPermission(ev.id, b.dataset.d, card); });
    this.perms[ev.id] = card;
  }

  permissionDone(ev) {
    const card = this.perms[ev.id];
    if (!card) return;
    const ok = ev.decision === 'allow';
    card.classList.replace('perm', ok ? 'ok' : 'err');
    card.querySelector('.card-title').textContent = ok ? 'Allowed' : 'Denied';
    card.querySelector('.card-actions')?.remove();
  }

  webdev(l, ev) {
    const d = ev.data || {};
    if (ev.event === 'title' && typeof d.title === 'string') this.add(l, 'notice-line', 'Project: ' + esc(d.title));
    const files = Array.isArray(d.files) ? d.files : [];
    if (!files.length) return;
    this.add(l, 'card code-files', `<div class="card-head"><span class="card-title">Code</span><span class="tag">${esc(d.templateKind || 'project')}</span><span class="card-sub">${files.length} file(s)</span></div>`
      + files.slice(0, 40).map(f => `<details><summary class="notice-line">${esc(f.path)}</summary><pre><code>${esc(String(f.content ?? '').slice(0, 200000))}</code></pre></details>`).join(''));
  }

  files(l, ev) {
    const card = this.add(l, 'card' + (ev.saved ? ' ok' : ''), `<div class="card-head"><span class="card-title">${ev.saved ? 'Saved on this computer' : 'Not saved yet'}</span><span class="card-sub">${esc(ev.root)}</span></div>`
      + `<div class="notice-line">${ev.written} written &middot; ${ev.deleted} removed &middot; ${ev.unchanged} unchanged${ev.skipped ? ` &middot; ${ev.skipped} skipped (unsafe path or binary)` : ''}</div><div class="card-actions"></div>`);
    const act = card.querySelector('.card-actions');
    const button = (label, fn, primary) => {
      const b = document.createElement('button');
      b.className = 'btn ' + (primary ? 'btn-primary' : 'btn-secondary');
      b.textContent = label;
      b.onclick = () => fn(b);
      act.appendChild(b);
    };
    if (!ev.saved) button('Save to disk', b => saveWebdev(this.chatId, l, b, card), true);
    button('Open folder', () => openFolder(ev.root));
    button('Download zip', () => { location.href = '/api/workspace/zip?path=' + encodeURIComponent(ev.root); });
    if (ev.preview) button('Local preview', () => window.open(ev.preview, '_blank'));
  }

  preview(l, ev) {
    if (!ev.url) {
      if (ev.status && ev.status !== 'success') this.add(l, 'notice-line', `Preview: ${esc(ev.status)}${ev.message ? ' - ' + esc(ev.message) : ''}`);
      return;
    }
    if (this.previews[l] === ev.url) return;
    this.previews[l] = ev.url;
    this.add(l, 'card', `<div class="card-head"><span class="card-title">Live preview on arena.ai</span></div><div class="card-actions"><a class="btn btn-secondary" href="${attr(safeUrl(ev.url))}" target="_blank" rel="noopener">Open preview</a></div>`);
  }

  media(l, ev) {
    const u = attr(safeUrl(ev.url));
    const tag = ev.kind === 'video' ? `<video src="${u}" controls></video>` : ev.kind === 'audio' ? `<audio src="${u}" controls></audio>` : `<img src="${u}" alt="">`;
    const box = this.add(l, 'card media-box', tag + `<div class="card-actions"><button class="btn btn-secondary">Save to disk</button><a class="btn btn-secondary" target="_blank" rel="noopener" href="${u}">Open</a></div>`);
    box.querySelector('button').onclick = e => saveMedia(ev.url, e.target);
  }

  challenge(ev) {
    this.chal = this.add('a', 'card challenge', `<div class="card-head"><span class="card-title">${ev.kind === 'cloudflare' ? 'Cloudflare check' : 'Human check'}</span></div><div class="card-sub">${esc(ev.message)}</div>`
      + '<div class="card-actions"><button class="btn btn-primary">Show arena.ai window</button><button class="btn btn-secondary">Cancel</button></div>');
    const [show, cancel] = this.chal.querySelectorAll('button');
    show.onclick = showEngine;
    cancel.onclick = stopStreaming;
  }

  challengeDone() {
    if (!this.chal) return;
    this.chal.classList.replace('challenge', 'ok');
    this.chal.querySelector('.card-sub').textContent = 'Verified. Sending your message...';
    this.chal.querySelector('.card-actions')?.remove();
    this.chal = null;
  }

  error(ev) {
    this.failed = true;
    const detail = ev.detail && ev.detail !== ev.message ? `<details><summary class="notice-line">Details</summary><pre class="diff">${esc(String(ev.detail).slice(0, 4000))}</pre></details>` : '';
    const card = this.add(ev.model || 'a', 'card err', `<div class="card-head"><span class="card-title">${esc(ERR_TITLES[ev.code] || 'Something went wrong')}</span>${ev.status ? `<span class="tag">HTTP ${esc(ev.status)}</span>` : ''}</div>`
      + `<div class="card-sub">${esc(ev.message || ev.text || '')}</div>${detail}<div class="card-actions"></div>`);
    const act = card.querySelector('.card-actions');
    const button = (label, fn) => {
      const b = document.createElement('button');
      b.className = 'btn btn-secondary';
      b.textContent = label;
      b.onclick = fn;
      act.appendChild(b);
    };
    if (ev.retry) button(ev.wait ? `Retry (wait about ${ev.wait}s)` : 'Retry', () => sendMessage(lastSent));
    if (ev.code === 'auth') button('Sign in', showLogin);
    if (ev.code === 'challenge' || ev.code === 'cloudflare') button('Show arena.ai window', showEngine);
    if (['network', 'server', 'http', 'internal', 'forbidden'].includes(ev.code)) button('Run diagnostics', () => runDoctor(true));
  }

  settle() {
    this.body.querySelectorAll('.seg').forEach(s => { this.paint(s); s.classList.remove('streaming-cursor'); });
    hlAll(this.body);
    addCopyBtns(this.body);
  }

  done(ev) {
    this.finished = true;
    for (const [l, ln] of Object.entries(this.lanes)) {
      if (ln.seg && ln.seg.pending) this.paint(ln.seg);  // text can still be queued in rAF when a fast answer ends
      const src = this.sources[l];
      if (src && src.length) {
        this.add(l, 'sources', 'Sources: ' + src.map((s, i) => {
          const u = safeUrl((s && (s.url || s.uri)) || '');
          return `<a href="${attr(u)}" target="_blank" rel="noopener">${esc((s && (s.title || s.name)) || (u !== '#' ? u : 'source ' + (i + 1)))}</a>`;
        }).join(' &middot; '));
      }
      if (!ln.root.textContent.trim() && !this.failed) this.add(l, 'notice-line', '(no response)');
    }
    this.settle();
    if (ev.chat_id) currentChatId = ev.chat_id;
    if (ev.dual && this.mode === 'battle' && !this.failed) {
      const row = document.createElement('div');
      row.className = 'vote-row';
      row.innerHTML = `<span class="vote-label">Which response was better?</span>
        <button class="vote-btn" onclick="castVote(this, 'a')">A is better</button>
        <button class="vote-btn" onclick="castVote(this, 'b')">B is better</button>
        <button class="vote-btn tie" onclick="castVote(this, 'tie')">Tie</button>
        <button class="vote-btn bad" onclick="castVote(this, 'bad')">Both bad</button>
        <span class="vote-note">Local only: not sent to the arena.ai leaderboard</span>`;
      this.el.appendChild(row);
    }
  }

  finish() {
    if (!this.finished) this.settle();
    const th = this.body.querySelector('.thinking');
    if (th) th.textContent = '(no response)';
  }
}

/* ── Global shortcuts ── */
document.addEventListener('keydown', e => {
  if (e.key === 'F1') { e.preventDefault(); showHelp(); }
  else if ((e.ctrlKey || e.metaKey) && e.key === ',') { e.preventDefault(); showSettings(); }
  else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === 'n' || e.key === 'N')) { e.preventDefault(); newChat(); }
  else if (e.key === 'Escape') { closeHelp(); hideSlash(); }
});
