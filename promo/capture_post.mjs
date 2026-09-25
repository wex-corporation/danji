import { chromium } from 'playwright';
import fs from 'fs';
const D = process.argv[2];
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--headless=new'] });
const ctx = await b.newContext({ proxy: { server: process.env.HTTPS_PROXY }, viewport: { width: 360, height: 1000 }, deviceScaleFactor: 4, locale: 'ko-KR' });
await ctx.route('**/*', async r => { try { const resp = await r.fetch(); await r.fulfill({ response: resp }); } catch (e) { await r.abort(); } });
const p = await ctx.newPage();
await p.goto('https://danji.life/c/eunma/p/1126', { waitUntil: 'networkidle', timeout: 60000 });
await p.waitForTimeout(2000);
await p.screenshot({ path: `${D}/post_tall.png` });
const boxes = await p.evaluate(() => {
  const rects = (needle) => {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n; const out = [];
    while ((n = w.nextNode())) { const i = n.data.indexOf(needle); if (i >= 0) { const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + needle.length); out.push([...r.getClientRects()].map(c => ({ x: c.x, y: c.y, w: c.width, h: c.height }))); } }
    return out;
  };
  return {
    badge: rects('출처 확인'), title: rects('일반관리 35'), agent: rects('AGENT').concat(rects('agent')), author: rects('은마설계노트'),
    stop: rects('그건 표가 아니라 현장이 답할 문제입니다.'), question: rects('단지에서 하루에 마주치는 관리 인력은 몇 분이나 되시나요?'),
    basis: rects('확인 기준'),
  };
});
fs.writeFileSync(`${D}/boxes_post.json`, JSON.stringify(boxes, null, 1));
console.log(JSON.stringify(boxes));
await b.close();
