// automcp 녹화기: 운영자의 업무 시연을 HAR로 녹화하고, 각 요청에 단계 라벨(x-automcp-step)을 붙인다.
// 서버 측 OTel 에이전트가 같은 라벨을 트레이스에 남기므로 화면 ↔ URL ↔ SQL이 자동으로 연결된다.
//
// 대화형(현장 운영자용):
//   node record.mjs --base-url http://dev-was:8080/app --out ../workspace/capture/raw
//   → 브라우저가 열리면 터미널에 단계 이름(예: UC-1/search)을 입력하고 브라우저에서 해당 업무를 수행한다.
//     다음 단계로 넘어갈 때마다 새 이름을 입력하고, 끝나면 q 를 입력한다.
//
// 시나리오(자동 재현·회귀용):
//   node record.mjs --base-url http://localhost:8080/jpetstore --out DIR --scenario ../examples/jpetstore/scenario.mjs
//   시나리오 모듈은 `export default async function (page, step, base) { await step('UC-1/x', async () => {...}) }`
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import readline from 'node:readline/promises';

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) args[argv[i].slice(2)] = argv[i + 1]?.startsWith('--') ? true : argv[++i];
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
if (!args['base-url'] || !args.out) {
  console.error('사용: node record.mjs --base-url URL --out DIR [--scenario FILE] [--headless]');
  process.exit(2);
}
const base = args['base-url'].replace(/\/$/, '');
const outDir = resolve(args.out);
mkdirSync(outDir, { recursive: true });
const harPath = resolve(outDir, 'demo.raw.har');

const browser = await chromium.launch({ headless: Boolean(args.scenario) || Boolean(args.headless) });
const context = await browser.newContext({ recordHar: { path: harPath, content: 'embed' } });
const page = await context.newPage();
const steps = [];

async function setStep(label) {
  await context.setExtraHTTPHeaders({ 'x-automcp-step': label });
  steps.push({ label, at: new Date().toISOString() });
}

if (args.scenario) {
  const scenario = (await import(pathToFileURL(resolve(args.scenario)).href)).default;
  await scenario(page, async (label, fn) => {
    await setStep(label);
    await fn();
    console.log(`✔ ${label}  →  ${page.url()}`);
  }, base);
} else {
  await page.goto(base);
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  console.log('브라우저에서 업무를 시연하세요. 단계가 바뀔 때마다 단계 이름을 입력합니다(q: 종료).');
  for (;;) {
    const label = (await rl.question('단계 이름> ')).trim();
    if (label === 'q' || label === '') break;
    await setStep(label);
    console.log(`  ● 지금부터의 요청은 [${label}] 로 기록됩니다.`);
  }
  rl.close();
}

await context.close(); // HAR 저장
await browser.close();
console.log(`HAR: ${harPath}  (단계 ${steps.length}개)`);
console.log('다음: automcp sanitize-har 로 정제한 뒤 원본은 고객 내부망 밖으로 반출하지 마세요.');
