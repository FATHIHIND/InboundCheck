import { resolve as pathResolve, extname } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import fs from "node:fs";

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("@/")) {
    const relPath = specifier.slice(2);
    let fullPath = pathResolve("./src", relPath);
    if (!extname(fullPath) && fs.existsSync(fullPath + ".ts")) {
      fullPath += ".ts";
    }
    return {
      shortCircuit: true,
      url: pathToFileURL(fullPath).href,
    };
  }

  if (specifier.startsWith("./") || specifier.startsWith("../")) {
    try {
      return await nextResolve(specifier, context);
    } catch (err) {
      if (context.parentURL) {
        const parentPath = fileURLToPath(context.parentURL);
        const dir = pathResolve(parentPath, "..");
        let target = pathResolve(dir, specifier);
        if (!extname(target) && fs.existsSync(target + ".ts")) {
          return {
            shortCircuit: true,
            url: pathToFileURL(target + ".ts").href,
          };
        }
      }
      throw err;
    }
  }

  return nextResolve(specifier, context);
}
