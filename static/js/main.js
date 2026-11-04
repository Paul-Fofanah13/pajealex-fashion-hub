// Pajealex Fashion Hub - small interactive helpers (no libraries needed)
(function () {
  "use strict";

  // Mobile menu
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    });
  }

  // Categories dropdown (click for touch screens, hover works via CSS)
  document.querySelectorAll(".dropdown-btn").forEach(function (btn) {
    btn.addEventListener("click", function (event) {
      event.stopPropagation();
      var box = btn.parentElement;
      var open = box.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });
  document.addEventListener("click", function () {
    document.querySelectorAll(".dropdown.open").forEach(function (box) { box.classList.remove("open"); });
  });

  // Dismiss messages, and fade the success ones after a few seconds
  document.querySelectorAll(".flash").forEach(function (flash) {
    var close = flash.querySelector(".flash-close");
    if (close) { close.addEventListener("click", function () { flash.remove(); }); }
    if (flash.classList.contains("flash-success")) {
      setTimeout(function () { flash.remove(); }, 6000);
    }
  });

  // Loading state on forms: stops double clicks and shows a spinner
  document.querySelectorAll("form.js-loading").forEach(function (form) {
    form.addEventListener("submit", function () {
      var button = form.querySelector("button[type=submit]");
      if (button) { button.classList.add("is-loading"); }
    });
  });
  // If the browser restores the page with the back button, reset spinners
  window.addEventListener("pageshow", function () {
    document.querySelectorAll(".btn.is-loading").forEach(function (b) { b.classList.remove("is-loading"); });
  });

  // Keep quantity inputs inside their allowed range
  document.querySelectorAll("input[type=number][max]").forEach(function (input) {
    input.addEventListener("change", function () {
      var min = parseInt(input.min || "1", 10), max = parseInt(input.max, 10), value = parseInt(input.value, 10);
      if (isNaN(value) || value < min) { input.value = min; }
      else if (value > max) { input.value = max; }
    });
  });
})();
