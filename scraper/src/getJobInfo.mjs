import puppeteer from "puppeteer";
import { argv } from "process";

(async () => {
  // Launch the browser and open a new blank page
  const browser = await puppeteer.launch({
    headless: false,
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1080, height: 1024 });

  const urls = argv.slice(-1).split(",");
  for (const url of urls) {
    await page.goto(url);
    // Wait and click on first result
    const title = await page.title();
    console.log(title);
    try {
      const modalSelector = ".modal__dismiss";
      await page.locator(modalSelector).click(modalSelector);
    } catch {}

    const jobs = await page.evaluate(() => {
      return Array.from(document.querySelectorAll(".base-card__full-link")).map((el) => el.href);
    });
  }

  await browser.close();
  console.log(jobs);

  // Navigate the page to a URL
})();
