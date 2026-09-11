import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../unrender/product/static/account.js', import.meta.url), 'utf8');
async function render({ token = false, email = false, failed = false } = {}) {
  const nodes = new Map();
  const node = (id) => {
    if (!nodes.has(id)) nodes.set(id, { hidden: ['account-form', 'email-help-links', 'account-error'].includes(id), textContent: '', addEventListener() {} });
    return nodes.get(id);
  };
  node('account-form').elements = { namedItem: node };
  const location = { hash: token ? '#account=reset&token=synthetic' : '', pathname: '/account', search: token ? '?mode=invite' : '' };
  let replaced = false;
  const context = vm.createContext({
    document: { getElementById: node }, location, URLSearchParams,
    history: { replaceState() { replaced = true; } },
    fetch: async () => ({ ok: !failed, json: async () => ({ email_available: email }) }),
  });
  vm.runInContext(source, context);
  await new Promise((resolve) => setImmediate(resolve));
  return { node, replaced };
}
for (const email of [false, true]) {
  const request = await render({ email });
  assert.equal(request.node('account-form').hidden, !email);
  assert.equal(request.node('email-help-links').hidden, !email);
  if (!email) {
    assert.match(request.node('account-description').textContent, /Email recovery isn’t available/);
    assert.match(request.node('account-description').textContent, /email address alone isn’t enough/);
    assert.doesNotMatch(request.node('account-description').textContent, /person who invited/);
  }
  const invitation = await render({ token: true, email });
  assert.equal(invitation.node('account-form').hidden, false);
  assert.equal(invitation.node('email-help-links').hidden, !email);
  assert.equal(invitation.node('account-submit').textContent, 'Activate workspace');
  assert.equal(invitation.replaced, true);
}
const failed = await render({ failed: true });
assert.equal(failed.node('account-form').hidden, true);
assert.equal(failed.node('account-error').hidden, false);
const tokenFailure = await render({ token: true, failed: true });
assert.equal(tokenFailure.node('account-form').hidden, false);
assert.equal(tokenFailure.node('account-error').hidden, true);
console.log('Account recovery configuration states passed');
