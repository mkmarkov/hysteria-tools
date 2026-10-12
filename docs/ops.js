// Roster rules: every change is an "op" applied to the whole roster state inside a Firestore
// transaction, so simultaneous editors never overwrite each other. Port of the old server.py.

export const CLASSES = {
  Warrior: ["Protection", "Arms", "Fury"],
  Warlock: ["Affliction", "Destruction", "Demonology"],
  Mage: ["Arcane", "Fire", "Frost"],
  Priest: ["Shadow", "Holy", "Discipline"],
  Druid: ["Feral (Tank)", "Feral (DPS)", "Balance", "Restoration"],
  Shaman: ["Elemental", "Enhancement", "Restoration"],
  Paladin: ["Protection", "Retribution", "Holy"],
  Rogue: ["Combat", "Assassination", "Subtlety"],
  Hunter: ["Marksmanship", "Beast Mastery", "Survival"],
  Unknown: ["Unknown"], // shown as "?": placeholder until the player's class is known
};

export class OpError extends Error {}

const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

function findPlayer(st, pid) {
  const p = st.players.find(p => p.id === pid);
  if (!p) throw new OpError("Player not found");
  return p;
}
function findChar(p, cid) {
  const c = p.chars.find(c => c.id === cid);
  if (!c) throw new OpError("Character not found");
  return c;
}
function findGroup(st, gid) {
  const g = st.groups.find(g => g.id === gid);
  if (!g) throw new OpError("Group not found");
  return g;
}
function findSlot(st, sid) {
  for (const g of st.groups) for (const s of g.slots) if (s.id === sid) return [g, s];
  throw new OpError("Slot not found");
}
function newId(st, prefix) {
  st.nextId += 1;
  return prefix + st.nextId;
}
function cleanName(name) {
  name = String(name ?? "").trim();
  if (!name || name.length > 40) throw new OpError("Name must be 1-40 characters");
  return name;
}
const cleanNote = note => String(note || "").slice(0, 200);

// Validate an edited character list; keep existing ids so group slots survive.
function cleanChars(p, chars, st) {
  const out = [], seen = new Set();
  for (const c of chars || []) {
    const cls = c.cls;
    if (!has(CLASSES, cls)) throw new OpError(`Unknown class '${cls}'`);
    if (seen.has(cls)) throw new OpError(`${cls} listed twice for this player`);
    seen.add(cls);
    const specs = []; // keep the player's preferred order, valid specs only
    for (const s of c.specs || []) if (CLASSES[cls].includes(s) && !specs.includes(s)) specs.push(s);
    if (!specs.length) throw new OpError(`Pick at least one ${cls} spec`);
    let cid = c.id;
    if (!cid || !p.chars.some(x => x.id === cid)) cid = newId(st, p.id + "-c");
    out.push({id: cid, cls, specs, kind: c.kind === "alt" ? "alt" : "main"});
  }
  return out;
}

function dropOrphanSlots(st) {
  const valid = new Map();
  for (const p of st.players) for (const c of p.chars) valid.set(p.id + "|" + c.id, c);
  for (const g of st.groups) {
    g.slots = g.slots.filter(s => valid.has(s.pid + "|" + s.cid));
    for (const s of g.slots) {
      const c = valid.get(s.pid + "|" + s.cid);
      if (!c.specs.includes(s.spec)) s.spec = c.specs[0];
    }
    if (g.leader && !g.slots.some(s => s.pid === g.leader)) g.leader = null;
  }
}

function assertFree(st, pid, cid) {
  for (const g of st.groups) for (const s of g.slots)
    if (s.pid === pid && s.cid === cid) throw new OpError(`That character is already in ${g.name}`);
}
// Group size limits only the active raid; the bench/rotation list (slot.bench) is unlimited
const activeCount = g => g.slots.filter(s => !s.bench).length;
function assertRoom(g) {
  if (activeCount(g) >= g.size) throw new OpError(`${g.name} is full (${g.size})`);
}
function setBenchFlag(s, bench) {
  if (bench) s.bench = true; else delete s.bench;
}

