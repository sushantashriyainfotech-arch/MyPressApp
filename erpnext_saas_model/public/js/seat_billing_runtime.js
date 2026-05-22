(function () {
	if (window.__erpnextSeatBillingRuntimeLoaded) return;
	window.__erpnextSeatBillingRuntimeLoaded = true;
	console.log('[Seat Billing] Script initialized');
	document.title = '[SB] ' + document.title;

	const state = {
		plans: [],
		selectedPlan: null,
		billableSeats: 1,
		panel: null,
		planGrid: null,
		step: 1, // 1: Plan selection, 2: Seat selection
	};

	const ROUTE_HINTS = ['sites/new', '/app/press/site/', '/overview', '/dashboard/sites/'];
	const MONTHLY_TEXT_RE = /\/day|\/mo|per day|per month/i;
	const DEBUG = true; // Set to false in production

	function log(...args) {
		if (DEBUG) console.log('[Seat Billing]', ...args);
	}

	// ── Debounce helper ────────────────────────────────────────────────────────
	function debounce(fn, delay) {
		let timer;
		return function (...args) {
			clearTimeout(timer);
			timer = setTimeout(() => fn.apply(this, args), delay);
		};
	}

	function normalize(value) {
		return String(value || '')
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '');
	}

	function isRelevantRoute() {
		const path = window.location.pathname || '';
		log('Checking route:', path);
		if (ROUTE_HINTS.some((hint) => path.includes(hint))) {
			log('Route matches hint');
			return true;
		}

		const bodyText = document.body?.innerText || '';
		return (
			bodyText.includes('Setup Subscription') ||
			bodyText.includes('Change Plan') ||
			bodyText.includes('Select Plan for')
		);
	}

	function currencySymbol() {
		const currency = window.frappe?.boot?.sysdefaults?.currency || 'USD';
		const symbols = window.frappe?.boot?.currency_symbols || {};
		return symbols[currency] || currency;
	}

	function formatCurrency(value) {
		const amount = Number(value || 0);
		const symbol = currencySymbol();

		if (window.format_currency) {
			return window.format_currency(amount, window.frappe?.boot?.sysdefaults?.currency);
		}

		return `${symbol}${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
	}

	function isSeatBased(plan) {
		return plan && plan.billing_type === 'Seat Based';
	}

	function clampSeats(plan, seats) {
		const minSeats = Number(plan?.min_seats || 1);
		const maxSeats = Number(plan?.max_seats || 0);
		let nextSeats = Number(seats || minSeats || 1);

		if (nextSeats < minSeats) nextSeats = minSeats;
		if (maxSeats && nextSeats > maxSeats) nextSeats = maxSeats;
		return nextSeats;
	}

	function findPlanByName(planName) {
		if (!planName) return null;
		const normalizedName = normalize(planName);
		return (
			state.plans.find((plan) => normalize(plan.name) === normalizedName) ||
			state.plans.find((plan) => normalize(plan.plan_title) === normalizedName) ||
			null
		);
	}

	function findPlanByText(text) {
		const normalizedText = normalize(text);
		if (!normalizedText) return null;

		return (
			state.plans.find((plan) => {
				const title = normalize(plan.plan_title);
				const name = normalize(plan.name);
				return (
					(normalizedText.includes(title) && title.length > 0) ||
					(normalizedText.includes(name) && name.length > 0)
				);
			}) || null
		);
	}

	async function loadPlans() {
		if (state.plans.length) return state.plans;

		const response = await fetch(
			'/api/method/erpnext_saas_model.api.site.get_site_plans',
			{ credentials: 'same-origin' },
		);
		const data = await response.json();
		state.plans = Array.isArray(data.message) ? data.message : [];
		return state.plans;
	}

	function getSelectedPlanFromGrid(grid) {
		if (!grid) return null;
		const buttons = Array.from(grid.querySelectorAll('button'));
		if (!buttons.length) return null;

		const selectedButton = buttons.find((button) =>
			/ring-1|border-outline-gray-5|ring-gray-900|border-gray-900|border-black|border-primary-|border-outline-primary/.test(
				button.className || '',
			),
		);

		log('Selected button:', selectedButton);
		if (!selectedButton) return null;

		const plan = findPlanByText(selectedButton.textContent || '');
		log('Found plan by text:', plan?.name || 'none');
		return plan;
	}

	function shouldShowWarning(plan, seats) {
		const maxSeats = Number(plan?.max_seats || 0);
		return Boolean(maxSeats && Number(seats || 0) > maxSeats);
	}

	function renderPanel() {
		if (!state.planGrid) return;
		if (!state.panel) {
			state.panel = document.createElement('div');
			state.panel.className =
				'erp-seat-billing-panel mt-4 rounded-lg border border-outline-gray-2 bg-surface-gray-1 p-4';
			state.panel.dataset.erpSeatBillingPanel = '1';
		}

		if (state.step === 1) {
			renderStep1();
		} else {
			renderStep2();
		}
	}

	function renderStep1() {
		if (!state.panel) return;
		state.planGrid.style.display = '';

		const plan = state.selectedPlan;
		if (!isSeatBased(plan)) {
			state.panel.style.display = 'none';
			if (!state.panel.isConnected) {
				state.planGrid.insertAdjacentElement('afterend', state.panel);
			}
			return;
		}

		state.panel.style.display = '';
		state.billableSeats = clampSeats(plan, state.billableSeats);

		state.panel.innerHTML = `
			<div class="flex items-start justify-between gap-4">
				<div>
					<div class="text-sm font-medium text-ink-gray-9">Seat billing available</div>
					<div class="text-xs text-ink-gray-6">Custom seat pricing will be applied in the next step.</div>
				</div>
				<div class="text-right">
					<button class="bg-surface-white border border-outline-gray-3 rounded px-3 py-1.5 text-sm font-medium hover:bg-surface-gray-1 transition-colors" data-role="next-step">
						Configure Seats
					</button>
				</div>
			</div>
		`;

		state.panel.querySelector('[data-role="next-step"]').onclick = () => {
			state.step = 2;
			renderPanel();
		};

		if (!state.panel.isConnected) {
			state.planGrid.insertAdjacentElement('afterend', state.panel);
		}
	}

	function renderStep2() {
		if (!state.panel) return;

		state.planGrid.style.display = 'none';
		state.panel.style.display = '';

		const plan = state.selectedPlan;
		state.billableSeats = clampSeats(plan, state.billableSeats);

		const minSeats = Number(plan.min_seats || 1);
		const maxSeats = Number(plan.max_seats || 0);
		const total = Number(state.billableSeats || 0) * Number(plan.price_per_seat || 0);

		const seatRangeText = maxSeats
			? `Min ${minSeats} seats · Up to ${maxSeats} seats`
			: `Min ${minSeats} seats`;
		const warningText = shouldShowWarning(plan, state.billableSeats)
			? plan.next_plan
				? `This plan supports up to ${maxSeats} seats. Consider upgrading to ${plan.next_plan}.`
				: `This plan supports up to ${maxSeats} seats.`
			: '';

		state.panel.innerHTML = `
			<div>
				<button class="text-xs text-ink-gray-6 hover:text-ink-gray-9 flex items-center gap-1 mb-4" data-role="back-to-plans">
					<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path></svg>
					Back to plans
				</button>
			</div>
			<div class="flex items-start justify-between gap-4">
				<div>
					<div class="text-base font-semibold text-ink-gray-9">${plan.plan_title}</div>
					<div class="text-sm font-medium text-ink-gray-9">Configure Seats</div>
					<div class="text-xs text-ink-gray-6" data-role="seat-range"></div>
				</div>
				<div class="text-right">
					<div class="text-xs text-ink-gray-6">Monthly total</div>
					<div class="text-xl font-bold text-ink-primary" data-role="seat-total"></div>
				</div>
			</div>
			<div class="mt-6 grid gap-4 sm:grid-cols-[160px_1fr] sm:items-center">
				<label class="text-sm font-medium text-ink-gray-8">How many seats?</label>
				<div class="flex items-center gap-2">
					<input
						type="number"
						min="${minSeats}"
						${maxSeats ? `max="${maxSeats}"` : ''}
						class="h-10 w-24 rounded border border-outline-gray-3 bg-surface-white px-3 text-base text-ink-gray-9 focus:border-outline-gray-4 focus:ring-0"
						data-role="seat-input"
					/>
					<span class="text-sm text-ink-gray-6">@ ${formatCurrency(plan.price_per_seat)} per seat</span>
				</div>
			</div>
			<div class="mt-4 text-sm text-ink-gray-6 bg-surface-gray-2 p-3 rounded border border-outline-gray-2">
				<strong>Billing details:</strong> Your base plan cost will be replaced by the seat-based total shown above.
			</div>
			<div class="mt-2 text-xs text-red-600" data-role="seat-warning"></div>
		`;

		state.panel.querySelector('[data-role="back-to-plans"]').onclick = () => {
			state.step = 1;
			renderPanel();
		};

		state.panel.querySelector('[data-role="seat-range"]').textContent = seatRangeText;
		state.panel.querySelector('[data-role="seat-total"]').textContent = formatCurrency(total);

		const warningEl = state.panel.querySelector('[data-role="seat-warning"]');
		warningEl.textContent = warningText;
		warningEl.style.display = warningText ? '' : 'none';

		const input = state.panel.querySelector('[data-role="seat-input"]');
		input.value = String(state.billableSeats || minSeats);
		input.oninput = () => {
			state.billableSeats = clampSeats(plan, input.value);
			input.value = String(state.billableSeats);
			// Update totals in-place without full re-render to avoid loop
			const newTotal = Number(state.billableSeats) * Number(plan.price_per_seat || 0);
			state.panel.querySelector('[data-role="seat-total"]').textContent = formatCurrency(newTotal);
			const newWarning = shouldShowWarning(plan, state.billableSeats)
				? plan.next_plan
					? `This plan supports up to ${maxSeats} seats. Consider upgrading to ${plan.next_plan}.`
					: `This plan supports up to ${maxSeats} seats.`
				: '';
			const w = state.panel.querySelector('[data-role="seat-warning"]');
			w.textContent = newWarning;
			w.style.display = newWarning ? '' : 'none';
		};

		if (!state.panel.isConnected) {
			state.planGrid.insertAdjacentElement('afterend', state.panel);
		}
	}

	// ── Fixed: only re-render when plan actually changes ──────────────────────
	function refreshSelection() {
		if (!state.planGrid) return;
		log('Refreshing selection...');
		const selected = getSelectedPlanFromGrid(state.planGrid);

		if (selected) {
			log('Current selection:', selected.name);
			if (state.selectedPlan?.name !== selected.name) {
				state.selectedPlan = selected;
				state.billableSeats = clampSeats(selected, 1);
				state.step = 1;
				log('Plan changed to:', selected.name);
				renderPanel(); // Only render on actual plan change
			}
		} else {
			log('No plan selected');
			if (state.selectedPlan !== null) {
				state.selectedPlan = null;
				state.step = 1;
				renderPanel(); // Only render on actual change
			}
		}
	}

	function findPlanGrid() {
		const dialogs = Array.from(document.querySelectorAll('.frappe-dialog, [role="dialog"]'));
		for (const dialog of dialogs) {
			const grid = findGridInContainer(dialog);
			if (grid) return grid;
		}
		return findGridInContainer(document.body);
	}

	function findGridInContainer(container) {
		const divs = Array.from(container.querySelectorAll('div'));
		for (const el of divs) {
			const buttons = Array.from(el.children).filter(
				(child) => child.tagName === 'BUTTON',
			);
			if (buttons.length < 2) continue;
			if (!buttons.some((button) => MONTHLY_TEXT_RE.test(button.textContent || ''))) {
				continue;
			}
			return el;
		}
		return null;
	}

	function bindPlanGrid(grid) {
		if (!grid || grid.dataset.erpSeatBillingBound === '1') return;
		grid.dataset.erpSeatBillingBound = '1';
		log('Binding to plan grid');
		grid.addEventListener(
			'click',
			() => {
				log('Grid clicked, scheduling refresh...');
				setTimeout(refreshSelection, 100);
			},
			true,
		);
	}

	function maybeMount() {
		if (!isRelevantRoute()) return;
		const grid = findPlanGrid();
		if (!grid) {
			if (state.planGrid) log('Plan grid lost');
			state.planGrid = null;
			state.selectedPlan = null;
			state.step = 1;
			return;
		}

		if (state.planGrid !== grid) {
			log('Found plan grid');
			state.planGrid = grid;
			bindPlanGrid(grid);
			refreshSelection();
		}
		// Removed: periodic refreshSelection() call here — was causing the loop
	}

	function updateRequestBody(url, body) {
		if (!body) return body;

		let parsed = body;
		if (typeof body === 'string') {
			try {
				parsed = JSON.parse(body);
			} catch (error) {
				return body;
			}
		} else if (typeof body !== 'object') {
			return body;
		}

		let planName =
			parsed?.site?.plan ||
			parsed?.plan ||
			parsed?.doc?.subscription_plan ||
			parsed?.doc?.plan;
		const plan = findPlanByName(planName);
		if (!isSeatBased(plan)) return body;

		const seats = clampSeats(plan, state.billableSeats);
		if (parsed.site) {
			parsed.site.billable_seats = seats;
		}
		if (parsed.doc && parsed.doc.doctype === 'Site') {
			parsed.doc.billable_seats = seats;
		}
		if (parsed.plan && !parsed.billable_seats) {
			parsed.billable_seats = seats;
		}
		if (parsed.subscription_plan && !parsed.billable_seats) {
			parsed.billable_seats = seats;
		}

		return typeof body === 'string' ? JSON.stringify(parsed) : parsed;
	}

	function patchFetch() {
		if (window.__erpnextSeatBillingFetchPatched) return;
		window.__erpnextSeatBillingFetchPatched = true;
		const originalFetch = window.fetch.bind(window);
		window.fetch = function (input, init) {
			try {
				const url =
					typeof input === 'string'
						? input
						: input && input.url
							? input.url
							: '';
				if (
					url.includes('press.api.site.new') ||
					url.includes('press.api.client.insert') ||
					url.includes('set_plan') ||
					url.includes('change_plan')
				) {
					init = init || {};
					init.body = updateRequestBody(url, init.body);
				}
			} catch (error) {
				// Leave the request untouched if interception fails.
			}
			return originalFetch(input, init);
		};
	}

	function patchXhr() {
		if (window.__erpnextSeatBillingXhrPatched) return;
		window.__erpnextSeatBillingXhrPatched = true;

		const originalOpen = XMLHttpRequest.prototype.open;
		const originalSend = XMLHttpRequest.prototype.send;

		XMLHttpRequest.prototype.open = function (method, url) {
			this.__erpnextSeatBillingUrl = url || '';
			return originalOpen.apply(this, arguments);
		};

		XMLHttpRequest.prototype.send = function (body) {
			try {
				if (
					(this.__erpnextSeatBillingUrl || '').includes('set_plan') ||
					(this.__erpnextSeatBillingUrl || '').includes('change_plan') ||
					(this.__erpnextSeatBillingUrl || '').includes('press.api.site.new') ||
					(this.__erpnextSeatBillingUrl || '').includes('press.api.client.insert')
				) {
					body = updateRequestBody(this.__erpnextSeatBillingUrl, body);
				}
			} catch (error) {
				// Ignore and keep the original body.
			}
			return originalSend.call(this, body);
		};
	}

	function interceptDialogButtons() {
		if (!isSeatBased(state.selectedPlan)) return;

		const dialogs = Array.from(document.querySelectorAll('.frappe-dialog, [role="dialog"]'));
		for (const dialog of dialogs) {
			const buttons = Array.from(dialog.querySelectorAll('button'));
			const primaryButton = buttons.find(b =>
				b.textContent.includes('Select Plan') ||
				b.textContent.includes('Change Plan') ||
				b.textContent.includes('Setup Subscription')
			);

			if (primaryButton) {
				if (state.step === 1) {
					primaryButton.disabled = true;
					primaryButton.title = 'Please configure seats first';
				} else {
					primaryButton.disabled = false;
					primaryButton.title = '';
				}
			}
		}
	}

	// ── Fixed: debounced observer that ignores our own panel mutations ─────────
	function observe() {
		const refresh = debounce(() => {
			maybeMount();
			interceptDialogButtons();
		}, 150);

		const observer = new MutationObserver((mutations) => {
			// Ignore mutations caused by our own panel to prevent infinite render loop
			const isOwnMutation = mutations.every(m =>
				state.panel && (
					state.panel.contains(m.target) ||
					m.target === state.panel
				)
			);
			if (isOwnMutation) return;
			refresh();
		});

		observer.observe(document.documentElement, {
			childList: true,
			subtree: true,
		});

		window.addEventListener('popstate', refresh);
		window.addEventListener('erpnext-seat-billing:navigation', refresh);

		const originalPushState = history.pushState;
		const originalReplaceState = history.replaceState;

		history.pushState = function () {
			originalPushState.apply(this, arguments);
			window.dispatchEvent(new Event('erpnext-seat-billing:navigation'));
		};
		history.replaceState = function () {
			originalReplaceState.apply(this, arguments);
			window.dispatchEvent(new Event('erpnext-seat-billing:navigation'));
		};
	}

	async function init() {
		patchFetch();
		patchXhr();
		observe();

		try {
			await loadPlans();
		} catch (error) {
			// If plan data fails to load, keep the runtime no-op rather than breaking Desk.
			return;
		}

		maybeMount();
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', init, { once: true });
	} else {
		init();
	}
})();
