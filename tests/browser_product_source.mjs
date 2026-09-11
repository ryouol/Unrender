import fs from "node:fs";

export const appPath = new URL("../unrender/product/static/app.js", import.meta.url);
export const source = ["google.js", "previews.js", "library.js", "settings.js", "app.js"]
  .map((name) => fs.readFileSync(new URL(`../unrender/product/static/${name}`, import.meta.url), "utf8"))
  .join("\n").replace(/\nbindEvents\(\);\nboot\(\);\s*$/, "");
