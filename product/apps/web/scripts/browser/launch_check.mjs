import puppeteer from 'puppeteer-core';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
try {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox','--disable-setuid-sandbox','--disable-gpu','--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  await page.setContent('<h1>launch-ok</h1>');
  const title = await page.evaluate(() => document.querySelector('h1').textContent);
  console.log('LAUNCH_OK', title);
  await browser.close();
} catch (e) {
  console.log('LAUNCH_FAIL', e.message);
  process.exit(1);
}
