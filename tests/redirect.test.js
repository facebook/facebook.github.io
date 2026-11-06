"use strict";
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const script = fs.readFileSync("assets/redirect.js", "utf8");

function run({ target = null, projects = null, pathname = "/", search = "", hash = "" }) {
  // The generated 404 embeds structured mappings. String shorthand keeps test
  // cases compact; explicit objects exercise retired-site behavior.
  if (projects) projects = Object.fromEntries(Object.entries(projects).map(([key, value]) => [key,
    typeof value === "string" ? { target_base: value, preserve_path: true } : value]));
  const replacements = [];
  const elements = {
    destination: { href: "/", textContent: "Browse migrated projects" },
    message: { textContent: "Find current documentation" },
  };
  if (projects) elements["redirect-projects"] = { textContent: JSON.stringify(projects) };
  vm.runInNewContext(script, {
    document: {
      body: { getAttribute: () => target },
      getElementById: (id) => elements[id] || null,
    },
    window: { location: { pathname, search, hash, replace: (url) => replacements.push(url) } },
  });
  return { replacements, elements };
}

const projects = { watchman: "https://meta.github.io/watchman/", pathpicker: "https://example.org/docs/" };
let cases = 0;
function check(input, expected) {
  assert.deepStrictEqual(run(input).replacements, expected);
  cases++;
}
check({ target: projects.watchman + "docs/cmd/query", search: "?a=1&b=%2F", hash: "#expr" }, [projects.watchman + "docs/cmd/query?a=1&b=%2F#expr"]);
check({ target: projects.watchman, projects, pathname: "/irrelevant" }, [projects.watchman]);
check({ projects, pathname: "/watchman/docs/new", search: "?x=1", hash: "#part" }, [projects.watchman + "docs/new?x=1#part"]);
check({ projects, pathname: "/watchman" }, [projects.watchman]);
check({ projects, pathname: "/watchman/" }, [projects.watchman]);
check({ projects, pathname: "/PathPicker/guide" }, ["https://example.org/docs/guide"]);
check({ projects, pathname: "/%77atchman/docs/new" }, [projects.watchman + "docs/new"]);
check({ projects, pathname: "/watchman/a%20b/%E2%9C%93" }, [projects.watchman + "a%20b/%E2%9C%93"]);
check({ projects, pathname: "/unknown/guide" }, []);
check({ projects, pathname: "/watchman-other/guide" }, []);
check({ projects, pathname: "/" }, []);
check({ projects, pathname: "/__proto__/guide" }, []);
check({ projects, pathname: "/constructor/guide" }, []);
check({ projects, pathname: "/%invalid/guide" }, []);
check({ pathname: "/watchman/guide" }, []);
check({ projects, pathname: "/watchman//evil.example/path", search: "?redirect=https://evil.example" }, [projects.watchman + "/evil.example/path?redirect=https://evil.example"]);
check({ projects: { flipper: { target_base: "https://github.com/meta/flipper/", preserve_path: false } }, pathname: "/flipper/docs/old", search: "?x=1", hash: "#part" }, ["https://github.com/meta/flipper/?x=1#part"]);
const fallback = run({ projects, pathname: "/watchman/new", search: "?a=1", hash: "#b" });
assert.strictEqual(fallback.elements.destination.href, projects.watchman + "new?a=1#b");
assert.strictEqual(fallback.elements.destination.textContent, "Continue to " + projects.watchman + "new");
assert.strictEqual(fallback.elements.message.textContent, "Redirecting to the project's current documentation.");
console.log(`${cases + 3} JavaScript assertions passed`);
