// Panel de Buscarancho: formulario de filtros + listado de resultados.
// Guarda todo en un KV. El buscador (GitHub Actions) lee /api/filters y publica en /api/listings.
import PAGE from "./panel.html";

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });

const FIELDS = {
  operacion: (v) => (["venta", "alquiler"].includes(v) ? v : "venta"),
  tipo: (v) => (["departamento", "casa", "ph"].includes(v) ? v : "departamento"),
  barrios: (v) => (Array.isArray(v) ? v.map((b) => String(b).trim().slice(0, 60)).filter(Boolean).slice(0, 15) : []),
  ambientes_min: int,
  ambientes_max: int,
  banos_min: int,
  precio_min: int,
  precio_max: int,
  moneda: (v) => (v === "ARS" ? "ARS" : "USD"),
  cochera: Boolean,
  balcon: Boolean,
  incluir_sin_confirmar: Boolean,
  fuentes: (v) => (Array.isArray(v) ? v.map(String).filter((s) => /^[a-z0-9_]{1,30}$/.test(s)) : []),
};

function int(v) {
  const n = parseInt(v, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function authorized(request, env) {
  const token = (request.headers.get("authorization") || "").replace(/^Bearer /, "");
  return Boolean(env.PANEL_TOKEN) && token === env.PANEL_TOKEN;
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    const write = request.method === "PUT" || request.method === "POST";
    if (write && !authorized(request, env)) return json({ error: "Clave incorrecta" }, 401);

    if (pathname === "/api/filters") {
      if (request.method === "PUT") {
        const body = await request.json();
        const filters = Object.fromEntries(Object.entries(FIELDS).map(([k, clean]) => [k, clean(body[k])]));
        await env.KV.put("filters", JSON.stringify(filters));
        return json(filters);
      }
      return json(JSON.parse((await env.KV.get("filters")) || "{}"));
    }

    if (pathname === "/api/listings") {
      if (request.method === "PUT") {
        await env.KV.put("listings", await request.text());
        return json({ ok: true });
      }
      return json(JSON.parse((await env.KV.get("listings")) || '{"listings":[],"status":{}}'));
    }

    // Opcional: "Buscar ahora" dispara el workflow de GitHub (requiere los secretos GH_TOKEN y GH_REPO)
    if (pathname === "/api/run" && request.method === "POST") {
      if (!env.GH_TOKEN || !env.GH_REPO) return json({ error: "Falta configurar GH_TOKEN / GH_REPO en el Worker" }, 501);
      const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/buscar.yml/dispatches`, {
        method: "POST",
        headers: { authorization: `Bearer ${env.GH_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "buscarancho-panel" },
        body: JSON.stringify({ ref: "main" }),
      });
      return json({ ok: r.ok }, r.ok ? 200 : 502);
    }

    if (pathname === "/") return new Response(PAGE, { headers: { "content-type": "text/html; charset=utf-8" } });
    return new Response("No encontrado", { status: 404 });
  },
};
