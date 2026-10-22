// Application-controller checks with an explicit in-memory DOM/API double.
// These do not claim to verify browser rendering or assistive technology support.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function setup() {
  const nodes = new Map();
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.value = ''; this.disabled = false; this.textContent = ''; this.classList = {toggle() {}}; }
    set id(value) { this._id = value; nodes.set(value, this); }
    get id() { return this._id; }
    append(...values) { this.children.push(...values); }
    replaceChildren(...values) { this.children = values; }
    setAttribute() {}
    addEventListener(event, callback) { (this.events[event] ||= []).push(callback); }
    reportValidity() { return Boolean(this.value || this.tag === 'form'); }
    focus() { this.focused = true; }
    async fire(event = 'click') {
      for (const callback of this.events[event] || []) await callback({preventDefault() {}});
      await flush();
    }
  }
  function node(id) {
    if (!nodes.has(id)) { const e = new Element(id.endsWith('Form') ? 'form' : 'div'); e.id = id; }
    return nodes.get(id);
  }
  const state = {
    ai: {ready: true, model: 'test-provider', endpoint: 'http://127.0.0.1:11434/v1'},
    admin: true, history: [], documents: [], workflows: [],
    effective: {detail: 'balanced', pacing: 'one_step', input: 'any', reduced_motion: false},
    profile: {explicit: {}, approved: {}, observed: {}, suggestions: {}, learning_enabled: true}
  };
  const calls = [];
  let fail = false;
  const context = vm.createContext({
    document: {getElementById: node, createElement: tag => new Element(tag),
      querySelector: () => ({content: 'test-token'}), body: new Element('body')},
    window: {addEventListener() {}}, navigator: {language: 'en-US'},
    Option: class extends Element { constructor(name, value) { super('option'); this.textContent = name; this.value = value; } },
    confirm: () => true, setTimeout, clearTimeout,
    fetch: async (path, options) => {
      calls.push({path, options});
      const input = options.body ? JSON.parse(options.body) : null;
      let output = state;
      if (path === '/api/ask') {
        if (fail) return {ok: false, json: async () => ({error: 'Provider unavailable'})};
        const w = {id: 'workflow-1', title: 'Setup', steps: [
          {instruction: 'Open the Extensions view', application: 'VS Code', keyboard_hint: 'Command+Shift+X', source_ids: ['source-1']},
          {instruction: 'Open your project', application: 'VS Code', keyboard_hint: '', source_ids: ['source-1']}],
          current_step: 0, status: 'active', sources: [{title: '<script>untrusted</script>', id: 'source-1', ordinal: 1, content: '<img src=x onerror=alert(1)>'}]};
        if (input.mode === 'plan') state.workflows = [w];
        output = {message: '<script>model text stays text</script>', sources: w.sources, workflow: input.mode === 'plan' ? w : null};
      } else if (path === '/api/confirm') {
        assert.equal(input.step, state.workflows[0].current_step);
        state.workflows[0].current_step++;
      } else if (path === '/api/preferences') {
        state.profile.explicit = input.values;
        state.effective = {...state.effective, ...input.values};
      } else if (path === '/api/clear-history') state.history = [];
      return {ok: true, json: async () => structuredClone(output)};
    }
  });
  vm.runInContext(fs.readFileSync('app.js', 'utf8'), context);
  await flush();
  return {node, state, calls, setFail: () => { fail = true; }};
}
function flush() { return new Promise(resolve => setImmediate(resolve)); }

test('onboarding UI creates a plan, presents one step, confirms and resumes', async () => {
  const {node, calls} = await setup();
  node('request').value = 'Help with onboarding';
  await node('plan').fire();
  assert.equal(node('stepsList').children.length, 1);
  assert.equal(node('progress').value, 0);
  assert.equal(node('confirm').disabled, false);
  assert.equal(node('stepsList').children[0].children[0].textContent, 'Open the Extensions view');
  await node('confirm').fire();
  assert.equal(node('progress').value, 1);
  assert.equal(node('stepsList').children[0].children[0].textContent, 'Open your project');
  await node('resume').fire();
  assert.equal(node('request').focused, true);
  const messages = node('conversation').children;
  assert.match(messages.at(-1).children[1].textContent, /1\/2 steps confirmed/);
  assert.ok(calls.every(c => c.options.headers['X-A11y-Token'] === 'test-token'));
});

test('preferences update task presentation and are explicitly submitted', async () => {
  const {node, state} = await setup();
  node('request').value = 'Help';
  await node('plan').fire();
  node('pref-pacing').value = JSON.stringify('all_steps');
  await node('preferencesForm').fire('submit');
  assert.equal(state.profile.explicit.pacing, 'all_steps');
  assert.equal(node('stepsList').children.length, 2);
});

test('model and document content is inserted as text, never parsed markup', async () => {
  const {node} = await setup();
  node('request').value = 'Question';
  await node('chatForm').fire('submit');
  const reply = node('conversation').children[1];
  assert.equal(reply.children[1].textContent, '<script>model text stays text</script>');
  const source = reply.children[2].children[1];
  assert.equal(source.children[2].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(reply.children[1].innerHTML, undefined);
});

test('provider errors are visible and controls recover; unsupported voice is disabled', async () => {
  const {node, setFail} = await setup();
  setFail();
  node('request').value = 'Question';
  await node('plan').fire();
  assert.equal(node('status').textContent, 'Provider unavailable');
  assert.equal(node('send').disabled, false);
  assert.equal(node('plan').disabled, false);
  assert.equal(node('listen').disabled, true);
  assert.equal(node('read').disabled, true);
});
