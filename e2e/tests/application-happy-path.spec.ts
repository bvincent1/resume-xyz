import { expect, test } from "@playwright/test";

test("adds an application, runs research and tuning, and builds a PDF", async ({
  page,
  context,
}) => {
  await page.goto("/admin/job_applications/application/add/");

  await page.locator(".field-company input").fill("Acme E2E");
  await page.locator(".field-title input").fill("Senior Engineer E2E");

  const description = page.locator(
    'trix-editor[input="wysiwyg-description"]'
  );
  await description.fill("Build deterministic things.");
  await description.blur();
  await expect(page.locator("#wysiwyg-description")).toHaveValue(
    /Build deterministic things\./
  );

  await page
    .locator(".field-provider select")
    .selectOption({ label: "e2e-provider" });

  await page.getByRole("button", { name: /save and continue/i }).click();
  await expect(page.getByText(/was added successfully/i)).toBeVisible();

  const appId = page.url().match(/application\/(\d+)\/change/)?.[1];
  expect(appId).toBeTruthy();
  const changeUrl = `/admin/job_applications/application/${appId}/change/`;

  // Company research: the admin action runs the Celery task inline because
  // settings_e2e puts Celery in eager mode.
  await page.getByRole("link", { name: "Refresh company research" }).click();
  await expect(
    page.getByText("Company research refresh queued.")
  ).toBeVisible();

  await page.goto(changeUrl);
  await page.locator("a", { hasText: "Metadata" }).first().click();
  await expect(page.getByText(/E2E research marker/)).toBeVisible();
  await expect(
    page
      .getByText("Company researched at:")
      .locator("xpath=ancestor::div[contains(@class, 'field-line')]")
  ).toContainText(/\d{4}/);

  // Tuning: the fake agent asserts that the persisted research is passed into
  // PipelineDeps before returning the deterministic resume.
  await page.getByRole("link", { name: "Regenerate prompts" }).click();
  await expect(page.getByText("Prompt regeneration queued.")).toBeVisible();

  await page.goto(changeUrl);
  await page.locator("a", { hasText: "Extra" }).first().click();
  await page.getByRole("link", { name: "tuning", exact: true }).click();

  await expect(page.locator("#id_error")).toHaveValue("");

  const response = JSON.parse(
    await page.locator("#id_response").inputValue()
  ) as { basics: { summary: string } };
  expect(response.basics.summary).toBe("E2E tuned summary");
  await expect(page.locator("#id_description")).toHaveValue(/Acme E2E/);

  // PDF: Build PDF is a target=_blank detail action and builds the PDF
  // synchronously before redirecting. Poll the change form until the saved
  // URL appears, then verify the renderer serves it. Do not parse the PDF.
  await page.goto(changeUrl);
  const popupPromise = context.waitForEvent("page");
  await page.getByRole("link", { name: "Build PDF" }).click();
  const pdfPage = await popupPromise;

  await expect
    .poll(
      async () => {
        await page.goto(changeUrl);
        return page.locator("#id_resume_url").inputValue();
      },
      { timeout: 30_000, intervals: [500, 1_000, 2_000] }
    )
    .toMatch(/\.pdf$/);

  await pdfPage.close();
  await page.locator("a", { hasText: "Metadata" }).first().click();
  const resumeUrl = await page.locator("#id_resume_url").inputValue();
  const pdfResponse = await page.request.get(resumeUrl);
  expect(pdfResponse.status()).toBe(200);
});
