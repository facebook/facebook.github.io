/* Static redirects work without JavaScript; this preserves query strings and
 * fragments and recovers unlisted browser navigations on the custom 404 page. */
(function () {
  "use strict";

  var target = document.body.getAttribute("data-redirect-target");
  var projectsElement = document.getElementById("redirect-projects");
  if (!target && projectsElement) {
    var projects = JSON.parse(projectsElement.textContent);
    var pathname = window.location.pathname;
    var separator = pathname.indexOf("/", 1);
    var prefix = pathname.slice(1, separator < 0 ? undefined : separator);
    try {
      prefix = decodeURIComponent(prefix).toLowerCase();
    } catch (_) {
      return;
    }
    // Only explicitly inventoried projects are redirected. Never accept a
    // target from URL parameters, and do not redirect unrelated missing pages.
    if (!Object.prototype.hasOwnProperty.call(projects, prefix)) {
      return;
    }
    var remainder = separator < 0 ? "" : pathname.slice(separator + 1);
    // Concatenation to a validated absolute base deliberately avoids urljoin's
    // protocol-relative URL behavior for paths beginning with //.
    var mapping = projects[prefix];
    target = mapping.target_base + (mapping.preserve_path ? remainder : "");
    var link = document.getElementById("destination");
    link.href = target + window.location.search + window.location.hash;
    link.textContent = "Continue to " + target;
    document.getElementById("message").textContent =
      "Redirecting to the project's current documentation.";
  }
  if (target) {
    window.location.replace(target + window.location.search + window.location.hash);
  }
})();
