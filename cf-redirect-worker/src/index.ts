/**
 * Welcome to Cloudflare Workers! This is your first worker.
 *
 * - Run `npm run dev` in your terminal to start a development server
 * - Open a browser tab at http://localhost:8787/ to see your worker in action
 * - Run `npm run deploy` to publish your worker
 *
 * Bind resources to your worker in `wrangler.jsonc`. After adding bindings, a type definition for the
 * `Env` object can be regenerated with `npm run cf-typegen`.
 *
 * Learn more at https://developers.cloudflare.com/workers/
 */
import { Client } from "pg";

export default {
  async fetch(request, env, ctx): Promise<Response> {
    const url = new URL(request.url);
    console.log(url.search);
    const subDomain = url.hostname.split(".")[0];
    if (url.search) {
      console.log(env.HYPERDRIVE.connectionString);
      const client = new Client({ connectionString: env.HYPERDRIVE.connectionString });
      await client.connect();

      const result = await client.query("insert into tracking.cloudflare_logs (data) values ($1)", [
        JSON.stringify({
          search: Object.fromEntries(new URLSearchParams(url.search)),
          subDomain,
        }),
      ]);
      console.log(result);
    }

    switch (subDomain.toLowerCase()) {
      case "github":
        return new Response(null, {
          headers: {
            location: "https://github.com/bvincent1",
          },
          status: 302,
        });
      case "www": // hanlde "www.linkedin.com.deuterium.dev"
      case "linkedin":
        return new Response(null, {
          headers: {
            location: "https://www.linkedin.com/in/vincent-slashsolve/",
          },
          status: 302,
        });
      case "gitlab":
        return new Response(null, {
          headers: {
            location: "https://gitlab.com/bvincent1",
          },
          status: 302,
        });
      case "coursera":
        return new Response(null, {
          headers: {
            location: "https://www.coursera.org/account/accomplishments/records/B3UH5Y6FNWKA",
          },
          status: 302,
        });
      default:
        return new Response("Method not allowed", {
          status: 405,
        });
    }
  },
} satisfies ExportedHandler<Env>;
