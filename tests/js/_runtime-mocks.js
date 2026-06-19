// Faithful mocks of the Workflow runtime hooks, shared by the workflow-core tests
// (not a *.test.js file, so the runner doesn't execute it directly).
// pipeline: barrier-free; a stage returning null/undefined drops the item; stage gets (prev, item, i).
// parallel: Promise.all; a throwing thunk resolves to null.

async function fakePipeline(items, ...stages) {
  return Promise.all(items.map(async (item, i) => {
    let v = item;
    for (const s of stages) { v = await s(v, item, i); if (v == null) return null; }
    return v;
  }));
}

async function fakeParallel(thunks) {
  return Promise.all(thunks.map(async (t) => { try { return await t(); } catch { return null; } }));
}

module.exports = { fakePipeline, fakeParallel };
