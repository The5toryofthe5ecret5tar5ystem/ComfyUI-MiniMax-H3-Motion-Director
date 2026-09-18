// Module resolution hooks: the enhancer (and its siblings) import ComfyUI's
// frontend `../../scripts/api.js`, which does not exist in the standalone repo.
// Point those specifiers at the local stubs.
import { registerHooks } from "node:module";

const here = new URL("./", import.meta.url);

registerHooks({
    resolve(specifier, context, nextResolve) {
        if (specifier.endsWith("/scripts/api.js")) {
            return { url: new URL("api-stub.mjs", here).href, shortCircuit: true };
        }
        if (specifier.endsWith("/scripts/app.js")) {
            return { url: new URL("app-stub.mjs", here).href, shortCircuit: true };
        }
        return nextResolve(specifier, context);
    },
});
