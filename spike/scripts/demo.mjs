// 운영자 "업무 시연"을 대신하는 스크립트.
// 실제 현장에서는 운영자가 브라우저로 직접 수행하고, 브라우저 확장/프록시가
// 각 요청에 x-automcp-step 라벨을 붙이며 HAR을 저장한다. 여기서는 Playwright로 같은 효과를 낸다.
//
// 사용: node demo.mjs [baseUrl]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.argv[2] ?? 'http://localhost:8080/jpetstore';
const HAR = new URL('../capture/demo.har', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
mkdirSync(new URL('../capture/', import.meta.url), { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({ recordHar: { path: HAR, content: 'embed' } });
const page = await context.newPage();

async function step(label, fn) {
  await context.setExtraHTTPHeaders({ 'x-automcp-step': label });
  await fn();
  console.log(`✔ ${label}  →  ${page.url()}`);
}

// UC-1 상품 검색
await step('UC-1/search-products', async () => {
  await page.goto(`${BASE}/catalog/`);
  await page.fill('input[name=keyword]', 'fish');
  await page.click('input[name=searchProducts]');
});

// UC-2 상품 상세·가격·재고
await step('UC-2/view-product', async () => {
  await page.click('a[href*="viewProduct?productId=FI-SW-01"]');
});
await step('UC-2/view-item', async () => {
  await page.click('a[href*="viewItem?itemId=EST-1"]');
});

// (주문 내역을 만들기 위한 사전 작업) 로그인 → 장바구니 → 주문
await step('SETUP/signon', async () => {
  await page.goto(`${BASE}/account`);
  await page.click('input[name=signon]'); // 시드 데이터의 테스트 계정이 폼에 기본값으로 채워져 있음
});
await step('SETUP/add-to-cart', async () => {
  await page.goto(`${BASE}/cart/addItem?workingItemId=EST-1`);
});
await step('SETUP/new-order-form', async () => {
  await page.goto(`${BASE}/order/new`);
});
await step('SETUP/submit-order', async () => {
  await page.click('input[name=newOrder]');
});
await step('SETUP/confirm-order', async () => {
  await page.click('input[value=Confirm]');
});

// UC-3 고객 주문 내역 조회
await step('UC-3/list-orders', async () => {
  await page.goto(`${BASE}/order/list`);
});
await step('UC-3/view-order', async () => {
  await page.click('a[href*="order/view?orderId="]');
});

await context.close(); // HAR 저장
await browser.close();
console.log(`HAR saved: ${HAR}`);
