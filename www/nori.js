/*
 * Libertär Leben events from Nori (nori.club), merged on top of the sheet.
 *
 * The public events of the community are read straight from its relay in
 * the browser, so they are always current. When the sheet and Libertär Leben
 * carry the same Termin (same day, same name — "#13" suffixes ignored),
 * Libertär Leben wins; sheet-only details (orga, chat link + QR, e-mail)
 * are kept. Events with guest registration get a `register` link.
 *
 * www/cities.json is a compact copy of data/cities.json ({ n, s, c }) used
 * to find the Bundesland of a Nori event.
 */
(function () {
	const NORI = {
		relay: "wss://relay.nori.club",
		storefront: "3e3dde45aa2bf064047244aab62370639d555e151c5a0f0014c01a8a175d785a",
		site: "https://libertaer-leben.de",
		orga: "Libertär Leben",
		timeoutMs: 4000,
	};
	const KIND_APPROVAL_POINTER = 34551;
	const KIND_CALENDAR_TIME = 31923;
	const DOW = ["So.", "Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa."];

	/** One REQ against the relay, resolved at EOSE (or after the timeout). */
	function relayQuery(filters) {
		return new Promise((resolve) => {
			const events = [];
			let ws;
			try {
				ws = new WebSocket(NORI.relay);
			} catch (e) {
				resolve(events);
				return;
			}
			const finish = () => {
				clearTimeout(timer);
				try { ws.close(); } catch (e) { /* ignore */ }
				resolve(events);
			};
			const timer = setTimeout(finish, NORI.timeoutMs);
			ws.onopen = () => ws.send(JSON.stringify(["REQ", "fs", ...filters]));
			ws.onmessage = (msg) => {
				let m;
				try { m = JSON.parse(msg.data); } catch (e) { return; }
				if (m[0] === "EVENT") events.push(m[2]);
				else if (m[0] === "EOSE") finish();
			};
			ws.onerror = finish;
		});
	}

	const tag = (ev, name) => {
		const t = ev.tags.find((x) => x[0] === name);
		return t ? t[1] : undefined;
	};

	function normalizeName(s) {
		return (s || "")
			.toLowerCase()
			.replace(/\s*#\s*\d+\b/g, "")
			.replace(/[^\p{L}\p{N}]+/gu, " ")
			.trim();
	}

	function berlinParts(unixSeconds) {
		const p = {};
		new Intl.DateTimeFormat("en-GB", {
			timeZone: "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit",
			hour: "2-digit", minute: "2-digit", hourCycle: "h23",
		}).formatToParts(new Date(unixSeconds * 1000)).forEach((x) => (p[x.type] = x.value));
		const date = `${p.year}-${p.month}-${p.day}`;
		return { date, time: `${p.hour}:${p.minute}`, dow: DOW[new Date(`${date}T12:00:00`).getDay()] };
	}

	function nearestCity(cities, coords) {
		let best = null;
		let bestDist = Infinity;
		cities.forEach((c) => {
			const dLat = c.c[0] - coords[0];
			const dLon = (c.c[1] - coords[1]) * Math.cos((coords[0] * Math.PI) / 180);
			const d = Math.sqrt(dLat * dLat + dLon * dLon) * 111; // km, good enough
			if (d < bestDist) { bestDist = d; best = c; }
		});
		return best && bestDist < 60 ? best : null;
	}

	/** A Nori calendar event in termine.json's shape (only the fields it knows). */
	function toTermin(slug, ev, cities) {
		const start = Number(tag(ev, "start"));
		if (!Number.isFinite(start)) return null;
		const when = berlinParts(start);
		const addr = ev.tags.find((t) => t[0] === "address") || [];
		const geo = ev.tags.find((t) => t[0] === "geo");
		const city = (addr[3] || "").trim();

		let coords = null;
		if (geo && Number.isFinite(Number(geo[1])) && Number.isFinite(Number(geo[2]))) {
			coords = [Number(geo[1]), Number(geo[2])];
		}
		const byName = city && cities.find((c) => c.n.toLowerCase() === city.toLowerCase());
		const near = byName || (coords && nearestCity(cities, coords));
		if (!coords && byName) coords = byName.c.slice();

		const hosts = ev.tags
			.filter((t) => t[0] === "p" && t[3] === "host" && t[4])
			.map((t) => t[4].trim())
			.filter((x, i, a) => x && a.indexOf(x) === i);
		// Present only when the host opened guest registration (auto or approval).
		const registration = tag(ev, "registration");

		return {
			name: (tag(ev, "title") || "Termin").trim(),
			plz: (addr[2] || "").trim() || undefined,
			state: near ? near.s : undefined,
			city: city || (near ? near.n : undefined),
			city_dist: 0,
			coords: coords || undefined,
			date: when.date,
			dow: when.dow,
			time: when.time,
			kontakt: hosts.length ? hosts.join(", ") : undefined,
			register: registration ? `${NORI.site}/${slug}` : undefined,
			cancelled: ev.tags.some((t) => t[0] === "status" && t[1] === "cancelled"),
			source: "nori",
		};
	}

	async function loadNoriTermine() {
		const [pointers, cities] = await Promise.all([
			relayQuery([{ kinds: [KIND_APPROVAL_POINTER], authors: [NORI.storefront], limit: 500 }]),
			fetch("cities.json").then((r) => (r.ok ? r.json() : [])).catch(() => []),
		]);
		// Newest pointer per slug wins; only live event pointers count.
		const latest = new Map();
		pointers.sort((a, b) => b.created_at - a.created_at).forEach((ev) => {
			const slug = tag(ev, "d");
			if (slug && !latest.has(slug)) latest.set(slug, ev);
		});
		const live = [];
		latest.forEach((ev, slug) => {
			if (tag(ev, "type") !== "events" || ev.tags.some((t) => t[0] === "removed")) return;
			if (tag(ev, "e")) live.push({ slug, revision: tag(ev, "e") });
		});
		if (live.length === 0) return [];

		const revisions = await relayQuery([{ ids: live.map((p) => p.revision) }]);
		const byId = new Map(revisions.map((r) => [r.id, r]));
		return live
			.map((p) => byId.get(p.revision))
			.map((ev, i) => (ev && ev.kind === KIND_CALENDAR_TIME ? toTermin(live[i].slug, ev, cities) : null))
			.filter(Boolean);
	}

	/**
	 * The sheet's Termine with Libertär Leben's on top. Never throws: if the
	 * relay is down the sheet is returned as it is.
	 */
	window.mergeNoriTermine = async function (sheet) {
		let nori;
		try {
			nori = await loadNoriTermine();
		} catch (e) {
			console.warn("Libertär Leben events unavailable:", e);
			return sheet;
		}
		const key = (t) => `${t.date}|${normalizeName(t.name)}`;
		const all = sheet.slice();
		const index = new Map();
		all.forEach((t, i) => { if (!index.has(key(t))) index.set(key(t), i); });
		nori.forEach((n) => {
			const i = index.get(key(n));
			if (n.cancelled) {
				if (i !== undefined) all[i] = null;
				return;
			}
			const fields = Object.fromEntries(Object.entries(n).filter(([, v]) => v !== undefined));
			if (i !== undefined) {
				all[i] = { ...all[i], ...fields };
				return;
			}
			// A new date of a known Stammtisch keeps its orga and chat link, and
			// its place when the event has none: from the latest earlier Termin.
			const name = normalizeName(n.name);
			const sibling = all
				.filter((o) => o && o.coords && normalizeName(o.name) === name)
				.sort((a, b) => ((a.date <= n.date) - (b.date <= n.date)) || a.date.localeCompare(b.date))
				.pop();
			const base = sibling
				? { ...sibling, register: undefined }
				: { orga: NORI.orga, orga_www: NORI.site, kontakt: null, "e-mail": null, link: null, link_qr: null, city_dist: 0 };
			all.push({ ...base, ...fields });
		});
		return all.filter((t) => t && t.coords);
	};
})();
