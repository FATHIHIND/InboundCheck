import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("root layout has no Google font build dependency", () => {
  const layout = readFileSync(new URL("../src/app/layout.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(layout, /next\/font\/google/);
  assert.match(layout, /next\/font\/local/);
});

for (const family of ["PlusJakartaSans", "JetBrainsMono"]) {
  test(`${family} is bundled as a valid variable TrueType font with its license`, () => {
    const base = new URL(`../src/app/fonts/${family}`, import.meta.url);
    const font = readFileSync(new URL(base.href + "-Variable.ttf"));
    assert.equal(font.readUInt32BE(0), 0x00010000);
    const tags = Array.from({ length: font.readUInt16BE(4) }, (_, i) =>
      font.toString("ascii", 12 + i * 16, 16 + i * 16));
    assert.ok(tags.includes("fvar"), "variable weight axis is required");
    const license = readFileSync(new URL(base.href + "-OFL.txt"), "utf8");
    assert.match(license, /SIL OPEN FONT LICENSE Version 1\.1/);
    assert.match(license, /Copyright 2020/);
  });
}
