import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { asLigand, fetchCoordinates, normalise, parseSource, sniffFormat, sourceName, type Atom3D, type Coordinates } from "./viewer";

const specOf = (raw: string) => {
  const p = parseSource(raw);
  if (!p || !("spec" in p)) throw new Error(`no spec: ${JSON.stringify(p)}`);
  return p.spec;
};

describe("parseSource", () => {
  it("reads a bare PDB id", () => {
    expect(specOf("6vxx").models).toEqual([{ pdb: "6VXX" }]);
    expect(specOf("`6VXX`").models).toEqual([{ pdb: "6VXX" }]);
  });

  it("reads AF-<accession> as an AlphaFold model coloured by pLDDT", () => {
    expect(specOf("AF-P69905").models).toEqual([{ afdb: "P69905", color: "plddt" }]);
    expect(specOf("AF-P69905-F1").models[0].afdb).toBe("P69905");
  });

  it("reads JSON with models", () => {
    const s = specOf('{"title": "T", "models": [{"pdb": "6SC6"}, {"ccd": "ATP"}]}');
    expect(s.title).toBe("T");
    expect(s.models).toHaveLength(2);
  });

  it("takes pdb / afdb / ccd / pubchem / data at the top level as a one-model spec", () => {
    expect(specOf('{"pdb": "6SC6", "title": "x", "chains": ["A"]}')).toMatchObject({ title: "x", models: [{ pdb: "6SC6", chains: ["A"] }] });
    expect(specOf('{"afdb": "P69905"}').models).toEqual([{ afdb: "P69905" }]);
    expect(specOf('{"ccd": "ATP", "caption": "c"}')).toMatchObject({ caption: "c", models: [{ ccd: "ATP" }] });
    expect(specOf('{"pubchem": 2244}').models).toEqual([{ pubchem: 2244 }]);
    expect(specOf('{"data": "HETATM", "format": "pdb"}').models).toEqual([{ data: "HETATM", format: "pdb" }]);
  });

  it("returns an error for JSON that is not a usable spec", () => {
    for (const raw of ['{"title": "no models"}', '{"models": [{"label": "no source"}]}', '{"models": []}', '{"pubchem": ""}']) {
      const p = parseSource(raw);
      expect(p && "error" in p).toBe(true);
    }
    expect((parseSource('{"models": [{"label": "x"}]}') as { error: string }).error).toContain("model 0");
    expect(() => normalise([])).toThrow();
  });

  it("returns null while the block is still streaming", () => {
    for (const raw of ['{"models": [', '{"title": "Spi', "", "just words", "AF-"]) expect(parseSource(raw)).toBeNull();
  });
});

describe("asLigand", () => {
  const atoms = (): Atom3D[] => [
    { x: 0, y: 0, z: 0, chain: "", resi: "", resn: "", atom: "", elem: "C", hetflag: false, b: 0 },
    { x: 1, y: 0, z: 0, chain: "", resi: "", resn: "", atom: "", elem: "O", hetflag: false, b: 0 },
  ];

  it("makes SDF atoms one het group named after a short title", () => {
    const a = atoms();
    asLigand(a, { name: "ATP", format: "sdf", data: "atp\n  RDKit\n" });
    expect(a.map((x) => [x.chain, x.resi, x.resn, x.hetflag, x.atom])).toEqual([["L", 1, "ATP", true, "C1"], ["L", 1, "ATP", true, "O2"]]);
  });

  it("uses LIG when the title is not a 1-3 character code", () => {
    const a = atoms();
    asLigand(a, { name: "x", format: "sdf", data: "adenosine triphosphate\n" });
    expect(a[0].resn).toBe("LIG");
  });

  it("reads the MOL2 name and keeps atom names it already has", () => {
    const a = atoms();
    a[0].atom = "CA1";
    asLigand(a, { name: "x", format: "mol2", data: "@<TRIPOS>MOLECULE\nhem\n 2 1\n" });
    expect(a.map((x) => [x.resn, x.atom])).toEqual([["HEM", "CA1"], ["HEM", "O2"]]);
  });

  it("leaves PDB and mmCIF atoms alone", () => {
    const a = atoms();
    asLigand(a, { name: "x", format: "pdb", data: "" } as Coordinates);
    expect(a[0].chain).toBe("");
  });
});

describe("sources", () => {
  it("names each source", () => {
    expect([{ pdb: "6VXX" }, { afdb: "P69905" }, { ccd: "atp" }, { pubchem: 2244 }, { data: "x" }].map(sourceName))
      .toEqual(["6VXX", "AF-P69905", "ATP", "CID 2244", "inline"]);
  });

  it("sniffs the format of inline data", () => {
    expect(sniffFormat("x\n  RDKit\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\n")).toBe("sdf");
    expect(sniffFormat("@<TRIPOS>MOLECULE\nx")).toBe("mol2");
    expect(sniffFormat("data_1ABC\n_atom_site.id")).toBe("cif");
    expect(sniffFormat("ATOM      1  N   ALA A   1")).toBe("pdb");
  });
});

describe("fetchCoordinates", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn(async (url: string) => new Response(JSON.stringify({ name: "n", format: url.includes("pdb=") ? "cif" : "sdf", data: "d" })));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());
  const lastUrl = () => String(fetchMock.mock.calls.at(-1)![0]);

  it.each([
    [{ pdb: "1ABC" }, "/knowledge-chat/structures?pdb=1ABC"],
    [{ afdb: "Q8W3K0" }, "/knowledge-chat/structures?afdb=Q8W3K0"],
    [{ ccd: "ATP" }, "/knowledge-chat/structures?ccd=ATP"],
    [{ ccd: "hem" }, "/knowledge-chat/structures?ccd=HEM"],
    [{ pubchem: 2244 }, "/knowledge-chat/structures?pubchem=2244"],
    [{ pubchem: "5957" }, "/knowledge-chat/structures?pubchem=5957"],
  ])("asks the backend for %j", async (model, path) => {
    const c = await fetchCoordinates(model);
    expect(lastUrl()).toContain(path);
    expect(c.data).toBe("d");
    expect((fetchMock.mock.calls.at(-1)![1] as RequestInit).credentials).toBe("include");
  });

  it("caches per source", async () => {
    await fetchCoordinates({ ccd: "GTP" });
    await fetchCoordinates({ ccd: "GTP" });
    await fetchCoordinates({ pubchem: 9999 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("returns inline data without any request", async () => {
    const c = await fetchCoordinates({ data: "ATOM  1", format: "pdb", label: "x" });
    expect(c).toEqual({ name: "inline", format: "pdb", data: "ATOM  1" });
    const m = await fetchCoordinates({ data: "@<TRIPOS>MOLECULE\nx" });
    expect(m.format).toBe("mol2");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects with the backend's message and forgets the failure", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "no such compound" }), { status: 404 }));
    await expect(fetchCoordinates({ pubchem: 1 })).rejects.toThrow("no such compound");
    await expect(fetchCoordinates({ pubchem: 1 })).resolves.toMatchObject({ data: "d" });
  });

  it("rejects an empty inline model", async () => {
    await expect(fetchCoordinates({ data: "  " })).rejects.toThrow();
  });
});
