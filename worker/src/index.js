import { run } from './notify.js';
import { handle } from './subs.js';

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(run(env, event.scheduledTime, fetch).then(sent => { if (sent.length) console.log(sent.join('\n')); }));
  },
  fetch: (req, env) => handle(req, env),
};
