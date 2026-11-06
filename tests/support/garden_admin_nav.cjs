'use strict';
// Executes the real garden shell (v3.js) against a small DOM and reports
// which training links each session role receives. No browser required.
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8');

function createDom() {
  class Node {
    constructor(tag) {
      this.tagName = String(tag).toUpperCase();
      this.children = [];
      this.parent = null;
      this.attrs = {};
      this.classList = new ClassList(this);
      this.style = {};
      this.hidden = false;
      this.disabled = false;
      this._text = '';
    }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this._text = String(value ?? ''); this.children = []; }
    get className() { return this.attrs.class || ''; }
    set className(value) { this.attrs.class = String(value); }
    get id() { return this.attrs.id || ''; }
    set id(value) { this.attrs.id = String(value); }
    setAttribute(key, value) { this.attrs[key] = String(value); }
    getAttribute(key) { return Object.prototype.hasOwnProperty.call(this.attrs, key) ? this.attrs[key] : null; }
    append(...nodes) { for (const node of nodes.flat()) this._insert(this.children.length, node); }
    prepend(...nodes) { const list = nodes.flat(); for (let i = list.length - 1; i >= 0; i--) this._insert(0, list[i]); }
    _insert(index, node) {
      if (node == null || node === false) return;
      const child = typeof node === 'string' ? new Node('#text') : node;
      if (typeof node === 'string') child._text = node;
      if (child.parent) child.remove();
      child.parent = this;
      this.children.splice(index, 0, child);
    }
    after(...nodes) { this._sibling(1, nodes); }
    before(...nodes) { this._sibling(0, nodes); }
    _sibling(offset, nodes) {
      if (!this.parent) throw new Error(this.tagName + ' has no parent');
      const index = this.parent.children.indexOf(this);
      nodes.flat().forEach((node, extra) => this.parent._insert(index + offset + extra, node));
    }
    remove() {
      if (!this.parent) return;
      this.parent.children = this.parent.children.filter(child => child !== this);
      this.parent = null;
    }
    replaceChildren(...nodes) { this.children.forEach(child => { child.parent = null; }); this.children = []; this.append(...nodes); }
    addEventListener() {}
    removeEventListener() {}
    focus() {}
    click() {}
    showModal() { this.open = true; }
    close() { this.open = false; }
    querySelector(selector) { return queryAll(this, selector)[0] || null; }
    querySelectorAll(selector) { return queryAll(this, selector); }
  }
  class ClassList {
    constructor(node) { this.node = node; }
    _parts() { return (this.node.attrs.class || '').split(/\s+/).filter(Boolean); }
    _write(parts) { this.node.attrs.class = parts.join(' '); }
    add(...names) { const set = new Set(this._parts()); names.forEach(name => set.add(name)); this._write([...set]); }
    remove(...names) { const ban = new Set(names); this._write(this._parts().filter(name => !ban.has(name))); }
    toggle(name, force) { const on = force === undefined ? !this.contains(name) : Boolean(force); if (on) this.add(name); else this.remove(name); return on; }
    contains(name) { return this._parts().includes(name); }
  }
  function matchSimple(node, token) {
    let i = 0;
    let tag = '';
    let id = '';
    const classes = [];
    const attrs = [];
    const ident = () => { let value = ''; while (i < token.length && /[\w-]/.test(token[i])) value += token[i++]; return value; };
    if (/[A-Za-z*]/.test(token[0] || '')) tag = ident();
    while (i < token.length) {
      if (token[i] === '#') { i++; id = ident(); }
      else if (token[i] === '.') { i++; classes.push(ident()); }
      else if (token[i] === '[') {
        const end = token.indexOf(']', i + 1);
        const body = token.slice(i + 1, end);
        i = end + 1;
        const eq = body.indexOf('=');
        attrs.push(eq === -1 ? [body, null] : [body.slice(0, eq), body.slice(eq + 1).replace(/^["']|["']$/g, '')]);
      } else break;
    }
    if (tag && tag !== '*' && node.tagName !== tag.toUpperCase()) return false;
    if (id && node.attrs.id !== id) return false;
    const have = new Set((node.attrs.class || '').split(/\s+/).filter(Boolean));
    if (classes.some(name => !have.has(name))) return false;
    return attrs.every(([key, value]) => Object.prototype.hasOwnProperty.call(node.attrs, key) && (value === null || node.attrs[key] === value));
  }
  function matches(node, selector) {
    const parts = selector.trim().split(/\s+/);
    if (!matchSimple(node, parts[parts.length - 1])) return false;
    let cursor = node.parent;
    for (let index = parts.length - 2; index >= 0; index--) {
      while (cursor && !matchSimple(cursor, parts[index])) cursor = cursor.parent;
      if (!cursor) return false;
      cursor = cursor.parent;
    }
    return true;
  }
  function descendants(root) {
    const out = [];
    (function walk(node) { for (const child of node.children) { out.push(child); walk(child); } })(root);
    return out;
  }
  function queryAll(root, selector) {
    const parts = selector.split(',').map(part => part.trim()).filter(Boolean);
    return descendants(root).filter(node => parts.some(part => matches(node, part)));
  }
  const document = new Node('#document');
  const html = new Node('html');
  const body = new Node('body');
  document.append(html);
  html.append(body);
  document.documentElement = html;
  document.body = body;
  const byId = new Map();
  document.createElement = tag => new Node(tag);
  document.createTextNode = value => { const node = new Node('#text'); node._text = String(value); return node; };
  document.getElementById = id => byId.get(id) || null;
  document.querySelector = selector => queryAll(document, selector)[0] || null;
  document.querySelectorAll = selector => queryAll(document, selector);
  document.addEventListener = () => {};
  function add(tag, id, parent, className) {
    const node = new Node(tag);
    if (id) { node.setAttribute('id', id); byId.set(id, node); }
    if (className) node.className = className;
    (parent || body).append(node);
    return node;
  }
  const sidebar = add('aside', 'sidebar');
  add('button', 'new-project', sidebar);
  add('span', 'list-label', sidebar);
  add('button', 'refresh-list', sidebar);
  add('nav', 'project-list', sidebar);
  add('button', 'capabilities-button', sidebar);
  const brand = add('a', null, sidebar, 'brand');
  const label = new Node('span');
  const small = new Node('small');
  small.textContent = '让好奇慢慢生长';
  label.append(small);
  brand.append(label);
  add('button', 'mobile-menu', body);
  add('button', 'garden-home', body);
  add('strong', 'page-title', body);
  add('div', 'growth-compass', body);
  add('nav', 'view-tabs', body);
  add('div', 'compass-action', body);
  const tools = add('div', null, body, 'top-tools');
  add('button', 'refresh-project', tools);
  add('button', 'records-toggle', tools);
  add('button', 'theme-toggle', tools);
  add('div', 'message', body);
  add('div', 'busy-notice', body);
  add('span', 'busy-text', body);
  add('span', 'busy-elapsed', body);
  add('section', 'grading-state', body);
  add('section', 'content', body);
  add('button', 'sidebar-shade', body);
  add('dialog', 'modal', body);
  add('h2', 'modal-title', body);
  add('button', 'modal-close', body);
  add('div', 'modal-content', body);
  return { Node, document };
}

const cases = {
  admin: { account: 'admin-1', login: 'admin@example.test', csrf_token: 'csrf', guest: false, logout: true,
    training: { role: 'admin', display_name: '培训管理员', unit_id: 'unit-1', unit_name: '青禾研习社' } },
  employee: { account: 'employee-1', login: 'employee@example.test', csrf_token: 'csrf', guest: false, logout: true,
    training: { role: 'employee', display_name: '培训管理员', unit_id: 'unit-1', unit_name: '青禾研习社' } },
  personal: { account: 'person-1', login: 'person@example.test', csrf_token: 'csrf', guest: false, logout: true,
    training: { role: 'personal', display_name: 'person', unit_id: null, unit_name: '个人学习空间' } },
  guest: { account: 'guest-1', csrf_token: 'csrf', guest: true, logout: false,
    training: { role: 'guest', display_name: '游客', unit_id: null, unit_name: '个人学习空间' } },
  none: { account: 'local-1', guest: false, logout: false },
};

function run(name, session) {
  const { Node, document } = createDom();
  const seen = new Set();
  let resolveSettled;
  const settled = new Promise(resolve => { resolveSettled = resolve; });
  const expected = ['/session', '/capabilities', '/material-packs', '/projects'];
  if (session.csrf_token) expected.push('/jobs/active');
  const storage = new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask,
    AbortController, URL, URLSearchParams, Promise, Math, Date, JSON, Object, Array, String, Number, Boolean,
    Error, TypeError, RegExp, Map, Set, Symbol, Proxy, Reflect, encodeURIComponent, decodeURIComponent,
    parseInt, parseFloat, isNaN, isFinite, crypto, Node,
    document,
    localStorage: {
      getItem: key => storage.has(key) ? storage.get(key) : null,
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: key => storage.delete(key),
    },
    location: { pathname: '/learn', search: '', hash: '#/garden', origin: 'http://127.0.0.1', href: 'http://127.0.0.1/learn#/garden', replace() {}, assign() {} },
    history: { replaceState() {} },
    navigator: { userAgent: 'garden-admin-nav-test' },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    fetch: async url => {
      const path = String(url);
      seen.add(path);
      if (expected.every(item => seen.has(item))) resolveSettled();
      const payloads = {
        '/session': session,
        '/capabilities': [],
        '/material-packs': { packs: [] },
        '/projects': [],
        '/jobs/active': { job: null },
      };
      const data = payloads[path];
      return { status: data ? 200 : 404, ok: Boolean(data), json: async () => data || { error: { message: '未提供 ' + path } } };
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.addEventListener = () => {};
  sandbox.removeEventListener = () => {};
  sandbox.scrollTo = () => {};
  sandbox.innerWidth = 1280;
  sandbox.innerHeight = 800;
  sandbox.SkillTreeGarden = () => ({
    init() {}, shell() {}, readRoute: async () => {}, navigate() {}, syncRoute() {}, afterWrite() {},
    home: () => document.createElement('div'),
    prepare: () => document.createElement('div'),
    lesson: () => document.createElement('div'),
    graph: () => document.createElement('div'),
  });
  vm.createContext(sandbox);
  const errors = [];
  const onError = error => errors.push(error);
  process.on('unhandledRejection', onError);
  try {
    vm.runInContext(source, sandbox, { filename: 'v3.js' });
  } catch (error) {
    process.off('unhandledRejection', onError);
    throw error;
  }
  return Promise.race([
    settled,
    new Promise((_, reject) => setTimeout(() => reject(new Error(name + ' did not finish; fetches=' + [...seen].join(','))), 2000)),
  ]).then(() => {
    process.off('unhandledRejection', onError);
    if (errors.length) throw errors[0];
    const tools = document.querySelector('.top-tools');
    const links = [...tools.children].filter(node => node.tagName === 'A').map(node => ({ href: node.getAttribute('href'), text: node.textContent, hidden: node.hidden }));
    return {
      role: name,
      links,
      brand: document.querySelector('.brand small').textContent,
      pageTitle: document.getElementById('page-title').textContent,
    };
  }).finally(() => process.off('unhandledRejection', onError));
}

(async () => {
  const report = {};
  for (const [name, session] of Object.entries(cases)) report[name] = await run(name, session);
  process.stdout.write(JSON.stringify(report));
})().catch(error => { console.error(error); process.exit(1); });
