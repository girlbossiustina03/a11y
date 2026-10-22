'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="a11y-token"]').content;
let state = null;
let selected = null;
let latestReply = '';
let busy = false;
const choices = {
  detail: [['concise', 'Concise'], ['balanced', 'Balanced'], ['detailed', 'Detailed']],
  pacing: [['one_step', 'One step at a time'], ['all_steps', 'All steps']],
  input: [['any', 'No preference'], ['keyboard', 'Prefer keyboard instructions']],
  reduced_motion: [[false, 'Animation enabled'], [true, 'Reduced motion']]
};

async function api(path, body) {
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {'X-A11y-Token': token, 'Content-Type': 'application/json'},
    ...(body === undefined ? {} : {body: JSON.stringify(body)})
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}
function status(message) { $('status').textContent = message; }
function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = content;
  if (className) node.className = className;
  return node;
}
function setA11y(mode, message) {
  $('a11yAvatar').className = `a11y-avatar state-${mode}`;
  if (message) $('a11yBubble').textContent = message.slice(0, 220);
}
function message(role, content, sources = []) {
  const article = element('article', undefined, `message ${role}`);
  article.append(element('strong', role === 'user' ? 'You' : 'A11y'), element('p', content));
  if (sources.length) {
    const details = element('details');
    details.append(element('summary', `${sources.length} company source${sources.length === 1 ? '' : 's'}`));
    renderSources(details, sources);
    article.append(details);
  }
  $('conversation').append(article);
  $('conversation').scrollTop = $('conversation').scrollHeight;
}
function renderSources(container, sources) {
  for (const source of sources) {
    const section = element('section', undefined, 'source');
    section.append(element('strong', `${source.title} · section ${source.ordinal}`),
      element('small', `[${source.id}]`), element('p', source.content));
    container.append(section);
  }
}
function selectedWorkflow() { return state?.workflows.find(w => w.id === selected); }
function renderWorkflow() {
  const workflow = selectedWorkflow();
  const list = $('stepsList');
  list.replaceChildren();
  $('workflowSources').replaceChildren();
  $('confirm').disabled = busy || !workflow || workflow.status !== 'active';
  $('resume').disabled = busy || !workflow;
  if (!workflow) {
    $('progressText').textContent = state?.unavailable_tasks ? 'Some saved tasks are hidden because their company sources are no longer accessible.' : 'Import your onboarding guide, then ask A11y to create a workflow.';
    $('progress').value = 0;
    return;
  }
  $('progress').max = workflow.steps.length;
  $('progress').value = workflow.current_step;
  $('progressText').textContent = `${workflow.current_step} of ${workflow.steps.length} steps confirmed · ${workflow.status}`;
  workflow.steps.forEach((step, index) => {
    if (state.effective.pacing === 'one_step' && (index !== workflow.current_step || workflow.status === 'completed')) return;
    const item = element('li', undefined, `step-item ${index < workflow.current_step ? 'completed' : ''}`);
    item.value = index + 1;
    if (index === workflow.current_step) item.setAttribute('aria-current', 'step');
    item.append(element('p', step.instruction));
    if (step.application) item.append(element('small', `Application: ${step.application}`));
    if (step.keyboard_hint) item.append(element('p', `Keyboard: ${step.keyboard_hint}`, 'keyboard-hint'));
    item.append(element('small', `Sources: ${step.source_ids.join(', ') || 'General guidance'}`));
    list.append(item);
  });
  if (workflow.status === 'completed') list.append(element('li', 'All steps confirmed. Your progress is saved.', 'step-item'));
  renderSources($('workflowSources'), workflow.sources || []);
}
function buildPreferences() {
  for (const [key, options] of Object.entries(choices)) {
    const wrapper = element('div');
    const label = element('label', key.replaceAll('_', ' '));
    label.htmlFor = `pref-${key}`;
    const select = element('select');
    select.id = label.htmlFor;
    select.append(new Option('Use approved/default', 'default'));
    for (const [value, name] of options) select.append(new Option(name, JSON.stringify(value)));
    wrapper.append(label, select);
    $('preferenceControls').append(wrapper);
  }
}
async function refresh(workflowId) {
  state = await api('state');
  if (workflowId) selected = workflowId;
  if (!state.workflows.some(w => w.id === selected)) selected = state.workflows[0]?.id || null;
  $('workflowSelect').replaceChildren(...state.workflows.map(w => new Option(`${w.title} · ${w.status}`, w.id)));
  if (selected) $('workflowSelect').value = selected;
  $('providerStatus').textContent = state.ai.ready
    ? `AI: ${state.ai.model} · ${state.ai.endpoint}. Requests include conversation, preferences and relevant company excerpts.`
    : state.ai.message;
  // Respect OS reduced-motion settings even if the user leaves this option at default.
  document.body.classList.toggle('reduced-motion', state.effective.reduced_motion);
  for (const key of Object.keys(choices)) {
    $(`pref-${key}`).value = Object.hasOwn(state.profile.explicit, key) ? JSON.stringify(state.profile.explicit[key]) : 'default';
  }
  $('learning').checked = state.profile.learning_enabled;
  $('profile').textContent = JSON.stringify({effective: state.effective, ...state.profile}, null, 2);
  $('suggestions').replaceChildren();
  for (const [signal, suggestion] of Object.entries(state.profile.suggestions)) {
    const wrapper = element('div', undefined, 'notice');
    wrapper.append(element('p', `Suggested: ${suggestion.key} → ${suggestion.value}. ${suggestion.reason}`));
    for (const approve of [true, false]) {
      const btn = element('button', approve ? 'Approve adaptation' : 'Dismiss');
      btn.type = 'button';
      btn.addEventListener('click', () => act(async () => {
        await api('adapt', {signal, approve});
        await refresh();
        status(approve ? 'Approved preference saved.' : 'Suggestion dismissed.');
      }));
      wrapper.append(btn);
    }
    $('suggestions').append(wrapper);
  }
  $('documents').replaceChildren();
  for (const doc of state.documents) {
    const li = element('li', `${doc.title} · roles: ${doc.roles.join(', ')}`);
    if (state.admin) {
      const remove = element('button', 'Remove document');
      remove.type = 'button';
      remove.addEventListener('click', () => act(async () => {
        if (!confirm(`Remove “${doc.title}” from company retrieval?`)) return;
        await api('delete-document', {id: doc.id});
        await refresh();
        $('conversation').replaceChildren();
        for (const item of state.history) message(item.role, item.content);
        latestReply = [...state.history].reverse().find(item => item.role === 'assistant')?.content || '';
        $('read').disabled = !speech || !latestReply;
        status('Document removed. Tasks and conversations that depend on it are now hidden.');
      }));
      li.append(remove);
    }
    $('documents').append(li);
  }
  if (!state.documents.length) $('documents').append(element('li', 'No documents available to your configured roles.'));
  $('adminPanel').hidden = !state.admin;
  $('adminNotice').textContent = state.admin ? 'Local administrator mode enabled.' : 'Document management is available when launched with --admin.';
  renderWorkflow();
}
async function act(operation) {
  try { await operation(); } catch (error) { status(error.message); }
}
function setBusy(value) {
  busy = value;
  for (const id of ['send', 'plan', 'confirm', 'resume']) $(id).disabled = value;
  $('chatForm').setAttribute('aria-busy', String(value));
  renderWorkflow();
}
async function ask(mode) {
  if (busy || !$('chatForm').reportValidity()) return;
  const request = $('request').value.trim();
  if (!request) return;
  setBusy(true);
  message('user', request);
  setA11y('thinking', 'Finding your next step…');
  status('AI request in progress. Your confirmed task progress is saved.');
  try {
    const result = await api('ask', {request, mode, workflow_id: selected});
    latestReply = result.message;
    $('read').disabled = !speech;
    message('assistant', result.message, result.sources);
    await refresh(result.workflow?.id);
    setA11y('idle', result.message);
    status(result.workflow ? 'Workflow created and saved. Review your next step.' : 'Reply ready.');
    $('request').value = '';
  } catch (error) {
    status(error.message);
    setA11y('idle', 'Your progress is saved. Review the error above.');
  } finally { setBusy(false); }
}
$('chatForm').addEventListener('submit', event => { event.preventDefault(); ask('answer'); });
$('plan').addEventListener('click', () => ask('plan'));
$('request').addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); ask('answer'); }
});
$('workflowSelect').addEventListener('change', () => { selected = $('workflowSelect').value; renderWorkflow(); });
$('confirm').addEventListener('click', () => act(async () => {
  const w = selectedWorkflow();
  if (!w || busy) return;
  $('confirm').disabled = true;
  try {
    await api('confirm', {workflow_id: w.id, step: w.current_step});
    await refresh(w.id);
    setA11y('celebrate', 'Progress saved. Continue when you are ready.');
    status('Step confirmed and saved.');
  } finally { renderWorkflow(); }
}));
$('resume').addEventListener('click', () => {
  const w = selectedWorkflow();
  if (!w) return;
  const next = w.status === 'active' ? `Next: ${w.steps[w.current_step].instruction}` : 'All steps confirmed.';
  message('assistant', `Resumed: ${w.title}. ${w.current_step}/${w.steps.length} steps confirmed. ${next}`);
  $('request').focus();
  status('Saved progress restored. Ask a question or continue your current step.');
});
$('preferencesForm').addEventListener('submit', event => {
  event.preventDefault();
  act(async () => {
    const values = {};
    for (const key of Object.keys(choices)) {
      const value = $(`pref-${key}`).value;
      if (value !== 'default') values[key] = JSON.parse(value);
    }
    await api('preferences', {values, learning_enabled: $('learning').checked});
    await refresh();
    status('Preferences saved. Current task presentation and future replies now use them.');
  });
});
$('resetLearned').addEventListener('click', () => act(async () => {
  await api('reset-learned', {}); await refresh(); status('Learned preferences and observations reset. Explicit settings retained.');
}));
$('clearHistory').addEventListener('click', () => act(async () => {
  await api('clear-history', {}); $('conversation').replaceChildren(); latestReply = ''; $('read').disabled = true; status('Saved conversation cleared.');
}));
$('documentFile').addEventListener('change', () => act(async () => {
  const file = $('documentFile').files[0];
  if (!file) return;
  if (file.size > 480000 || !/\.(txt|md)$/i.test(file.name)) throw new Error('Choose a text/Markdown file under 480 KB.');
  $('documentTitle').value = file.name;
  $('documentBody').value = await file.text();
}));
$('documentForm').addEventListener('submit', event => {
  event.preventDefault();
  act(async () => {
    await api('documents', {title: $('documentTitle').value, body: $('documentBody').value,
      roles: $('documentRoles').value.split(',').map(v => v.trim()).filter(Boolean)});
    await refresh(); status('Company document imported and available for permitted roles.');
    $('documentBody').value = ''; $('documentTitle').value = '';
  });
});
$('a11yAvatar').addEventListener('click', () => $('request').focus());
const speech = window.speechSynthesis;
$('read').disabled = true;
$('stopSpeech').disabled = !speech;
$('read').addEventListener('click', () => {
  if (!latestReply || !speech) return;
  speech.cancel();
  const utterance = new SpeechSynthesisUtterance(latestReply);
  utterance.onstart = () => setA11y('speaking', 'Reading the latest response…');
  utterance.onend = utterance.onerror = () => setA11y('idle', 'Ready when you are.');
  speech.speak(utterance);
});
$('stopSpeech').addEventListener('click', () => { speech?.cancel(); setA11y('idle', 'Speech stopped.'); });
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
$('listen').disabled = !Recognition;
if (!Recognition) $('voiceStatus').textContent = 'Speech input is unavailable in this browser. Text and keyboard input work.';
$('listen').addEventListener('click', () => {
  if (recognition) { recognition.stop(); return; }
  if (!confirm('Start optional voice input? Your browser may send audio to its speech provider. '
    + 'The microphone stops after this utterance or after 30 seconds. You can edit the transcript before sending it to A11y.')) return;
  recognition = new Recognition();
  const current = recognition;
  current.lang = navigator.language || 'en-US';
  current.continuous = false;
  current.interimResults = false;
  const stopTimer = setTimeout(() => current.stop(), 30000);
  current.onstart = () => {
    $('listen').textContent = 'Stop voice input';
    $('voiceStatus').textContent = 'Microphone active · listening for one utterance.';
    setA11y('listening', 'Listening. You can edit your words before sending.');
  };
  current.onresult = event => { $('request').value = event.results[0][0].transcript; $('request').focus(); };
  current.onerror = event => { status(`Voice input: ${event.error}. You can continue by typing.`); };
  current.onend = () => {
    clearTimeout(stopTimer); recognition = null;
    $('listen').textContent = 'Start voice input';
    $('voiceStatus').textContent = 'Microphone off. Review your words before sending.';
    setA11y('idle', 'Ready when you are.');
  };
  try { current.start(); } catch (error) { clearTimeout(stopTimer); recognition = null; status(error.message); }
});
window.addEventListener('pagehide', () => { recognition?.abort(); speech?.cancel(); });
buildPreferences();
act(async () => {
  await refresh();
  for (const item of state.history) message(item.role, item.content);
  latestReply = [...state.history].reverse().find(item => item.role === 'assistant')?.content || '';
  $('read').disabled = !speech || !latestReply;
  status('Ready. Saved tasks restored. Screen and microphone are off.');
});
