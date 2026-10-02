import { NextResponse } from "next/server";

// The dashboard's /api is also the phone's API (openapi.yaml). `next dev`
// listens on every interface, and POST /api/queue with kind "raw" runs any
// command on a board — so once API_TOKEN is set in .env.local, every /api call
// needs it: `Authorization: Bearer <token>` from the phone, or the ae_token
// cookie a browser gets by opening any page once with ?token=<token>.
// ponytail: unset API_TOKEN = old open behaviour, for a Mac-only setup.
const TOKEN = process.env.API_TOKEN?.trim();

// Constant-time compare; the edge runtime has no crypto.timingSafeEqual.
const same = (a = "", b = "") => {
  let d = a.length ^ b.length;
  for (let i = 0; i < b.length; i++) d |= a.charCodeAt(i % (a.length || 1)) ^ b.charCodeAt(i);
  return d === 0;
};

export function middleware(req) {
  if (!TOKEN) return NextResponse.next();
  const url = req.nextUrl;

  if (!url.pathname.startsWith("/api/")) {
    const t = url.searchParams.get("token");
    if (!t || !same(t, TOKEN)) return NextResponse.next();
    url.searchParams.delete("token");
    const res = NextResponse.redirect(url);
    res.cookies.set("ae_token", TOKEN, { httpOnly: true, sameSite: "strict", maxAge: 60 * 60 * 24 * 365 });
    return res;
  }

  const bearer = req.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  if (same(bearer, TOKEN) || same(req.cookies.get("ae_token")?.value, TOKEN)) {
    return NextResponse.next();
  }
  return NextResponse.json({ error: "missing or bad token" }, { status: 401 });
}

export const config = { matcher: ["/((?!_next/|favicon).*)"] };
