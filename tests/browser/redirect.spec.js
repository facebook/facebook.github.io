const { test, expect } = require("@playwright/test");
const fs = require("fs");
const { projects } = JSON.parse(fs.readFileSync("sites.json", "utf8"));
const watchman = projects.find((project) => project.prefix === "watchman");

async function captureDestination(page) {
  await page.route(/^https:\/\//, (route) => route.fulfill({
    contentType: "text/html",
    body: "<!doctype html><title>Destination</title><h1>Destination</h1>",
  }));
}

for (const path of ["/watchman/docs/cmd/query", "/watchman/docs/cmd/query/", "/watchman/docs/cmd/query.html"]) {
  test(`known redirect preserves query and fragment: ${path}`, async ({ page }) => {
    await captureDestination(page);
    await page.goto(path + "?q=a%20b&x=1#expression");
    await expect(page).toHaveURL(watchman.target_base + "docs/cmd/query?q=a%20b&x=1#expression");
  });
}

test("static HTML meta refresh works with JavaScript disabled", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await captureDestination(page);
  await page.goto("http://127.0.0.1:8765/watchman/docs/cmd/query");
  await expect(page).toHaveURL(watchman.target_base + "docs/cmd/query");
  await context.close();
});

test("custom 404 recovers unknown deep paths", async ({ page }) => {
  await captureDestination(page);
  await page.goto("/watchman/docs/not-yet-in-sitemap?q=1#section");
  await expect(page).toHaveURL(watchman.target_base + "docs/not-yet-in-sitemap?q=1#section");
});

test("unknown projects remain genuine 404s", async ({ page }) => {
  const response = await page.goto("/not-a-migrated-project/guide?redirect=https://evil.example/");
  expect(response.status()).toBe(404);
  await expect(page).toHaveURL(/127\.0\.0\.1:8765\/not-a-migrated-project\//);
  await expect(page.getByRole("link", { name: "Browse migrated projects", exact: true }).first()).toBeVisible();
});

test("custom-domain projects drop the old repository prefix", async ({ page }) => {
  const custom = projects.find((project) => new URL(project.target_base).hostname !== "meta.github.io");
  test.skip(!custom, "No custom-domain project in this configuration");
  await captureDestination(page);
  await page.goto(`/${custom.prefix}/unlisted-test-page?x=1#section`);
  await expect(page).toHaveURL(custom.target_base + "unlisted-test-page?x=1#section");
});

test("retired Flipper pages go to the repository root", async ({ page }) => {
  const retired = projects.find((project) => project.prefix === "flipper");
  await captureDestination(page);
  await page.goto("/flipper/docs/old-page?q=1#section");
  await expect(page).toHaveURL(retired.target_base + "?q=1#section");
});

for (const [prefix, route] of [["docusaurus", "docs/installation"], ["lexical", "docs/intro"]]) {
  test(`${prefix} uses the canonical custom domain, not the root-only Pages stub`, async ({ page }) => {
    const project = projects.find((candidate) => candidate.prefix === prefix);
    await captureDestination(page);
    await page.goto(`/${prefix}/${route}?q=1#section`);
    await expect(page).toHaveURL(project.target_base + route + "?q=1#section");
  });
}

test("site root is a usable project directory", async ({ page }) => {
  const response = await page.goto("/");
  expect(response.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Meta open source documentation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "watchman", exact: true })).toHaveAttribute("href", watchman.target_base);
});
