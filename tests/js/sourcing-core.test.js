const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../../workflows/lib/sourcing-core.js");

// ---------------------------------------------------------------------------
// interpolate
// ---------------------------------------------------------------------------

test("interpolate fills present tokens", () => {
  assert.equal(
    core.interpolate("Bonjour {{fullName}} de {{companyName}}", { fullName: "A B", companyName: "Acme" }),
    "Bonjour A B de Acme",
  );
});

test("interpolate blanks missing or null tokens", () => {
  assert.equal(core.interpolate("x {{ghost}} y {{nul}} z", { nul: null }), "x  y  z");
});

test("interpolate tolerates inner spaces and leaves plain text", () => {
  assert.equal(core.interpolate("{{ jobTitle }} fixe", { jobTitle: "Gérant" }), "Gérant fixe");
});

// ---------------------------------------------------------------------------
// score prompt + verdict schema + lead identity
// ---------------------------------------------------------------------------

test("buildScorePrompt embeds the interpolated template and the candidate facts", () => {
  const lead = { linkedinUrl: "https://lk/a", fullName: "Marie Roy", jobTitle: "Gérante", companyName: "Roy Immo", location: "Lyon" };
  const out = core.buildScorePrompt("Évalue ce {{jobTitle}}.", lead);
  assert.match(out, /Évalue ce Gérante\./);
  assert.match(out, /Marie Roy/);
  assert.match(out, /Roy Immo/);
  assert.match(out, /Lyon/);
});

test("VERDICT_SCHEMA requires qualifie and raison", () => {
  assert.deepEqual(core.VERDICT_SCHEMA.required, ["qualifie", "raison"]);
  assert.equal(core.VERDICT_SCHEMA.properties.qualifie.type, "boolean");
});

test("leadId/leadLabel fall back through identifiers", () => {
  assert.equal(core.leadId({ people_db_id: "p1" }), "p1");
  assert.equal(core.leadLabel({ linkedinUrl: "https://lk/x" }), "https://lk/x");
});
