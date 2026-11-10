/*
 * Libertär Leben events (libertaer-leben.de), shown on top of the sheet.
 *
 * The community's public events are read straight from its relay in the
 * browser, so they are always current. When the sheet and Libertär Leben
 * carry the same Termin (same day, same name — "#13" suffixes ignored),
 * the Libertär Leben record replaces the sheet row entirely:
 *
 *   orga      the hosting group's affiliation ("Unabhängig", a party …),
 *             else "Libertär Leben"
 *   kontakt   the hosts' names (no e-mail: hosts are reached via the event page)
 *   link      the group's chat, with a QR code (qrcode.min.js)
 *   register  the event page, when guest registration is open
 *
 * www/cities.json is a compact copy of data/cities.json ({ n, s, c }) used
 * to find the Bundesland of an event.
 */
(function () {
	const LL = {
		relay: "wss://relay.libertaer-leben.de",
		pubkey: "3e3dde45aa2bf064047244aab62370639d555e151c5a0f0014c01a8a175d785a",
		slug: "libertaer-leben",
		site: "https://libertaer-leben.de",
		orga: "Libertär Leben",
		timeoutMs: 4000,
	};
	const KIND_DEFINITION = 34550;
	const KIND_POINTER = 34551;
	const KIND_CALENDAR_TIME = 31923;
	const DOW = ["So.", "Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa."];

	/** One REQ against the relay, resolved at EOSE (or after the timeout). */
	function relayQuery(filters) {
		return new Promise((resolve) => {
			const events = [];
			let ws;
			try {
				ws = new WebSocket(LL.relay);
			} catch (e) {
				resolve(events);
				return;
			}
			const finish = () => {
				clearTimeout(timer);
				try { ws.close(); } catch (e) { /* ignore */ }
				resolve(events);
			};
			const timer = setTimeout(finish, LL.timeoutMs);
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

	/** The QR code of a link as an image URL, or null without the QR script. */
	async function qrImage(url) {
		if (!window.QRCode) return null;
		try {
			const svg = await window.QRCode.toString(url, { type: "svg", margin: 1 });
			return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
		} catch (e) {
			return null;
		}
	}

	/**
	 * The community's public groups by the slug of each space they own:
	 * `{ "berlin-events": { slug, name, chat, affiliation } }`.
	 */
	async function loadGroupsBySpace() {
		const defs = await relayQuery([{ kinds: [KIND_DEFINITION], authors: [LL.pubkey], "#d": [LL.slug] }]);
		const def = defs.sort((a, b) => b.created_at - a.created_at)[0];
		const bySpace = new Map();
		let groups = [];
		try {
			groups = (def && JSON.parse(def.content).groups) || [];
		} catch (e) {
			return bySpace;
		}
		groups.forEach((g) => {
			if (g && Array.isArray(g.spaces)) g.spaces.forEach((space) => bySpace.set(space, g));
		});
		return bySpace;
	}

	/** The public group whose space an event was posted in, if any. */
	function groupOf(ev, groupsBySpace) {
		const prefix = `${KIND_DEFINITION}:${LL.pubkey}:${LL.slug}/`;
		const a = ev.tags.find((t) => t[0] === "a" && typeof t[1] === "string" && t[1].startsWith(prefix));
		return a ? groupsBySpace.get(a[1].slice(prefix.length)) : undefined;
	}

	/** A Libertär Leben calendar event as a Termin (termine.json's shape). */
	async function toTermin(slug, ev, cities, groupsBySpace) {
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
		const group = groupOf(ev, groupsBySpace);
		const affiliation = group && group.affiliation && group.affiliation.name ? group.affiliation : null;
		const chat = group && typeof group.chat === "string" && /^https?:\/\//.test(group.chat) ? group.chat : null;
		// Present only when the host opened guest registration (auto or approval).
		const registration = tag(ev, "registration");

		return {
			name: (tag(ev, "title") || "Termin").trim(),
			plz: (addr[2] || "").trim(),
			state: near ? near.s : null,
			city: city || (near ? near.n : ""),
			city_dist: 0,
			coords,
			date: when.date,
			dow: when.dow,
			time: when.time,
			orga: affiliation ? affiliation.name : LL.orga,
			orga_www: (affiliation && affiliation.url) || (group ? `${LL.site}/${group.slug}` : LL.site),
			// An affiliation without its own logo is found by name in ORGA_BRANDING.
			branding: affiliation ? (affiliation.logo ? { logo: affiliation.logo, bg: "#EEE" } : undefined) : undefined,
			kontakt: hosts.join(", "),
			"e-mail": null,
			link: chat,
			link_qr: chat ? await qrImage(chat) : null,
			register: registration ? `${LL.site}/${slug}` : null,
			cancelled: ev.tags.some((t) => t[0] === "status" && t[1] === "cancelled"),
			source: "libertaer-leben",
		};
	}

	async function loadTermine() {
		const [pointers, cities, groupsBySpace] = await Promise.all([
			relayQuery([{ kinds: [KIND_POINTER], authors: [LL.pubkey], limit: 500 }]),
			fetch("cities.json").then((r) => (r.ok ? r.json() : [])).catch(() => []),
			loadGroupsBySpace().catch(() => new Map()),
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
		const termine = await Promise.all(live.map((p) => {
			const ev = byId.get(p.revision);
			return ev && ev.kind === KIND_CALENDAR_TIME ? toTermin(p.slug, ev, cities, groupsBySpace) : null;
		}));
		return termine.filter(Boolean);
	}

	/**
	 * The sheet's Termine with Libertär Leben's on top. Never throws: if the
	 * relay is down the sheet is returned as it is.
	 */
	window.mergeLibertaerLebenTermine = async function (sheet) {
		let ours;
		try {
			ours = await loadTermine();
		} catch (e) {
			console.warn("Libertär Leben events unavailable:", e);
			return sheet;
		}
		const key = (t) => `${t.date}|${normalizeName(t.name)}`;
		const replaced = new Set(ours.map(key));
		const all = sheet.filter((t) => !replaced.has(key(t)));
		ours.forEach((t) => { if (!t.cancelled) all.push(t); });

		// An event without a place takes it from another Termin of the same name,
		// Libertär Leben's own first, then the latest one before it.
		all.forEach((t) => {
			if (t.coords) return;
			const name = normalizeName(t.name);
			const same = all
				.filter((o) => o.coords && normalizeName(o.name) === name)
				.sort((a, b) => (a.source === b.source ? 0 : a.source === t.source ? 1 : -1)
					|| ((a.date <= t.date) - (b.date <= t.date)) || a.date.localeCompare(b.date))
				.pop();
			if (same) Object.assign(t, { coords: same.coords, city: same.city, plz: same.plz, state: same.state, city_dist: same.city_dist });
		});
		return all.filter((t) => t.coords);
	};
})();
