import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

// TS §6.3 and §8.1 "Stolen web session (XSS)": stored text renders as plain
// text only, and the bsu_ session token stays in memory only. These guards
// catch mistakes; keys hidden behind variables or calls stay with review.
const plainText = "Render API data as plain text (TS §6.3).";
const inMemoryToken = "Keep the session token in memory only (TS §8.1).";
const generatedClient =
  "Call the API only through the generated client in src/api/client.ts.";
const builtKey =
  "Do not build property keys from strings; use a static key (TS §6.3).";

const SRC = "src/**/*.{ts,tsx,mts,cts,js,jsx,mjs,cjs}";
const CLIENT = "src/api/client.ts";

// A static key: a.b, a["b"], or a template literal with no substitutions.
const keyIs = (node, field, re) => [
  `${node}[${field}.name=${re}]`,
  `${node}[${field}.value=${re}]`,
  `${node}[${field}.type='TemplateLiteral'][${field}.expressions.length=0][${field}.quasis.0.value.cooked=${re}]`,
];
const rule = (message, selectors) =>
  selectors.map((selector) => ({ selector, message }));

const STORAGE = "/^(localStorage|sessionStorage|cookieStore|cookie)$/";
const NETWORK = "/^(fetch|XMLHttpRequest)$/";
const DOC_WRITE = "/^(write|writeln)$/";

const htmlAndStorageSinks = [
  ...rule(plainText, [
    "JSXAttribute[name.name='dangerouslySetInnerHTML']",
    ...keyIs("Property", "key", "/^dangerouslySetInnerHTML$/"),
    ...keyIs(
      "AssignmentExpression > MemberExpression.left",
      "property",
      "/^(inner|outer)HTML$/",
    ),
    ...keyIs("MemberExpression", "property", "/^insertAdjacentHTML$/"),
    ...keyIs("MemberExpression[object.name='document']", "property", DOC_WRITE),
    ...keyIs(
      "MemberExpression[object.property.name='document']",
      "property",
      DOC_WRITE,
    ),
    ...keyIs(
      "VariableDeclarator[init.name='document'] > ObjectPattern > Property",
      "key",
      DOC_WRITE,
    ),
  ]),
  ...rule(inMemoryToken, [
    "Identifier[name=/^(localStorage|sessionStorage|cookieStore)$/]",
    ...keyIs("MemberExpression", "property", STORAGE),
    ...keyIs("ObjectPattern > Property", "key", STORAGE),
  ]),
  ...rule(builtKey, [
    "MemberExpression > BinaryExpression.property[operator='+']:has(Literal[raw=/^[\"']/], TemplateLiteral)",
    "MemberExpression > TemplateLiteral.property[expressions.length>0]",
    "ObjectPattern > Property > BinaryExpression.key[operator='+']:has(Literal[raw=/^[\"']/], TemplateLiteral)",
    "ObjectPattern > Property > TemplateLiteral.key[expressions.length>0]",
  ]),
];

const handWrittenHttp = rule(generatedClient, [
  "Identifier[name=/^(fetch|XMLHttpRequest)$/]",
  ...keyIs("MemberExpression", "property", NETWORK),
  ...keyIs("ObjectPattern > Property", "key", NETWORK),
]);

export default defineConfig(
  { ignores: ["node_modules/", "dist/", "coverage/"] },
  {
    linterOptions: {
      noInlineConfig: true,
      reportUnusedDisableDirectives: "error",
    },
  },
  js.configs.recommended,
  tseslint.configs.strict,
  {
    files: [SRC],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
  {
    files: [SRC],
    ignores: [CLIENT],
    rules: {
      "no-restricted-syntax": [
        "error",
        ...htmlAndStorageSinks,
        ...handWrittenHttp,
      ],
    },
  },
  {
    files: [CLIENT],
    rules: {
      "no-restricted-syntax": ["error", ...htmlAndStorageSinks],
    },
  },
);
