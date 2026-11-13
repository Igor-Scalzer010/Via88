// @vitest-environment node
import { spawnSync } from "node:child_process";
import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const frontendRoot = fileURLToPath(new URL("../../", import.meta.url));
// Keep isolated checkouts under node_modules so the real CLI resolves its dependency.
const fixtureParent = join(frontendRoot, "node_modules", ".cache");
let fixtureRoot: string;
let scriptPath: string;
let schemaPath: string;
let targetPath: string;

function runGenerator(...args: string[]) {
  const result = spawnSync(process.execPath, [scriptPath, ...args], { encoding: "utf8" });
  if (result.error) throw result.error;
  return result;
}

beforeEach(async () => {
  await mkdir(fixtureParent, { recursive: true });
  fixtureRoot = await mkdtemp(join(fixtureParent, "via-contracts-"));
  scriptPath = join(fixtureRoot, "frontend", "scripts", "generate-contracts.mjs");
  schemaPath = join(fixtureRoot, "contracts", "schema.json");
  targetPath = join(fixtureRoot, "frontend", "src", "lib", "contracts.generated.ts");
  for (const path of [scriptPath, schemaPath, targetPath])
    await mkdir(dirname(path), { recursive: true });
  await copyFile(join(frontendRoot, "scripts", "generate-contracts.mjs"), scriptPath);
  await copyFile(join(frontendRoot, "..", "contracts", "schema.json"), schemaPath);
  const generated = runGenerator();
  expect(generated.stderr).toBe("");
  expect(generated.status).toBe(0);
});

afterEach(async () => {
  if (fixtureRoot && dirname(fixtureRoot) === fixtureParent)
    await rm(fixtureRoot, { recursive: true, force: true });
});

describe("contract generator CLI", () => {
  it("writes generated validators with LF line endings", async () => {
    const content = await readFile(targetPath, "utf8");
    expect(content).toContain("\n");
    expect(content).not.toContain("\r");
  });

  it.each([
    ["LF", "\n"],
    ["CRLF", "\r\n"],
  ])("accepts a matching %s checkout without rewriting it", async (_name, newline) => {
    const checkedOut = (await readFile(targetPath, "utf8")).replaceAll("\n", newline);
    await writeFile(targetPath, checkedOut);
    const checked = runGenerator("--check");
    expect(checked.stderr).toBe("");
    expect(checked.status).toBe(0);
    expect(await readFile(targetPath, "utf8")).toBe(checkedOut);
  });

  it.each([
    ["LF", "\n"],
    ["CRLF", "\r\n"],
  ])("rejects real schema drift in a %s checkout", async (_name, newline) => {
    const checkedOut = (await readFile(targetPath, "utf8")).replaceAll("\n", newline);
    await writeFile(targetPath, checkedOut);
    const schema = JSON.parse(await readFile(schemaPath, "utf8"));
    schema.$defs.ChatRequest.properties.message.maxLength = 42;
    await writeFile(schemaPath, JSON.stringify(schema));
    const checked = runGenerator("--check");
    expect(checked.status).not.toBe(0);
    expect(checked.stderr).toContain("Generated contracts have drifted");
    expect(await readFile(targetPath, "utf8")).toBe(checkedOut);
  });
});
