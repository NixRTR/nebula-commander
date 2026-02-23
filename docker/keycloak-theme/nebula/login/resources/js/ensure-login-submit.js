/**
 * Ensure Sign In button click and Enter key submit the login form.
 * Works around overlay or stacking issues that can block form submit.
 */
(function () {
  function ensureLoginSubmit() {
    var btn = document.getElementById("kc-login");
    if (!btn) return;
    var form = document.getElementById("kc-form-login") || document.querySelector("form[action*='login-actions']") || btn.closest("form");
    if (!form || !form.action) return;

    function doSubmit() {
      if (form && form.action) {
        form.submit();
      }
    }

    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      doSubmit();
      return false;
    });

    form.addEventListener("submit", function (e) {
      if (!e.defaultPrevented) return;
      e.preventDefault();
      doSubmit();
    });

    form.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && e.target.matches("input")) {
        e.preventDefault();
        doSubmit();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureLoginSubmit);
  } else {
    ensureLoginSubmit();
  }
})();
