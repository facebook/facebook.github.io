# facebook.github.io redirects

An organization-level GitHub Pages site that restores links to documentation
previously hosted on `facebook.github.io`. Known pages redirect to their current
canonical URLs on `meta.github.io` or a project's custom domain.

## Behavior

- `sites.json` records project prefixes, canonical destination roots, and known
  page routes. The build is deterministic and does not fetch remote content.
- Known routes serve real HTML files with an immediate meta refresh, a canonical
  link, and a visible destination link. They return **HTTP 200**, not a custom
  404. JavaScript preserves the original query string and fragment.
- Both extensionless and trailing-slash variants are generated. GitHub Pages
  resolves an extensionless request to the corresponding `.html` file.
- Unknown deep paths under known projects use `404.html` to redirect browser
  navigations to the corresponding destination, preserving the path, query, and
  fragment. Unknown project prefixes remain 404s.
- The domain root lists migrated projects rather than redirecting to a potentially
  nonexistent `meta.github.io` root.
- Targets are explicitly configured; URL parameters never select a destination.
  Custom domains are supported without carrying the old repository prefix over.
  A retired site can set `preserve_path: false` to send all old paths to its
  replacement landing page. Flipper uses this because its upstream documentation
  site already redirects all paths to the GitHub repository.

`inventory-summary.json` records the public inventory snapshot, source, coverage,
and known limitations. A site with only a verified root still gets a root
redirect and the browser safety net, not a claim of complete SEO coverage.

GitHub Pages does not offer configurable HTTP 301/308 redirects. Google treats
immediate meta refresh as a permanent redirect, but ignores HTTP 404 response
content. The custom 404 is therefore **a browser safety net, not the SEO migration**.
Without JavaScript, listed pages still redirect, but query strings and fragments
are not preserved. Redirect HTML cannot restore image, CSS, JavaScript, or other
asset fetches that expect the original resource instead of an HTML document.

## Build and test

Python 3.12+ and Node.js 22+ are sufficient for unit tests. Only the real-browser
regression suite has third-party development dependencies.

```sh
python3 -m unittest discover -s tests -v
node tests/redirect.test.js
python3 scripts/build.py
python3 scripts/serve.py
```

The local server approximates Pages' `.html`, directory-index, and custom-404
resolution. It is not a substitute for the live deployment checks below.

```sh
npm ci
npx playwright install --with-deps chromium
npm run test:browser
```

Browser tests intercept destination requests locally. They do not write to or
exercise destination services. The generator refuses to overwrite an arbitrary
nonempty output directory; only directories it previously generated are replaced.

## Configuration and refresh

Each project has a legacy `prefix`, an HTTPS `target_base` ending in `/`, and
relative page `routes`. For example:

```json
{
  "prefix": "watchman",
  "target_base": "https://meta.github.io/watchman/",
  "routes": ["", "docs/cmd/query"]
}
```

Keep the legacy prefix even if a project changes its repository name. Update the
target root independently. Include a known route for any legacy path not present
in a new site's sitemap. Empty string represents the project root. Non-HTML
resources are not routes. Optional `sitemaps` lists the public sitemap sources.
`excluded_routes` can record confirmed missing destination pages so a refresh
will not reintroduce stale sitemap entries. Remove an exclusion after verifying
that the destination has been restored.

```sh
# Preview refreshed configuration without changing a file:
python3 -m scripts.refresh
# Refresh explicitly; all downloads and a validation build must succeed:
python3 -m scripts.refresh --write
```

Refresh preserves manually recorded old routes, follows bounded sitemap indexes,
and accepts only the configured canonical site or that project's known legacy
organization URLs. Downloads and expanded gzip data are size-limited. Failed
refreshes do not change the configuration. Review the resulting diff and run the
tests before publication; there is no unattended remote-content refresh.

## Deploy

The repository must be **`facebook/facebook.github.io`**. `.github` is not the
special organization-level Pages repository. Do not create repositories such as
`facebook/watchman` to restore individual sites: they can override GitHub's
existing repository redirects to `meta/watchman`.

1. Create this repository in the replacement `facebook` organization. Publish
   the source on `main`. Do not replace an existing repository without checking
   its ownership and contents first.
2. In **Settings → Pages**, select **GitHub Actions** as the publishing source
   (REST equivalent: `POST /repos/facebook/facebook.github.io/pages` with
   `build_type: "workflow"`). Do not set a custom domain or add a `CNAME` file.
3. Run **Test and deploy redirects**, or push to `main`. Tests must pass before
   the deployment job runs. The workflow uses immutable action revisions and
   grants Pages write/OIDC permission only to the deployment job.
4. Verify the exact reported Watchman URL and representative other projects:

```sh
curl -i https://facebook.github.io/watchman/docs/cmd/query
curl -i https://facebook.github.io/watchman/docs/cmd/query/
curl -i https://facebook.github.io/watchman/docs/not-in-sitemap
```

The first two must return 200 with a meta refresh and canonical link to
`https://meta.github.io/watchman/docs/cmd/query`. The third remains HTTP 404 but
must redirect a JavaScript-enabled browser. Check query and fragment preservation
in a browser, a custom-domain project, and unknown project prefixes. Never claim
live verification based on the local server alone.

## References

- [Organization Pages repository naming](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)
- [Custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Custom 404 pages](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-custom-404-page-for-your-github-pages-site)
- [Google's redirect interpretation](https://developers.google.com/search/docs/crawling-indexing/301-redirects)
- [Google's HTTP status handling](https://developers.google.com/search/docs/crawling-indexing/http-network-errors)
