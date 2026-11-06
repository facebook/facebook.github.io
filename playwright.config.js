const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "tests/browser",
  fullyParallel: true,
  retries: 0,
  use: { browserName: "chromium", baseURL: "http://127.0.0.1:8765" },
  webServer: {
    command: "python3 scripts/build.py && python3 scripts/serve.py",
    url: "http://127.0.0.1:8765/",
    reuseExistingServer: false,
  },
});
