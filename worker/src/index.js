import { run } from './notify.js';

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(run(env, event.scheduledTime, fetch).then(sent => {
      if (sent.length) console.log(sent.join('\n'));
    }));
  },
  async fetch(req, env) {
    return new Response(`scbbl notifier. Subscribe on ntfy to ${env.TOPIC_PREFIX}-all or ${env.TOPIC_PREFIX}-<team>, e.g. ${env.TOPIC_PREFIX}-hea.\n`);
  },
};
