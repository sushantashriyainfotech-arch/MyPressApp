(function () {
	if (window.__erpnextSeatBillingRuntimeLoaded) return;
	window.__erpnextSeatBillingRuntimeLoaded = true;

	const state = {
		plans: [],
		selectedPlan: null,
		billableSeats: 1,
		panel: null,
		planGrid: null,
	};

	const ROUTE_HINTS = ['sites/new', '/app/site/'];
	const MONTHLY_TEXT_RE = /\/day|\/mo|per day|per month/i;

	function normalize(value) {
		return String(value || '')
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '');
	}

	function isRelevantRoute() {
		const path = window.location.pathname || '';
		if (ROUTE_HINTS.some((hint) => path.includes(hint))) return true;

		const bodyText = document.body?.innerText || '';
		return bodyText.includes('Setup Subscription') || bodyText.includes('Change Plan');
	}

	function currencySymbol() {
		const currency = window.frappe?.boot?.sysdefaults?.currency || 'USD';
		return currency === 'INR' ? '₹' : '$';
	}

	function formatCurrency(value) {
		const amount = Number(value || 0);
		return `${currencySymbol()}${amount.toFixed(2)}`;
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
			{
				credentials: 'same-origin',
			},
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
			/ring-1|border-outline-gray-5|ring-gray-900/.test(
				button.className || '',
			),
		);

		if (!selectedButton) return null;

		return findPlanByText(selectedButton.textContent || '');
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
			<div class="flex items-start justify-between gap-4">
				<div>
					<div class="text-sm font-medium text-ink-gray-9">Seat billing</div>
					<div class="text-xs text-ink-gray-6" data-role="seat-range"></div>
				</div>
				<div class="text-right">
					<div class="text-xs text-ink-gray-6">Monthly total</div>
					<div class="text-base font-semibold text-ink-gray-9" data-role="seat-total"></div>
				</div>
			</div>
			<div class="mt-3 grid gap-3 sm:grid-cols-[160px_1fr] sm:items-center">
				<label class="text-sm font-medium text-ink-gray-8">Billable seats</label>
				<input
					type="number"
					min="${minSeats}"
					${maxSeats ? `max="${maxSeats}"` : ''}
					class="h-9 rounded border border-outline-gray-3 bg-surface-white px-3 text-base text-ink-gray-9 focus:border-outline-gray-4 focus:ring-0"
					data-role="seat-input"
				/>
			</div>
			<div class="mt-2 text-xs text-ink-gray-6" data-role="seat-pricing"></div>
			<div class="mt-2 text-xs text-red-600" data-role="seat-warning"></div>
		`;

		state.panel.querySelector('[data-role="seat-range"]').textContent = seatRangeText;
		state.panel.querySelector('[data-role="seat-total"]').textContent =
			formatCurrency(total);
		state.panel.querySelector('[data-role="seat-pricing"]').textContent = `${formatCurrency(
			plan.price_per_seat,
		)} per seat`;
		const warningEl = state.panel.querySelector('[data-role="seat-warning"]');
		warningEl.textContent = warningText;
		warningEl.style.display = warningText ? '' : 'none';

		const input = state.panel.querySelector('[data-role="seat-input"]');
		input.value = String(state.billableSeats || minSeats);
		input.addEventListener('input', () => {
			state.billableSeats = clampSeats(plan, input.value);
			input.value = String(state.billableSeats);
			renderPanel();
		});

		if (!state.panel.isConnected) {
			state.planGrid.insertAdjacentElement('afterend', state.panel);
		}
	}

	function refreshSelection() {
		if (!state.planGrid) return;
		const selected = getSelectedPlanFromGrid(state.planGrid);
		if (selected) {
			state.selectedPlan = selected;
			state.billableSeats = clampSeats(selected, state.billableSeats);
		}
		renderPanel();
	}

	function findPlanGrid() {
		const divs = Array.from(document.querySelectorAll('div'));
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
		grid.addEventListener(
			'click',
			() => {
				setTimeout(refreshSelection, 0);
			},
			true,
		);
	}

	function maybeMount() {
		if (!isRelevantRoute()) return;
		const grid = findPlanGrid();
		if (!grid) return;

		state.planGrid = grid;
		bindPlanGrid(grid);
		refreshSelection();
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

	function observe() {
		const refresh = () => {
			maybeMount();
		};

		const observer = new MutationObserver(refresh);
		observer.observe(document.documentElement, {
			childList: true,
			subtree: true,
		});

		window.addEventListener('popstate', refresh);
		window.addEventListener('erpnext-seat-billing:navigation', refresh);

		const originalPushState = history.pushState;
		const originalReplaceState = history.replaceState;

		history.pushState = function () {
			const result = originalPushState.apply(this, arguments);
			window.dispatchEvent(new Event('erpnext-seat-billing:navigation'));
			return result;
		};
		history.replaceState = function () {
			const result = originalReplaceState.apply(this, arguments);
			window.dispatchEvent(new Event('erpnext-seat-billing:navigation'));
			return result;
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
