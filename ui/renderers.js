// How this plugin's page draws its tasks' outputs. Every plugin's page is NanoAgent's chat: a
// person says what they need, the plugin's agent runs one of its tasks, and the page shows the
// task's output, drawn from its JSON Schema. To draw an output class differently, map its name to
// a renderer, `(value, {task, verdict, send}) => Element`, built from ./kit/components.js:
//
//   import { h } from "./kit/components.js";
//   export default { SpecOutput: (done) => h("p", { text: `spec written to ${done.path}` }) };
//
// `send(text)` sends a message as if the person typed it, e.g. from a button on the result.
export default {};