export function applyOp(st, op) {
  switch (op.op) {
    case "addPlayer": {
      const pid = newId(st, "p");
      const p = {id: pid, name: cleanName(op.name), note: cleanNote(op.note), chars: []};
      if (st.players.some(x => x.name.toLowerCase() === p.name.toLowerCase()))
        throw new OpError("A player with that name already exists");
      p.chars = cleanChars(p, op.chars, st);
      if (!p.chars.length) throw new OpError("Add at least one class");
      st.players.push(p);
      break;
    }
    case "updatePlayer": {
      const p = findPlayer(st, op.pid);
      const name = cleanName(op.name);
      if (st.players.some(x => x.name.toLowerCase() === name.toLowerCase() && x.id !== p.id))
        throw new OpError("A player with that name already exists");
      const chars = cleanChars(p, op.chars, st);
      if (!chars.length) throw new OpError("Add at least one class");
      p.name = name; p.note = cleanNote(op.note); p.chars = chars;
      dropOrphanSlots(st);
      break;
    }
    case "deletePlayer": {
      const p = findPlayer(st, op.pid);
      st.players.splice(st.players.indexOf(p), 1);
      dropOrphanSlots(st);
      break;
    }
    case "assign": {
      const p = findPlayer(st, op.pid);
      const c = findChar(p, op.cid);
      const g = findGroup(st, op.gid);
      assertFree(st, p.id, c.id);
      if (!op.bench) assertRoom(g);
      const spec = c.specs.includes(op.spec) ? op.spec : c.specs[0];
      const s = {id: newId(st, "s"), pid: p.id, cid: c.id, spec};
      setBenchFlag(s, op.bench);
      g.slots.push(s);
      break;
    }
    case "move": {
      // to another group and/or between that group's raid and bench (op.bench)
      const [src, s] = findSlot(st, op.sid);
      const dst = findGroup(st, op.gid);
      const bench = !!op.bench;
      if (src === dst && !!s.bench === bench) return;
      if (!bench) assertRoom(dst);
      src.slots.splice(src.slots.indexOf(s), 1);
      setBenchFlag(s, bench);
      dst.slots.push(s);
      dropOrphanSlots(st);
      break;
    }
    case "unassign": {
      const [g, s] = findSlot(st, op.sid);
      g.slots.splice(g.slots.indexOf(s), 1);
      dropOrphanSlots(st);
      break;
    }
    case "setSpec": {
      // Change what a drafted player brings to this raid: any class/spec. The class is
      // added to the player's profile (as an alt) and the spec to that class if new.
      const [, s] = findSlot(st, op.sid);
      const p = findPlayer(st, s.pid);
      const cls = op.cls || findChar(p, s.cid).cls;
      const spec = op.spec;
      if (!has(CLASSES, cls) || !CLASSES[cls].includes(spec)) throw new OpError("Unknown class/spec");
      const cur = findChar(p, s.cid);
      let c = p.chars.find(c => c.cls === cls);
      if (!c && cur.cls === "Unknown") {
        // resolving a "?" placeholder: turn it into the real class instead of adding an alt
        cur.cls = cls; cur.specs = [];
        c = cur;
      } else if (!c) {
        c = {id: newId(st, p.id + "-c"), cls, specs: [], kind: "alt"};
        p.chars.push(c);
      } else if (c.id !== s.cid) {
        assertFree(st, p.id, c.id);
      }
      if (!c.specs.includes(spec)) c.specs.push(spec);
      s.cid = c.id; s.spec = spec;
      // a "?" placeholder left behind (player switched to a class they already had) is dropped
      if (cur !== c && cur.cls === "Unknown") p.chars.splice(p.chars.indexOf(cur), 1);
      break;
    }
    case "setLeader": {
      const g = findGroup(st, op.gid);
      const pid = op.pid;
      if (pid) {
        findPlayer(st, pid);
        if (!g.slots.some(s => s.pid === pid)) throw new OpError("The leader has to be in the group");
        for (const other of st.groups)
          if (other !== g && other.leader === pid) throw new OpError(`Already leading ${other.name}`);
      }
      g.leader = pid || null;
      break;
    }
    case "updateGroup": {
      const g = findGroup(st, op.gid);
      if (has(op, "name")) g.name = cleanName(op.name);
      if (has(op, "size")) {
        const size = Number(op.size);
        if (!Number.isInteger(size) || size < activeCount(g) || size < 1 || size > 40)
          throw new OpError(`Size must be between ${Math.max(1, activeCount(g))} and 40`);
        g.size = size;
      }
      break;
    }
    case "clearGroup": {
      const g = findGroup(st, op.gid);
      g.slots = []; g.leader = null;
      break;
    }
    default:
      throw new OpError("Unknown operation");
  }
}
