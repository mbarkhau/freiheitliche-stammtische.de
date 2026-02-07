(function () {

	// --- Constants ---
	const ORGANIZER_LOGOS = {
		"Unabhängig": "img/logo_256.png",
		"DIE LIBERTÄREN": "img/logo_die-libertaeren.png",
		"Hayek Club": "img/logo_hayek-club.png",
		"Staatenlos": "img/logo_staatenlos.png",
		"Free Cities Foundation": "img/logo_free-cities.png",
		"Bündnis Libertärer": "img/logo_blib.png",
		"Milei Institut": "img/logo_milei-institut.png",
		"Partei der Vernunft": "img/logo_pdv.png",
	};

	function getOrgaLogo(orga) {
		if (!orga) return "img/logo_256.png";
		// Check for exact match
		if (ORGANIZER_LOGOS[orga]) {
			return ORGANIZER_LOGOS[orga];
		}
		// Check for partial match (e.g. "Hayek Club Berlin" -> "Hayek Club")
		for (const [key, value] of Object.entries(ORGANIZER_LOGOS)) {
			if (orga.includes(key)) {
				return value;
			}
		}
		return "img/logo_256.png";
	}

	function stringToHash(str) {
		let hash = 0;
		if (str.length === 0) return hash;
		for (let i = 0; i < str.length; i++) {
			hash = ((hash << 5) - hash) + str.charCodeAt(i);
			hash |= 0;
		}
		return hash;
	}

	function getDeterministicOffset(seed) {
		const x = Math.sin(stringToHash(seed)) * 10000;
		return x - Math.floor(x);
	}

	// --- Theme Logic ---
	function toggleTheme() {
		const currentTheme = document.documentElement.getAttribute('data-theme');
		const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

		if (newTheme === 'dark') {
			document.documentElement.setAttribute('data-theme', 'dark');
		} else {
			document.documentElement.removeAttribute('data-theme');
		}

		localStorage.setItem('theme', newTheme);
		const button = document.getElementById('theme-toggle');
		button.textContent = newTheme === 'dark' ? '✹' : '☾';

		if (globalMapMarkers && globalTermine) {
			initMap(globalMapMarkers, globalTermine);
		}
	}

	function initTheme() {
		let savedTheme = localStorage.getItem('theme');
		if (!savedTheme) {
			if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
				savedTheme = 'dark';
			}
		}

		if (savedTheme === 'dark') {
			document.documentElement.setAttribute('data-theme', 'dark');
		} else {
			document.documentElement.removeAttribute('data-theme');
		}

		const button = document.getElementById('theme-toggle');
		if (button) {
			button.textContent = savedTheme === 'dark' ? '✹' : '☾';
		}
	}

	function getMapColors() {
		const style = getComputedStyle(document.documentElement);
		return {
			fill: style.getPropertyValue('--map-fill').trim() || '#fcfcfc',
			stroke: style.getPropertyValue('--map-stroke').trim() || '#d1d1d1',
			accent: style.getPropertyValue('--accent-color').trim() || '#c5a059'
		};
	}

	// --- Date & Formatting Utilities ---
	function getRelativeDateString(dateStr) {
		if (!dateStr) return '';
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		const eventDate = new Date(dateStr + 'T00:00:00');
		const diffTime = eventDate - today;
		const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

		if (diffDays === 0) return 'heute';
		if (diffDays === 1) return 'morgen';
		if (diffDays === -1) return 'gestern';

		const weeks = Math.abs(Math.round(diffDays / 7));
		const months = Math.abs(Math.round(diffDays / 30));
		if (diffDays > 0) {
			if (months > 2) return `in ${months} Monaten`;
			if (weeks > 2) return `in ${weeks} Wochen`;
			return `in ${diffDays} Tagen`;
		} else {
			if (months > 2) return `vor ${months} Monaten`;
			if (weeks > 2) return `vor ${weeks} Wochen`;
			return `vor ${Math.abs(diffDays)} Tagen`;
		}
	}

	const MONTH_NAMES = ["JAN", "FEB", "MÄR", "APR", "MAI", "JUN", "JUL", "AUG", "SEP", "OKT", "NOV", "DEZ"];

	function getDetailedDate(dateStr) {
		const date = new Date(dateStr + 'T00:00:00');
		return {
			dayNum: date.getDate(),
			month: MONTH_NAMES[date.getMonth()],
			year: String(date.getFullYear())
		};
	}

	function cityText(termin) {
		const dist = termin.city_dist;
		return dist < 15 ? termin.city : ('bei ' + termin.city);
	}

	function formatKontakt(kontakt, email) {
		if (!kontakt && !email) return '';
		if (email) {
			const recipient = kontakt ? `${kontakt.trim()} <${email.trim()}>` : email.trim();
			return `<a href="mailto:${encodeURIComponent(recipient)}">${kontakt || email}</a>`;
		}
		return kontakt || '';
	}

	function cardHtml(t) {
		const dateInfo = getDetailedDate(t.date);
		// Hidden search content for better search accuracy
		const searchParts = [t.name, t.city, t.plz, t.state, t.orga, t.kontakt, t['e-mail'], t.date, t.dow]
		const searchContent = searchParts.join(' ').toLowerCase();

		return `
		<div class="search-content" style="display: none;">${searchContent}</div>
		<div class="date-badge">
			<span class="day-name-num">${t.dow || ''} ${dateInfo.dayNum}</span>
			<div class="day-month-year">
				<span class="month">${dateInfo.month}</span>
				<span class="year">${dateInfo.year}</span>
			</div>
			<span class="relative-date">${getRelativeDateString(t.date)}</span>
		</div>
		<div class="event-info">
			<h3 class="event-title">${t.name || ''}</h3>
			<div class="event-detail">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
				<span>${t.plz || ''} ${cityText(t)}</span>
			</div>
			<div class="event-detail">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
				<span>${t.orga || ''}</span>
			</div>
			<div class="orga-logo-card-container">
				<img src="${getOrgaLogo(t.orga)}" class="orga-logo-card" alt="${t.orga || 'Logo'}">
			</div>
		</div>`;
	}

	// --- Card List Management ---
	function populateList(termine) {
		const listContainer = document.querySelector('#termine-list');
		listContainer.innerHTML = '';
		const today = new Date().toISOString().split('T')[0];
		let separatorAdded = false;

		termine.forEach(t => {
			if (!separatorAdded && t.date >= today) {
				const separator = document.createElement('div');
				separator.className = 'list-separator';
				separator.id = 'future-separator';
				listContainer.appendChild(separator);
				separatorAdded = true;
			}

			const card = document.createElement('div');
			card.className = 'event-card';
			card.id = 'marker-' + t.originalIndex;
			card.dataset.date = t.date; // Store date for filtering

			if (t.date < today) {
				card.classList.add('past-event');
				card.style.opacity = '0.6';
			}

			card.innerHTML = cardHtml(t);

			card.addEventListener('click', () => {
				updateSelectionPanel(t, true);
				// On mobile, maybe don't scroll map into view automatically if user is browsing cards?
				// But we want to show the marker on the map too.
				if (currentMap) {
					currentMap.setFocus({ coords: t.coords, scale: 3, animate: true });
				}
			});

			listContainer.appendChild(card);
		});
	}

	// --- Map Logic ---
	let currentMap = null;
	let globalTermine = null;
	let globalMapMarkers = null;

	function debounce(func, wait) {
		let timeout;
		return function () {
			const context = this;
			const args = arguments;
			clearTimeout(timeout);
			timeout = setTimeout(() => func.apply(context, args), wait);
		};
	}

	function initMap(mapMarkers, events) {
		if (currentMap) {
			currentMap.destroy();
		}
		document.getElementById('map').innerHTML = '';

		const colors = getMapColors();

		try {
			currentMap = new jsVectorMap({
				focusOn: { coords: [51, 10], scale: 0.9 },
				zoomMin: 0.9,
				markersSelectable: true,
				markersSelectableOne: true,
				selector: '#map',
				map: 'de_mill',
				backgroundColor: 'transparent',
				regionStyle: {
					initial: {
						fill: colors.fill,
						stroke: colors.stroke,
						strokeWidth: 0.8
					},
				},
				zoomButtons: false,
				zoomOnScroll: true,
				markers: [...mapMarkers],
				onMarkerClick: function (event, index) {
					const marker = globalMapMarkers[index];
					const today = new Date().toISOString().split('T')[0];

					// Find all events for this marker
					const markerTermine = globalTermine.filter(t => marker.ids.includes(t.originalIndex));

					// Find the first future event, or fallback to the first event
					const termin = markerTermine.find(t => t.date >= today) || markerTermine[0];

					updateSelectionPanel(termin, true);
				},
				onRegionClick: function (event, code) {
					updateSearch(code);
					if (window.innerWidth <= 900) {
						document.getElementById('event-list-container').scrollIntoView({ behavior: 'auto' });
					}
				},
				onLoaded: function (map) {
					// Clear search if clicking map backdrop
					map.container.querySelector('svg').addEventListener('click', function (e) {
						if (e.target.tagName === 'svg' || e.target.id === 'jvm-regions-group') {
							updateSearch('');
						}
					});
				}
			});
		} catch (e) {
			console.error("Map Error:", e);
			document.getElementById('map').innerHTML = '<p style="padding: 20px;">Fehler beim Laden der Karte.</p>';
		}
	}

	function getCalendarLink(termin) {
		const title = encodeURIComponent(termin.name || 'Stammtisch');
		const location = encodeURIComponent(`${termin.plz || ''} ${cityText(termin)}, Deutschland`);

		let startHour = 19;
		let startMin = 0;

		if (termin.time) {
			const timeMatch = termin.time.match(/(\d{1,2})[:.]?(\d{2})?/);
			if (timeMatch) {
				startHour = parseInt(timeMatch[1], 10);
				if (timeMatch[2]) startMin = parseInt(timeMatch[2], 10);
			}
		}

		const start = new Date(`${termin.date}T${String(startHour).padStart(2, '0')}:${String(startMin).padStart(2, '0')}:00`);
		const end = new Date(start.getTime() + 3 * 60 * 60 * 1000); // Default 3 hours

		const toJvmFormat = (d) => d.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
		const dates = `${toJvmFormat(start)}/${toJvmFormat(end)}`;

		const details = encodeURIComponent(`Orga: ${termin.orga || ''}\nKontakt: ${termin.kontakt || ''}\n${termin.link || ''}`);
		return `https://www.google.com/calendar/render?action=TEMPLATE&text=${title}&dates=${dates}&details=${details}&location=${location}&sf=true&output=xml`;
	}

	function updateSelectionPanel(termin, showOverlay = true) {
		const overlay = document.getElementById('selection-overlay');
		if (showOverlay) {
			overlay.style.display = 'block';
			const relativeDate = getRelativeDateString(termin.date);
			overlay.innerHTML = `
	<div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
	  <div style="display: flex; align-items: center; gap: 0.75rem;">
	  	<img src="${getOrgaLogo(termin.orga)}" class="orga-logo-overlay" alt="${termin.orga || 'Logo'}">
	  	<h4 style="margin: 0; font-size: 1.1rem;">${termin.name || ''}</h4>
	  </div>
	  <button onclick="document.getElementById('selection-overlay').style.display='none'" class="map-overlay-close">✕</button>
	</div>
	<div style="font-size: 0.9rem; color: var(--text-muted); display: flex; flex-direction: column; gap: 0.25rem;">
	  <div>
		  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
		  ${termin.date || ''} (${termin.dow || ''}) — ${relativeDate}
		  <a href="${getCalendarLink(termin)}" target="_blank" style="margin-left: 8px; text-decoration: none; font-size: 0.8rem; background: var(--accent-color); color: var(--accent-contrast); padding: 2px 6px; border-radius: 4px; display: inline-flex; align-items: center; gap: 4px;">
			  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
			  Kalender
		  </a>
	  </div>
	  <div><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg> <a href="https://maps.google.com/?q=${termin.plz},${cityText(termin)},Deutschland" target="_blank">${termin.plz || ''} ${cityText(termin)}</a></div>
	  <div><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg> ${formatKontakt(termin.kontakt, termin['e-mail'])}</div>
	  <div style="margin-top: 0.5rem;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg> ${termin.orga_www ? `<a href="${termin.orga_www}" target="_blank">${termin.orga || 'Link'}</a>` : (termin.orga || '')} ${termin.time ? `<span style="margin-left: 8px; opacity: 0.8;">ab ${termin.time}</span>` : ''}</div>
	  ${termin.link_qr ? `<div style="margin-top: 0.5rem;">${termin.link ? `<a href="${termin.link}" target="_blank">` : ''}<img src="${termin.link_qr}" alt="QR Code" style="width: 100%; max-width: 150px; border-radius: 4px;">${termin.link ? '</a>' : ''}</div>` : ''}
	</div>
	`;
		} else {
			overlay.style.display = 'none';
		}
	}

	function updateSearch(val) {
		const searchInput = document.querySelector('.filter-panel .table-search');
		if (searchInput) searchInput.value = val;

		const today = new Date().toISOString().split('T')[0];
		let firstFutureCard = null;
		let matchCount = 0;
		let futureMatchCount = 0;

		if (val.trim() === '') {
			document.querySelectorAll('.event-card').forEach(card => {
				card.style.display = 'flex';
				matchCount++;
				if (card.dataset.date >= today) {
					futureMatchCount++;
					if (!firstFutureCard) firstFutureCard = card;
				}
			});
		} else {
			const lowerVal = val.toLowerCase();
			document.querySelectorAll('.event-card').forEach(card => {
				const searchContent = card.querySelector('.search-content').textContent;
				if (searchContent.includes(lowerVal)) {
					card.style.display = 'flex';
					matchCount++;
					if (card.dataset.date >= today) {
						futureMatchCount++;
						if (!firstFutureCard) firstFutureCard = card;
					}
				} else {
					card.style.display = 'none';
				}
			});
		}

		const separator = document.getElementById('future-separator');
		if (separator) {
			if (futureMatchCount > 0) {
				separator.style.display = 'flex';
				separator.scrollIntoView({ behavior: 'auto', block: 'start' });
			} else {
				separator.style.display = 'none';
			}
		}

		const noResults = document.getElementById('no-results');
		if (noResults) {
			noResults.style.display = matchCount === 0 ? 'flex' : 'none';
		}
	}

	async function loadData() {
		initTheme();
		const response = await fetch('termine.json');
		let termine = await response.json();
		const today = new Date().toISOString().split('T')[0];

		// Map original index to all events for reliable lookup
		termine = termine.map((t, i) => ({ ...t, originalIndex: i }));

		// Sort by date ASC
		termine.sort((a, b) => (a.date || '').localeCompare(b.date || ''));

		// Group markers
		const groups = {};
		termine.forEach(t => {
			const coordKey = t.coords.join(',');
			if (!groups[coordKey]) groups[coordKey] = [];
			groups[coordKey].push(t);
		});

		const markerRadius = window.innerWidth <= 720 ? 10 : 7;
		const colors = getMapColors();

		const mapMarkers = [];

		// 1. Group by Location (coords)
		Object.values(groups).forEach(group => {
			// 2. Sub-group by Event Name
			const nameGroups = {};
			group.forEach(t => {
				const name = t.name || 'Unbenannt';
				if (!nameGroups[name]) nameGroups[name] = [];
				nameGroups[name].push(t);
			});

			// 3. Create markers for each distinct event at this location
			const subGroups = Object.values(nameGroups);
			subGroups.forEach((subGroup, index) => {
				let coords = subGroup[0].coords;
				const displayEvent = subGroup.find(t => t.date >= today) || subGroup[0];

				if (index > 0) {
					// Apply random offset if there are multiple events at this location
					// (Keep the first one stable, offset others)
					const seedBase = (displayEvent.name || '') + (displayEvent.city || '');
					const offset = getDeterministicOffset(seedBase);
					coords = [coords[0] + offset * 0.03, coords[1] + offset * 0.03];
				}

				const hasFutureEvent = subGroup.some(t => t.date >= today);
				const markerColor = hasFutureEvent ? colors.accent : "#888";
				const ids = subGroup.map(t => t.originalIndex);

				mapMarkers.push({
					name: `${displayEvent.name} (${displayEvent.city})`,
					coords: coords,
					style: { initial: { fill: markerColor, r: markerRadius, stroke: "#333", strokeWidth: 1 } },
					ids: ids
				});
			});
		});

		globalTermine = termine;
		globalMapMarkers = mapMarkers;

		populateList(termine);
		initMap(mapMarkers, termine);

		updateSearch('');

		// Search logic
		const searchInput = document.querySelector('.filter-panel .table-search');
		if (searchInput) {
			searchInput.addEventListener('input', debounce(function (e) {
				updateSearch(e.target.value);
			}, 150));
		}

		const clearButton = document.getElementById('clear-filter');
		if (clearButton) {
			clearButton.addEventListener('click', () => updateSearch(''));
		}

		const themeBtn = document.getElementById('theme-toggle');
		if (themeBtn) themeBtn.addEventListener('click', toggleTheme);

		document.addEventListener('keydown', (e) => {
			if (e.key === 'Escape') {
				document.getElementById('selection-overlay').style.display = 'none';
			}
		});

		document.addEventListener('click', (e) => {
			const overlay = document.getElementById('selection-overlay');
			if (overlay && overlay.style.display === 'block') {
				const isOverlay = e.target.closest('#selection-overlay');
				const isMarker = e.target.closest('.jvm-marker') || e.target.classList.contains('jvm-marker');
				const isCard = e.target.closest('.event-card');

				if (!isOverlay && !isMarker && !isCard) {
					overlay.style.display = 'none';
				}
			}
		});
	}

	window.addEventListener('DOMContentLoaded', loadData);
	window.addEventListener('resize', debounce(() => {
		if (globalMapMarkers) initMap(globalMapMarkers, globalTermine);
	}, 150));

})();
