// Builds two separate bundles:
//   dist/extension.js  -- the extension host (Node context, `vscode` external)
//   dist/webview.js/.css -- the React chat UI (browser context, bundled with React)
// These run in fundamentally different environments (Node vs. a webview's
// sandboxed browser context) so they cannot share one esbuild config.
const esbuild = require("esbuild");

const watch = process.argv.includes("--watch");

const watchLogPlugin = (label) => ({
  name: "watch-log",
  setup(build) {
    build.onStart(() => console.log(`[watch:${label}] build started`));
    build.onEnd((result) => {
      for (const { text, location } of result.errors) {
        console.error(`> ${location ? `${location.file}:${location.line}:${location.column}: ` : ""}error: ${text}`);
      }
      console.log(`[watch:${label}] build finished`);
    });
  },
});

const hostOptions = {
  entryPoints: ["src/extension.ts"],
  bundle: true,
  outfile: "dist/extension.js",
  external: ["vscode"],
  format: "cjs",
  platform: "node",
  sourcemap: true,
  plugins: watch ? [watchLogPlugin("host")] : [],
};

const webviewOptions = {
  entryPoints: ["webview/src/main.tsx"],
  bundle: true,
  outfile: "dist/webview.js",
  format: "iife",
  platform: "browser",
  sourcemap: true,
  jsx: "automatic",
  loader: { ".css": "css" },
  plugins: watch ? [watchLogPlugin("webview")] : [],
};

async function main() {
  if (watch) {
    const hostCtx = await esbuild.context(hostOptions);
    const webviewCtx = await esbuild.context(webviewOptions);
    await Promise.all([hostCtx.watch(), webviewCtx.watch()]);
  } else {
    await Promise.all([esbuild.build(hostOptions), esbuild.build(webviewOptions)]);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
