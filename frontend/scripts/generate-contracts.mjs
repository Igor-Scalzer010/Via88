import { readFile, writeFile } from "node:fs/promises";
import { jsonSchemaToZod } from "json-schema-to-zod";
const source = JSON.parse(
  await readFile(new URL("../../contracts/schema.json", import.meta.url), "utf8"),
);
// Pydantic emits local $defs references; resolve before deriving validators.
function resolve(node, trail = []) {
  if (Array.isArray(node)) return node.map((value) => resolve(value, trail));
  if (node === null || typeof node !== "object") return node;
  if (node.$ref) {
    if (!node.$ref.startsWith("#/$defs/") || trail.includes(node.$ref))
      throw new Error(`Unsupported schema reference ${node.$ref}`);
    const name = node.$ref.slice(8).replaceAll("~1", "/").replaceAll("~0", "~");
    return resolve(
      {
        ...source.$defs[name],
        ...Object.fromEntries(Object.entries(node).filter(([key]) => key !== "$ref")),
      },
      [...trail, node.$ref],
    );
  }
  const resolved = Object.fromEntries(
    Object.entries(node)
      .filter(([key]) => key !== "$defs")
      .map(([key, value]) => [key, resolve(value, trail)]),
  );
  // Pydantic default factories have no JSON Schema default. Normalize their
  // empty arrays/objects so validated output has the same defaults as Python.
  if (resolved.properties)
    for (const [key, property] of Object.entries(resolved.properties)) {
      if (!(resolved.required ?? []).includes(key) && !("default" in property)) {
        if (property.type === "array") property.default = [];
        if (property.type === "object") property.default = {};
      }
    }
  // Closed discriminator values make these branches exclusive. A Zod union
  // retains their inferred TS variants; generic oneOf emits an untyped refine.
  if (resolved.oneOf && resolved.discriminator) {
    resolved.anyOf = resolved.oneOf;
    delete resolved.oneOf;
    delete resolved.discriminator;
  }
  return resolved;
}
const names = {
  chat_request: "ChatRequest",
  response: "Response",
  dataset: "Dataset",
  session: "Session",
  session_summary: "SessionSummary",
  catalog: "Catalog",
  dashboard: "Dashboard",
  health: "Health",
  stage: "Stage",
  error: "Error",
};
let output =
  '// Generated from Pydantic contracts/schema.json. Run npm run contracts; do not edit.\nimport { z } from "zod";\n';
for (const [key, name] of Object.entries(names)) {
  output += `\nexport const ${name}Schema = ${jsonSchemaToZod(resolve(source.properties[key]), { zodVersion: 3 })};\nexport type ${name} = z.infer<typeof ${name}Schema>;\n`;
}
output +=
  '\nexport type Widget = Dashboard["widgets"][number];\nexport type Filters = NonNullable<ChatRequest["filters"]>;\n';
const target = new URL("../src/lib/contracts.generated.ts", import.meta.url);
if (process.argv.includes("--check")) {
  if ((await readFile(target, "utf8")) !== output)
    throw new Error("Generated contracts have drifted. Run npm run contracts.");
} else await writeFile(target, output);
