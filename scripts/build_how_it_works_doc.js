// Builds docs/HOW_IT_WORKS.md from the same step data the app's How it works page shows, so the two never drift apart.
//   node scripts/build_how_it_works_doc.js
const fs = require("fs");
const path = require("path");
const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "frontend", "how.html"), "utf8");

function grab(name) {
  const m = html.match(new RegExp("const " + name + "=\\[([\\s\\S]*?)\\];\\r?\\n"));
  if (!m) throw new Error("not found: " + name);
  return eval("[" + m[1] + "]");
}
const off = grab("OFF_STEPS"), on = grab("ON_STEPS"), up = grab("UP_STEPS"), cmp = grab("CMP");
const steps = (a) => a.map((x, i) => `${i + 1}. **${x[0]}.** ${x[1]} (\`${x[2]}\`)`).join("\n");

const md = `# How Cognify answers: without and with memory

The same question takes two real paths through the code. This page is generated from the same data as the *How it works* page of the app (\`/how-it-works#steps\`), where both paths can also be run live.

## Memory OFF: a normal AI model

${steps(off)}

## Memory ON: the company's own experience

${steps(on)}

## Side by side

| | Memory OFF | Memory ON |
| --- | --- | --- |
${cmp.map((r) => "| " + r.join(" | ") + " |").join("\n")}

## When you upload a file

${steps(up)}

## A real example

Question: *Why does a Daikin VRV unit keep tripping with an E3 error?*

- **Memory OFF** answers with a generic list: low refrigerant charge, dirty filters, a faulty pressure sensor, compressor overload, and a reset-and-clean checklist. Reasonable, but it does not know this fleet.
- **Memory ON** answers that the compressor contactor is the most common cause here (scorched coil, pitted contacts), that low supply voltage under about 200 V triggers the trip, to measure the supply under load before touching the compressor, and not to replace the compressor relay board first, because it did not fix the fault in any recorded visit. It cites the records it used.

## What happens for an alarm (the agent mesh)

An alarm starts the same memory path with more actors: the Dispatcher routes it, the Diagnostician recalls and reflects, the Parts agent checks past fixes and stock, and the Verifier reads the raw records and can veto a diagnosis (up to three rounds) before the technician briefing is written.

When recent evidence contradicts an old lesson, the Verifier says so. On a newer Daikin unit it vetoed the contactor fix because that fix had worked 20 of 22 times on older units but failed 4 of 4 times since 2026-09-18 on units installed from 2023. The plan was revised to the inverter PCB and the briefing followed the revision.
`;
fs.writeFileSync(path.join(root, "docs", "HOW_IT_WORKS.md"), md);
console.log("written", md.length, "characters");
