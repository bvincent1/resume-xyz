import { argv } from "process";
import puppeteer from "puppeteer";

(async () => {
  // Launch the browser and open a new blank page
  const browser = await puppeteer.launch({
    headless: false,
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1080, height: 1024 });

  // "https://www.linkedin.com/jobs/search/?keywords=Full%20Stack%20Engineer&location=Canada&geoId=101174742&f_TPR=r86400&f_WT=2&position=1&pageNum=0",

  // Navigate the page to a URL
  await page.goto(argv.slice(-1));

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

  await browser.close();
  console.log(jobs);
})();
