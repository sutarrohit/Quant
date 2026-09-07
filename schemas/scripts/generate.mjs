#!/usr/bin/env node
// Two-generator codegen step for schemas/strategy-spec.v1.json (D-06, FOUND-04).
//
// `build` regenerates both languages from the one schema:
//   - TypeScript -> schemas/generated/ts/strategy-spec.d.ts (json-schema-to-typescript)
//   - Pydantic v2 -> engine/generated/strategy_spec.py (datamodel-code-generator, run inside
//     the engine's own uv environment -- this script never assumes a global Python install)
//
// `--check` regenerates into a scratch temp directory and diffs against whatever is currently
// on disk at those same two paths, so a schema edit with no matching regeneration is caught
// before it drifts silently. Both output directories are gitignored (plan 01-01) -- neither is
// ever a committed artifact.
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SCHEMAS_ROOT = join(__dirname, "..");
const REPO_ROOT = join(SCHEMAS_ROOT, "..");
const SCHEMA_PATH = join(SCHEMAS_ROOT, "strategy-spec.v1.json");
const ENGINE_PROJECT_DIR = join(REPO_ROOT, "engine");

const CHECK_MODE = process.argv.includes("--check");

async function generateTs(outDir) {
  const schema = JSON.parse(readFileSync(SCHEMA_PATH, "utf8"));
  const ts = await compile(schema, "StrategySpec", { bannerComment: undefined });
  const outFile = join(outDir, "ts", "strategy-spec.d.ts");
  mkdirSync(dirname(outFile), { recursive: true });
  writeFileSync(outFile, ts);
  return outFile;
}

function generatePydantic(outDir) {
  mkdirSync(outDir, { recursive: true });
  const outFile = join(outDir, "strategy_spec.py");
  execFileSync(
    "uv",
    [
      "run",
      "--project",
      ENGINE_PROJECT_DIR,
      "datamodel-codegen",
      "--input",
      SCHEMA_PATH,
      "--input-file-type",
      "jsonschema",
      "--output",
      outFile,
      "--output-model-type",
      "pydantic_v2.BaseModel",
      "--class-name",
      "StrategySpec",
      "--disable-timestamp",
    ],
    { stdio: "inherit" },
  );
  // The generated module must be importable -- engine/generated has no other __init__.py writer.
  writeFileSync(join(outDir, "__init__.py"), "");
  return outFile;
}

async function build() {
  await generateTs(join(SCHEMAS_ROOT, "generated"));
  generatePydantic(join(ENGINE_PROJECT_DIR, "generated"));
}

async function check() {
  const tmp = mkdtempSync(join(tmpdir(), "schemas-check-"));
  try {
    const freshTs = await generateTs(tmp);
    const freshPyDir = join(tmp, "engine-generated");
    generatePydantic(freshPyDir);

    const committedTs = join(SCHEMAS_ROOT, "generated", "ts", "strategy-spec.d.ts");
    const committedPy = join(ENGINE_PROJECT_DIR, "generated", "strategy_spec.py");

    let drifted = false;
    for (const [fresh, committed, label] of [
      [freshTs, committedTs, "TypeScript"],
      [join(freshPyDir, "strategy_spec.py"), committedPy, "Pydantic"],
    ]) {
      if (!existsSync(committed)) {
        console.error(
          `[schemas check] ${label} output missing at ${committed} -- run 'pnpm --filter @repo/schemas run build' first`,
        );
        drifted = true;
        continue;
      }
      if (readFileSync(fresh, "utf8") !== readFileSync(committed, "utf8")) {
        console.error(`[schemas check] ${label} output has drifted from the schema -- regenerate`);
        drifted = true;
      }
    }
    if (drifted) {
      process.exitCode = 1;
      return;
    }
    console.log("[schemas check] generated output matches the schema");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

if (CHECK_MODE) {
  await check();
} else {
  await build();
}
