// jpetstore 업무 시연 시나리오 (녹화기 --scenario 용).
// 실제 현장에서는 운영자가 같은 흐름을 브라우저로 직접 수행한다.
export default async function (page, step, base) {
  // UC-1 상품 검색
  await step('UC-1/search-products', async () => {
    await page.goto(`${base}/catalog/`);
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

  // UC-4 카테고리별 상품 목록
  await step('UC-4/view-category', async () => {
    await page.goto(`${base}/catalog/`);
    await page.click('a[href*="viewCategory?categoryId=DOGS"]');
  });

  // UC-5 주문 생성 (로그인 사용자 위임) — 쓰기 경로
  await step('UC-5/signon', async () => {
    await page.goto(`${base}/account`);
    await page.click('input[name=signon]'); // 시드 데이터의 테스트 계정이 폼 기본값으로 채워져 있음
  });
  await step('UC-5/add-to-cart', async () => {
    await page.goto(`${base}/cart/addItem?workingItemId=EST-1`);
  });
  await step('UC-5/new-order-form', async () => {
    await page.goto(`${base}/order/new`);
  });
  await step('UC-5/submit-order', async () => {
    await page.click('input[name=newOrder]');
  });
  await step('UC-5/confirm-order', async () => {
    await page.click('input[value=Confirm]');
  });

  // UC-3 고객 주문 내역 조회
  await step('UC-3/list-orders', async () => {
    await page.goto(`${base}/order/list`);
  });
  await step('UC-3/view-order', async () => {
    await page.click('a[href*="order/view?orderId="]');
  });
}
