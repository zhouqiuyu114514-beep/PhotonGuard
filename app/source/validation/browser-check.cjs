const { chromium } = require('C:/Users/zhou/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('fs');
const assert = require('assert');
const path = require('path');
const base = 'http://127.0.0.1:8776';
const results = [], errors = [], external = [];
let browser;
async function main() {
  browser = await chromium.launch({headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin !== base) { external.push(route.request().url()); return route.abort(); }
    return route.continue();
  });
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(e.message));
  async function action(selector) {
    const response = page.waitForResponse(r => r.url().endsWith('/action') && r.request().method() === 'POST');
    await page.locator(selector).click();
    const r = await response;
    await page.waitForFunction(() => !document.querySelector('#intake-text')?.disabled);
    return r.json();
  }
  await page.goto(base);
  await page.getByRole('button', {name: '新建需求录入', exact: true}).click();
  await page.locator('#intake-text').waitFor();
  await page.getByRole('button', {name: '填入合成示例（不保存）', exact: true}).click();
  await action('#intake-save');
  const draft = await action('#intake-review');
  assert.equal(draft.intake.result.mode, 'MOCK_RULES_NOT_AI');
  assert.equal(await page.locator('#semantic-intake tbody tr').count(), 14);
  assert(await page.locator('#semantic-intake').innerText().then(t => t.includes('第 9 行') && t.includes('膜层折射率为2。')));
  assert(await page.locator('#intake-confirm').isDisabled());
  await page.locator('#intake-agree').check();
  await action('#intake-confirm');
  await page.reload();
  await page.getByText('已记录人工语义审阅。原生映射仍阻塞，任务未批准、未锁定、未运行。').waitFor();
  const downloadEvent = page.waitForEvent('download');
  await page.locator('#intake-handoff').click();
  const handoffDownload = await downloadEvent;
  await handoffDownload.saveAs(path.join(__dirname, 'manual-mapping-example.json'));
  const handoff = JSON.parse(fs.readFileSync(path.join(__dirname, 'manual-mapping-example.json'), 'utf8'));
  assert.equal(handoff.kind, 'MANUAL_MAPPING_REQUIRED_NOT_A_NATIVE_TASK');
  assert(Object.values(handoff.decisions_to_document).every(v => v === null));
  await page.locator('#intake-native-next').click();
  assert.equal(await page.evaluate(() => document.activeElement.id), 'context-background');
  results.push('confirmed draft has downloadable manual handoff and working native-form navigation');
  results.push('complete mock, 14 source rows, explicit confirmation, reload recovery');
  await page.screenshot({path: path.join(__dirname, 'desktop-review.png'), fullPage: true});

  await page.locator('#intake-text').fill('膜层折射率为2。\n膜层折射率为3。\n<script>window.INJECTED=1</script>');
  assert(await page.locator('#intake-review').isDisabled());
  assert(!(await page.locator('#intake-confirm').isVisible()));
  await action('#intake-save');
  const conflict = await action('#intake-review');
  assert.equal(conflict.intake.result.normalized_response.fields.film_index.status, 'conflict');
  assert.equal(conflict.intake.result.normalized_response.fields.film_index.evidence.length, 2);
  assert(await page.locator('#intake-agree').isDisabled());
  assert.equal(await page.evaluate(() => window.INJECTED), undefined);
  results.push('dirty source invalidation, missing values, both conflict sources, injection inert');
  await page.screenshot({path: path.join(__dirname, 'conflict-review.png'), fullPage: true});

  await action('#intake-cancel');
  assert(await page.locator('#intake-review').isDisabled());
  await page.reload();
  await page.locator('#intake-resume').waitFor();
  await action('#intake-resume');
  assert.equal(await page.locator('#semantic-intake tbody tr').count(), 0);
  results.push('cancel persisted across reload, resume clears old result');

  await page.getByRole('button', {name: '填入合成示例（不保存）', exact: true}).click();
  await action('#intake-save');
  await page.locator('#intake-mode').selectOption('adapter_mock');
  const adapter = await action('#intake-review');
  assert.equal(adapter.intake.result.mode, 'MODEL_ADAPTER_MOCK_TRANSPORT');
  assert.equal(adapter.intake.adapter_audit.audits.length, 2);
  assert.equal(adapter.intake.adapter_audit.tool_calls, 1);
  assert.equal(adapter.intake.model_calls, 0);
  results.push('frontend -> existing DeepSeek transport protocol -> public tool -> continuation, all synthetic');
  const mock = await action('#intake-review');
  await page.locator('#intake-mode').selectOption('offline');
  assert(!(await page.locator('#intake-confirm').isVisible()));
  await page.locator('#intake-response').fill(JSON.stringify(mock.intake.result.normalized_response));
  const offline = await action('#intake-review');
  assert.equal(offline.intake.result.mode, 'OFFLINE_RESPONSE_UNVERIFIED_ORIGIN');
  results.push('existing response import distinct from mock and live, no provenance overclaim');
  await page.locator('#intake-mode').selectOption('offline');
  await page.locator('#intake-response').fill('model failed: service unavailable');
  const failed = await action('#intake-review');
  assert.equal(failed.intake.status, 'FAILED');
  assert.equal(failed.intake.result, null);
  await page.getByText(/旧草稿和确认已失效/).waitFor();
  results.push('failed model response gives actionable error and invalidates old result');

  let delayed = false;
  await page.route('**/action', async route => {
    const body = route.request().postDataJSON();
    if (body.type === 'intake-review') { delayed = true; await new Promise(r => setTimeout(r, 450)); }
    await route.continue();
  });
  const first = page.waitForResponse(r => r.url().endsWith('/action') && r.request().postDataJSON().type === 'intake-review');
  await page.locator('#intake-review').click();
  await page.waitForFunction(() => document.querySelector('#intake-review')?.disabled);
  assert(await page.locator('#intake-review').isDisabled());
  await page.locator('#intake-cancel').click();
  await first;
  await page.locator('#intake-resume').waitFor();
  assert(delayed);
  await page.unroute('**/action');
  results.push('in-flight cancel persists withdrawal; repeated click disabled');

  await action('#intake-resume');
  const caseUrl = page.url();
  const second = await context.newPage(); await second.goto(caseUrl); await second.locator('#intake-review').waitFor();
  await action('#intake-review');
  await second.locator('#intake-review').click();
  await second.getByText('页面版本已变化；请重新读取记录后审阅。未自动重试。').waitFor();
  await second.close(); results.push('two browser tabs reject stale revision');

  await page.locator('#intake-text').fill('膜层折射率为2。\napi_key=FAKE_BROWSER_ONLY_SENTINEL');
  const scrubbed = await action('#intake-save');
  assert(scrubbed.intake.redacted);
  assert(!(await page.locator('#intake-text').inputValue()).includes('FAKE_BROWSER_ONLY_SENTINEL'));
  // Playwright's isDisabled() does not classify OPTION in this bundled version.
  assert(await page.locator('#intake-mode option[value=live]').evaluate(e => e.disabled));
  results.push('synthetic secret redaction visible, live mode unavailable');

  await page.setViewportSize({width: 390, height: 844});
  await page.screenshot({path: path.join(__dirname, 'mobile-intake.png'), fullPage: true});
  const layout = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
  assert(layout.scroll <= layout.width + 1, JSON.stringify(layout));
  results.push('mobile viewport no page-wide horizontal overflow');
  assert.deepEqual(errors, []); assert.deepEqual(external, []);
  const report = {browser: 'User local Microsoft Edge, isolated headless profile', executable: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', url: base, passed: results, page_errors: errors, external_requests: external, model_calls: 0, solver_calls: 0};
  fs.writeFileSync(path.join(__dirname, 'browser-results.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
}
main().catch(async e => { console.error(e); if (browser) await browser.close(); process.exit(1); });
