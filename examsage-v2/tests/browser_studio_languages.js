async (page) => {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  await page.getByRole('button', {name: 'Try the spring lesson'}).click();
  await page.waitForFunction(() => document.querySelector('#courseName').textContent.includes('Linear spring'));
  for (const question of ['What is the spring stiffness?', 'What units appear on its source page?']) {
    await page.locator('#question').fill(question);
    await page.locator('#question').press('Control+Enter');
    await page.getByText('The stiffness is 200 N/m.', {exact: true}).last().waitFor();
    await page.waitForFunction(n => document.querySelectorAll('.point-action').length === n,
      question.startsWith('What is') ? 1 : 2);
  }
  await page.locator('.point-action').last().click();
  await page.locator('.source-card').first().click();
  const original = await page.locator('.page-text').innerText();
  assert(original.includes('An ideal Hooke spring') && original.includes('200 N/m'), 'Original passage');
  assert(/page\s*1\b/i.test(await page.locator('.paper-bar').innerText()), 'Original page number');
  await page.getByRole('button', {name: 'Add to course review'}).click();
  await page.locator('#openReview').click();
  await page.locator('.review-row').first().click();
  await page.getByRole('button', {name: 'Reveal source page'}).click();
  assert((await page.locator('.review-source-text').innerText()).includes('200 N/m'), 'Saved source');
  await page.getByRole('button', {name: 'Mark as learned'}).click();
  await page.locator('#closeReview').click();

  await page.locator('#addCourse').click();
  await page.locator('#importName').fill('学生原文 · Field notes');
  await page.locator('#subject').fill('Physics');
  await page.locator('#files').setInputFiles({
    name: 'spring-notes.txt', mimeType: 'text/plain',
    buffer: Buffer.from('对照出处. Hooke spring stiffness is 200 N/m in the linear range.'),
  });
  await page.locator('#confirmImport').click();
  await page.waitForFunction(() => document.querySelector('#courseName').textContent === '学生原文 · Field notes');
  await page.locator('#question').fill('Keep my draft 对照出处');
  await page.locator('#language').selectOption('zh');
  await page.waitForFunction(() => document.documentElement.lang === 'zh-CN' && document.querySelector('#question').value.includes('Keep my draft'));
  await page.locator('#language').selectOption('en');
  await page.waitForFunction(() => document.documentElement.lang === 'en' && document.querySelector('#question').value.includes('Keep my draft'));
  assert(await page.locator('#courseName').innerText() === '学生原文 · Field notes', 'Course name is original');
  await page.locator('#question').fill('What is the stiffness of my spring?');
  await page.locator('#send').click();
  await page.locator('.point-action').first().click();
  await page.locator('.source-card').first().click();
  assert((await page.locator('.page-text').innerText()).includes('对照出处.'), 'Original text survives localisation');

  await page.setViewportSize({width: 390, height: 844});
  if (!(await page.locator('#closeReader').isVisible())) await page.locator('#toggleReader').click();
  await page.locator('#readerBody').waitFor({state: 'visible'});
  await page.locator('#closeReader').click();
  await page.locator('#menu').click();
  assert(await page.locator('#language').isVisible(), 'Mobile language selector');
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal layout overflow');
}
