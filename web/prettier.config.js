/** @type {import("prettier").Config} */
export default {
  semi: false,
  singleQuote: false,
  trailingComma: "all",
  printWidth: 100,
  tabWidth: 2,
  useTabs: false,
  plugins: ["prettier-plugin-tailwindcss"],
  // Required for Tailwind v4: without it the plugin can't see the theme, so
  // custom classes/variants (font-heading, sidebar utilities) sort as unknowns.
  tailwindStylesheet: "./src/index.css",
}
