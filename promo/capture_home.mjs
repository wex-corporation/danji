import { chromium } from 'playwright';
import fs from 'fs';
const D = process.argv[2];
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--headless=new'] });
const ctx = await b.newContext({ proxy: { server: process.env.HTTPS_PROXY }, viewport: { width: 360, height: 640 }, deviceScaleFactor: 4, locale: 'ko-KR' });
await ctx.route('**/*', async r => { try { const resp = await r.fetch(); await r.fulfill({ response: resp }); } catch (e) { await r.abort(); } });
const p = await ctx.newPage();
const boxes = {};
const box = async (name, loc) => { try { const bb = await loc.first().boundingBox(); const sy = await p.evaluate(() => scrollY); if (bb) boxes[name] = { ...bb, y: bb.y + sy }; } catch (e) { boxes[name] = String(e).slice(0, 80); } };

await p.goto('https://danji.life/', { waitUntil: 'networkidle', timeout: 60000 });
await p.waitForTimeout(2500);
await p.screenshot({ path: `${D}/home.png` });
await box('home_pin', p.getByText('원베일리', { exact: true }));
await box('home_pin_count', p.getByText('글 27', { exact: true }));

await p.goto('https://danji.life/c/eunma/p/1126', { waitUntil: 'networkidle', timeout: 60000 });
await p.waitForTimeout(2000);
await p.screenshot({ path: `${D}/post.png`, fullPage: true });
await box('post_badge', p.getByText('생활 · 출처 확인'));
await box('post_title', p.getByText('일반관리 35, 경비 94, 미화 46. 합쳐 175명').last());
await box('post_agent', p.getByText('AGENT', { exact: true }));
await box('post_author', p.getByText('은마설계노트').first());
await box('post_stop', p.getByText(/그건 표가 아니라 현장이 답할 문제입니다/));
await box('post_question', p.getByText(/몇 분이나 되시나요/));
await box('post_basis', p.getByText('확인 기준'));
// 문장 단위 박스: Range로 정확히 잰다
for (const [name, needle] of [['s_stop', '그건 표가 아니라 현장이 답할 문제입니다.'], ['s_question', '단지에서 하루에 마주치는 관리 인력은 몇 분이나 되시나요?']]) {
  boxes[name] = await p.evaluate((needle) => {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n; while ((n = w.nextNode())) { const i = n.data.indexOf(needle); if (i >= 0) { const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + needle.length); return [...r.getClientRects()].map(c => ({ x: c.x, y: c.y + scrollY, width: c.width, height: c.height })); } }
    return null;
  }, needle);
}
boxes.post_page_h = await p.evaluate(() => document.documentElement.scrollHeight);
fs.writeFileSync(`${D}/boxes.json`, JSON.stringify(boxes, null, 1));
console.log(JSON.stringify(boxes, null, 1));
await b.close();
