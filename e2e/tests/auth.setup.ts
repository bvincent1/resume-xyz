import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

import { expect, test as setup } from "@playwright/test";

const authFile = ".auth/admin.json";

setup("sign in to the admin", async ({ page }) => {
  await page.goto("/admin/login/?next=/admin/");

  await page.getByLabel(/email/i).fill("e2e@example.com");
  await page.getByLabel(/password/i).fill("e2e-password");
  await page.getByRole("button", { name: /log in/i }).click();

  await expect(page).toHaveURL(/\/admin\/$/);

  mkdirSync(dirname(authFile), { recursive: true });
  await page.context().storageState({ path: authFile });
});
