const {chromium} = require('playwright-core');
const {spawn} = require('node:child_process');
const {createInterface} = require('node:readline');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {once} = require('node:events');
async function main() {
  const [python, kit] = process.argv.slice(2);
  if (!python || !kit) throw Error('Usage: node tests/run_studio_language_check.cjs <python> <extracted-student-kit>');
  const tests = __dirname;
  const host = spawn(python, ['-B', path.join(tests, 'studio_language_fixture.py'), path.resolve(kit), tests], {stdio:['pipe','pipe','inherit']});
  const lines = createInterface({input: host.stdout});
  let browser;
  const timer = setTimeout(() => host.kill(), 100_000);
  try {
    const [url] = await Promise.race([once(lines, 'line'), once(host, 'exit').then(() => {throw Error('Fixture exited before launching');})]);
    browser = await chromium.launch({headless:true,channel:'msedge'});
    const page = await browser.newPage({viewport:{width:1400,height:900}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(url);
    const test = eval('(' + readFileSync(path.join(tests, 'browser_studio_languages.js'), 'utf8') + ')');
    await test(page);
    if (errors.length) throw Error(errors.join('\n'));
    console.log('PASS: extracted student kit, English example, two turns, citation and page, review, mixed-language import and original, draft, mobile.');
  } finally {
    clearTimeout(timer);
    if(browser) await browser.close();
    lines.close();
    host.stdin.end('\n');
  }
}
main().catch(e => {console.error(e.message.replace(/(127\.0\.0\.1:\d+\/en\/#)\S+/g,'$1[private]'));process.exitCode=1;});
