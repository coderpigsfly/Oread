// Oread's pages are pinned to ECMAScript 2020, so every target browser
// (Chrome, Edge, Firefox, Safari 14+, Chrome on Android) runs them as written.
// This refuses newer syntax (the parser) and newer built-ins (es-x).
const esx = require("eslint-plugin-es-x");

module.exports = [
  { ignores: ["oread/web/vendor/**"] },
  {
    files: ["oread/web/**/*.js"],
    plugins: { "es-x": esx },
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: "module",
      globals: {
        window: "readonly", document: "readonly", location: "readonly", localStorage: "readonly",
        fetch: "readonly", Node: "readonly", console: "readonly", navigator: "readonly",
        AudioWorkletNode: "readonly", Float32Array: "readonly", Int16Array: "readonly",
        Audio: "readonly", Event: "readonly", URLSearchParams: "readonly", history: "readonly", setTimeout: "readonly", clearTimeout: "readonly",
        MutationObserver: "readonly", Blob: "readonly", URL: "readonly", Intl: "readonly",
      },
    },
    rules: {
      ...esx.configs["flat/restrict-to-es2020"].rules,
      "no-undef": "error",
      "no-unused-vars": ["error", { caughtErrors: "none" }],
    },
  },
  {
    files: ["oread/web/recorder.js"],
    languageOptions: { sourceType: "script",
      globals: { AudioWorkletProcessor: "readonly", registerProcessor: "readonly" } },
  },
  {
    files: ["oread/web/theme.js"],
    languageOptions: { sourceType: "script" },
  },
];
