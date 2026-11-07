import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: { extend: { colors: { teal: { DEFAULT: "var(--teal)" }, ink: "var(--ink)" } } },
  corePlugins: { preflight: false },
  plugins: [],
};
export default config;
