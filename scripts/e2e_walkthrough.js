// Headless-browser walkthrough of the acceptance test. Usage: node scripts/e2e_walkthrough.js <screenshot-dir> (server on :8000, Playwright installed).
const { chromium } = require('playwright');
const OUT = process.argv[2];
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push('PAGEERROR ' + e.message));
  const shot = async (n) => { await page.waitForTimeout(500); await page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true }); };
  await page.goto('http://localhost:8000/');
  await page.waitForSelector('.login-card'); await shot('01-login');
  const login = async (u) => {
    await page.fill('input[name=username]', u); await page.fill('input[name=password]', 'hdews-demo');
    await page.click('button[type=submit]'); await page.waitForSelector('.rail');
  };
  await login('analyst');
  await page.waitForSelector('.grid-overview'); await shot('02-overview');
  await page.goto('http://localhost:8000/#/map'); await page.waitForSelector('.map-svg .site'); await page.waitForTimeout(400);
  await page.locator('.map-svg .site').nth(4).click({ force: true }); await page.waitForSelector('.drawer .btn-primary'); await shot('03-map');
  await page.goto('http://localhost:8000/#/sites/SNP-05'); await page.waitForSelector('.assess'); await shot('04-site');
  await page.goto('http://localhost:8000/#/simulator?site=SNP-05'); await page.waitForSelector('.preset-list');
  await page.check('input[value=rising_landslide_indicators]');
  await page.click('text=Apply scenario and re-assess'); await page.waitForSelector('.sim-result table'); await shot('05-simulator');
  const alertHref = await page.locator('.sim-result .callout-warn a').first().getAttribute('href');
  console.log('alert link', alertHref);
  // reviewer flow
  await page.click('text=Sign out'); await page.waitForSelector('.login-card');
  await login('reviewer');
  await page.goto('http://localhost:8000/' + alertHref); await page.waitForSelector('.stepper'); await shot('06-alert');
  await page.click('.alert-controls >> text=Acknowledge');
  await page.fill('dialog textarea[name=notes]', 'Reviewing evidence'); await page.click('dialog button[type=submit]');
  await page.waitForSelector('text=Record action');
  await page.click('.alert-controls >> text=Record action');
  await page.fill('dialog input[name=assignee]', 'Field team 2'); await page.fill('dialog textarea[name=notes]', 'Inspect the slope above the road');
  await page.click('dialog button[type=submit]'); await page.waitForTimeout(600);
  await page.click('.alert-controls >> text=Resolve');
  await page.fill('dialog textarea[name=reason]', 'Simulated scenario, demo exercise complete');
  await page.click('dialog button[type=submit]'); await page.waitForSelector('.stepper li.current >> text=Resolved'); await shot('07-alert-resolved');
  await page.goto('http://localhost:8000/#/audit'); await page.waitForSelector('table.audit');
  await page.click('text=Verify hash chain'); await page.waitForSelector('text=Chain intact'); await shot('08-audit');
  // outage scenario as analyst
  await page.click('text=Sign out'); await login('analyst');
  await page.goto('http://localhost:8000/#/simulator?site=SNP-05'); await page.waitForSelector('.preset-list');
  await page.check('input[value=sensor_outage_adverse_weather]'); await page.click('text=Apply scenario and re-assess');
  await page.waitForSelector('.sim-result table');
  await page.goto('http://localhost:8000/#/sites/SNP-05'); await page.waitForSelector('.assess'); await shot('09-site-outage');
  await page.goto('http://localhost:8000/#/evaluation'); await page.waitForSelector('.not-evaluated'); await shot('10-evaluation');
  await page.goto('http://localhost:8000/#/incidents'); await page.waitForSelector('.incident-detail h2'); await shot('11-incidents');
  await page.goto('http://localhost:8000/#/sources'); await page.waitForSelector('.source'); await shot('12-sources');
  await page.goto('http://localhost:8000/#/alerts'); await page.waitForSelector('.page-head'); await shot('13-alerts');
  await page.goto('http://localhost:8000/#/settings'); await page.waitForSelector('textarea.code'); await shot('14-settings');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('http://localhost:8000/#/'); await page.waitForSelector('.grid-overview'); await shot('15-mobile');
  console.log('ERRORS', JSON.stringify(errors));
  await browser.close();
})().catch(e => { console.error('FAIL', e); process.exit(1); });
