(function () {
	// Load once per page. The runtime is injected after the dashboard boot data,
	// then waits for DOM readiness before wiring itself into the page.
	if (window.__erpnextSeatBillingRuntimeLoaded) return;
	window.__erpnextSeatBillingRuntimeLoaded = true;
	console.log('[Seat Billing] Script initialized');
	document.title = '[SB] ' + document.title;

	function getDashboardBrandName() {
		return (
			(document.title || '')
				.replace(/^\[SB\]\s*/i, '')
				.replace(/\s*Dashboard$/i, '')
				.trim() || 'Frappe Cloud'
		);
	}

	function syncSidebarBrandName() {
		const sidebarBrand = document.querySelector(
			'aside button .text-base.font-medium.hidden.md\\:flex.text-ink-gray-9',
		);
		if (!sidebarBrand) return false;

		sidebarBrand.textContent = getDashboardBrandName();
		return true;
	}

	const sidebarBrandObserver = new MutationObserver(() => {
		if (syncSidebarBrandName()) {
			sidebarBrandObserver.disconnect();
		}
	});

	sidebarBrandObserver.observe(document.documentElement, {
		childList: true,
		subtree: true,
	});
	syncSidebarBrandName();

	// ─────────────────────────────────────────────────────────────────────────────
	// State & constants
	// ─────────────────────────────────────────────────────────────────────────────
	const state = {
		plans: [],
		selectedPlan: null,
		billableSeats: 1,
		activeSubscription: null,
		activeSubscriptionContext: null,
		panel: null,
		planGrid: null,
		planGridDialog: null,
		planGridDialogCloseBound: false,
		step: 1, // 1: Plan selection, 2: Seat selection
		currency: null,
		country: null,
	};

	const ROUTE_HINTS = ['/app/press/site/', '/overview', '/dashboard/sites/'];
	const EXCLUDED_ROUTE_HINTS = ['/dashboard/create-site/*'];
	const MONTHLY_TEXT_RE = /\/day|\/mo|per day|per month/i;
	const DEBUG = true;

	function log(...args) {
		if (DEBUG) console.log('[Seat Billing]', ...args);
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Generic utilities
	// ─────────────────────────────────────────────────────────────────────────────
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

	function parseMaybeJSON(value) {
		if (value == null || value === '') return null;
		if (typeof value === 'object') return value;
		try {
			return JSON.parse(value);
		} catch (error) {
			return null;
		}
	}

	function parseMaybeJSONSafe(value) {
		if (value == null || value === '') return null;
		if (typeof value === 'object') return value;
		try {
			return JSON.parse(value);
		} catch (error) {
			return null;
		}
	}

	function isVisibleElement(el) {
		if (!el || !el.isConnected) return false;
		if (typeof el.getAttribute === 'function' && el.getAttribute('data-state') && el.getAttribute('data-state') !== 'open') {
			return false;
		}
		const style = window.getComputedStyle(el);
		if (style.display === 'none' || style.visibility === 'hidden') return false;
		return true;
	}

	function isExcludedRoute() {
		const path = window.location.pathname || '';
		return EXCLUDED_ROUTE_HINTS.some((hint) => {
			if (hint.includes('*')) {
				const escaped = hint.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
				const regex = new RegExp('^' + escaped + '$');
				return regex.test(path);
			}
			return path.includes(hint);
		});
	}

	function isRelevantRoute() {
		if (isExcludedRoute()) {
			log('Route is excluded');
			return false;
		}

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

	function formatCurrency(value) {
		const amount = Number(value || 0);
		const currency = state.currency || 'USD';
		const locale = currency === 'INR' ? 'en-IN' : 'en-US';

		log('Formatting currency with locale:', locale, 'and currency:', currency);
		log('Formatting currency:', amount, currency);

		if (window.format_currency) {
			return window.format_currency(amount, currency);
		}

		return new Intl.NumberFormat(locale, {
			style: 'currency',
			currency,
			currencyDisplay: 'symbol',
		}).format(amount);
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Team locale
	// ─────────────────────────────────────────────────────────────────────────────
	async function getCurrentTeamData() {
		try {
			const currentTeam = localStorage.getItem('current_team') || '';
			const url = currentTeam
				? `/api/method/press.api.team.get_current_team_locale?team_name=${encodeURIComponent(currentTeam)}`
				: '/api/method/press.api.team.get_current_team_locale';
			const res = await fetch(url, {
				credentials: 'same-origin',
			});
			const data = await res.json();
			log('Fetched team data:', data?.message);
			return data?.message;
		} catch {
			console.error('Failed to fetch team data');
			return;
		}
	}

	async function loadLocale() {
		if (state.country && state.currency) return;
		const data = await getCurrentTeamData();
		state.country = data?.country || state.country;
		state.currency = data?.currency || state.currency;
		log('Locale loaded:', { country: state.country, currency: state.currency });
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Plans & subscriptions
	// ─────────────────────────────────────────────────────────────────────────────
	function isSeatBased(plan) {
		return plan && plan.billing_type === 'Seat Based';
	}

	function clampSeats(plan, seats) {
		const minSeats = Number(plan?.min_seats || 1);
		let nextSeats = Number(seats || minSeats || 1);
		if (nextSeats < minSeats) nextSeats = minSeats;
		return nextSeats;
	}

	function getActiveUserCount() {
		return Number(
			state.activeSubscriptionContext?.active_user_count ||
			state.activeSubscriptionContext?.current?.active_user_count ||
			0,
		);
	}

	function getInitialSeatCount(plan) {
		const activeSubscriptionSeats = Number(
			state.activeSubscriptionContext?.billable_seats ||
			state.activeSubscriptionContext?.subscription?.billable_seats ||
			state.activeSubscriptionContext?.current?.billable_seats ||
			0,
		);
		return Math.max(Number(plan?.min_seats || 1), activeSubscriptionSeats);
	}

	function getPlanSeatPrice(plan) {
		if (!plan) return 0;
		return state.currency === 'INR'
			? Number(plan.price_inr || plan.price_usd || 0)
			: Number(plan.price_usd || plan.price_inr || 0);
	}

	function findPlanByBillingType(billingType, fallbackPlanName = null) {
		if (!fallbackPlanName) return null;

		const normalizedName = normalize(fallbackPlanName);
		const candidate = state.plans.find((plan) => normalize(plan.name) === normalizedName);
		if (!candidate) {
			return null;
		}

		if (billingType) {
			const normalizedBillingType = normalize(billingType);
			if (normalizedBillingType && normalize(candidate.billing_type) !== normalizedBillingType) {
				return null;
			}
		}

		return candidate;
	}

	function decoratePlanCards(grid) {
		if (!grid || !Array.isArray(state.plans) || !state.plans.length) return;

		const buttons = Array.from(grid.querySelectorAll('button')).filter((button) =>
			MONTHLY_TEXT_RE.test(button.textContent || ''),
		);

		buttons.forEach((button, index) => {
			const plan = state.plans[index];
			if (!plan) return;

			const seatBased = isSeatBased(plan);
			button.dataset.planName = plan.name;
			button.dataset.billingType = seatBased ? 'Seat Based' : 'Resource Based';

			const badgeText = seatBased ? 'Seat Based' : 'Resource Based';
			if (seatBased && !button.dataset.seatPricingAdjusted) {
				button.innerHTML = button.innerHTML.replace('/mo', '/seat/mo');
				button.dataset.seatPricingAdjusted = '1';
			}
			let badgeEl = button.querySelector('[data-role="plan-badge"]');
			if (!badgeEl) {
				badgeEl = document.createElement('div');
				badgeEl.dataset.role = 'plan-badge';
				button.prepend(badgeEl);
			}
			badgeEl.className = `erp-seat-billing-plan-badge pointer-events-none flex w-full items-center justify-start rounded-t-md rounded-b-none px-3 py-1 text-[10px] font-semibold leading-none tracking-wide ${seatBased
				? 'border-b border-ink-gray-9 bg-ink-gray-9 text-gray-9 shadow-sm'
				: 'border-b border-outline-gray-2 bg-surface-gray-1 text-ink-gray-5'
				}`;
			badgeEl.style.display = 'flex';
			badgeEl.style.width = '100%';
			badgeEl.style.margin = '0';
			badgeEl.textContent = badgeText;

			const normalizedText = normalize(button.textContent || '');
			if (normalizedText.includes(normalize(plan.name)) || normalizedText.includes(normalize(plan.plan_title))) return;
		});
	}

	async function loadPlans() {
		if (state.plans.length) return state.plans;
		const response = await fetch('/api/method/press.api.site.get_site_plans', {
			credentials: 'same-origin',
		});
		const data = await response.json();
		state.plans = Array.isArray(data.message) ? data.message : [];
		return state.plans;
	}

	async function loadCurrentSubscription() {
		if (state.activeSubscriptionContext) {
			log('Active subscription context already loaded', state.activeSubscriptionContext);
			return state.activeSubscriptionContext;
		}

		const site = getCurrentManagedSite();
		if (!site) {
			log('No managed site found in boot data');
			return null;
		}

		try {
			const response = await fetch(
				`/api/method/press.api.site.get_current_subscription_context?site=${encodeURIComponent(site)}`,
				{ credentials: 'same-origin' },
			);
			const data = await response.json();
			state.activeSubscription = data?.message?.subscription || null;
			state.activeSubscriptionContext = data?.message?.current || null;
			log('Loaded active subscription context:', {
				site,
				subscription: state.activeSubscription,
				context: state.activeSubscriptionContext,
			});
			return state.activeSubscriptionContext;
		} catch (error) {
			log('Failed to load active subscription context', error);
			return null;
		}
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Plan grid discovery and rendering
	// ─────────────────────────────────────────────────────────────────────────────
	function getCurrentManagedSite() {
		const path = window.location.pathname || '';
		const match = path.match(/\/dashboard\/sites\/([^/]+)(?:\/|$)/);
		if (match?.[1]) {
			log('Resolved managed site from route:', match[1]);
			return match[1];
		}

		const bootSite =
			window.site_name ||
			window.press_site_name ||
			window.frappe?.boot?.site_name ||
			window.frappe?.boot?.sitename ||
			window.frappe?.boot?.site ||
			null;

		if (bootSite) {
			log('Resolved managed site from boot data:', bootSite);
			return bootSite;
		}

		return null;
	}

	function isManagedSiteOverviewRoute() {
		return /\/dashboard\/sites\/[^/]+\/overview(?:\/|$)/.test(window.location.pathname || '');
	}

	function getVisibleModalContainers() {
		return Array.from(
			document.querySelectorAll('[data-dismissable-layer][role="dialog"], [role="dialog"][data-dismissable-layer], [role="dialog"], .modal.show, .modal[style*="display: block"], .modal-dialog, .modal-content'),
		).filter(isVisibleElement);
	}

	function findGridInContainer(container) {
		const divs = Array.from(container.querySelectorAll('div'));
		for (const el of divs) {
			const buttons = Array.from(el.children).filter((child) => child.tagName === 'BUTTON');
			if (buttons.length < 2) continue;
			if (!buttons.some((button) => MONTHLY_TEXT_RE.test(button.textContent || ''))) continue;
			return el;
		}
		return null;
	}

	function findPlanGrid() {
		const dialogs = getVisibleModalContainers();
		for (const dialog of dialogs) {
			if (!isVisibleElement(dialog)) continue;
			const grid = findGridInContainer(dialog);
			if (grid) return grid;
		}
		return findGridInContainer(document.body);
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

		const plan = findPlanByBillingType(
			selectedButton.dataset?.billingType || '',
			selectedButton.dataset?.planName || '',
		);
		log('Found plan by billing type:', plan?.name || 'none');
		return plan;
	}

	function shouldShowWarning(plan, seats) {
		const maxSeats = Number(plan?.max_seats || 0);
		return Boolean(maxSeats && Number(seats || 0) > maxSeats);
	}

	function getEffectiveSeatPrice(plan, seats) {
		return getPlanSeatPrice(plan) * Number(seats || 0);
	}

	function renderPanel() {
		if (!state.planGrid) return;
		if (!state.panel) {
			state.panel = document.createElement('div');
			state.panel.className = 'erp-seat-billing-panel mt-4 rounded-lg border border-outline-gray-2 bg-surface-gray-1 p-4';
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
		state.panel.style.display = 'none';

		if (!state.panel.isConnected) {
			state.planGrid.insertAdjacentElement('afterend', state.panel);
		}
	}

	function renderStep2() {
		if (!state.panel) return;

		state.planGrid.style.display = '';
		state.panel.style.display = '';

		const plan = state.selectedPlan;
		const activeUserCount = getActiveUserCount();
		const activeSubscriptionSeats = Number(
			state.activeSubscriptionContext?.billable_seats ||
			state.activeSubscriptionContext?.subscription?.billable_seats ||
			state.activeSubscriptionContext?.current?.billable_seats ||
			0,
		);
		const initialSeats = getInitialSeatCount(plan);
		state.billableSeats = clampSeats(plan, state.billableSeats || initialSeats);

		const minSeats = Number(plan.min_seats || 1);
		const maxSeats = Number(plan.max_seats || 0);
		const selectedPrice = getPlanSeatPrice(plan);
		const total = Number(state.billableSeats || 0) * Number(selectedPrice || 0);
		const currentSubscriptionAmount = Number(
			state.activeSubscriptionContext?.total_amount ||
			state.activeSubscriptionContext?.current?.total_amount ||
			state.activeSubscriptionContext?.amount ||
			state.activeSubscriptionContext?.current?.amount ||
			0,
		);
		const currentSubscriptionText = state.activeSubscriptionContext
			? `Current subscription seats: ${activeSubscriptionSeats || initialSeats} · Active users: ${activeUserCount} · Total: ${formatCurrency(currentSubscriptionAmount)}`
			: `Defaulting to plan minimum of ${initialSeats}`;

		const seatRangeText = maxSeats ? `Min ${minSeats} seats · Up to ${maxSeats} seats` : `Min ${minSeats} seats`;
		const warningText = shouldShowWarning(plan, state.billableSeats)
			? plan.next_plan
				? `This plan supports up to ${maxSeats} seats. Please upgrade to ${plan.next_plan} to continue.`
				: `This plan supports up to ${maxSeats} seats. Please upgrade to a higher plan to continue.`
			: '';

		state.panel.innerHTML = `
			<div class="flex items-start justify-between gap-4">
				<div>
					<div class="text-base font-semibold text-ink-gray-9">${plan.plan_title || plan.name}</div>
					<div class="text-sm font-medium text-ink-gray-9">Configure Seats</div>
					<div class="text-xs text-ink-gray-6" data-role="seat-range"></div>
					<div class="text-xs text-ink-gray-6 mt-1">${currentSubscriptionText}</div>
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
						class="h-10 w-24 rounded border border-outline-gray-3 bg-surface-white px-3 text-base text-ink-gray-9 focus:border-outline-gray-4 focus:ring-0"
						data-role="seat-input"
					/>
					<span class="text-sm text-ink-gray-6">@ ${formatCurrency(selectedPrice)} per seat</span>
				</div>
			</div>
			<div class="mt-4 text-sm text-ink-gray-6 bg-surface-gray-2 p-3 rounded border border-outline-gray-2">
				<strong>Billing details:</strong> Your base plan cost will be replaced by the seat-based total shown above.
			</div>
			<div class="mt-2 text-xs text-red-600" data-role="seat-warning"></div>
		`;

		state.panel.querySelector('[data-role="seat-range"]').textContent = seatRangeText;
		state.panel.querySelector('[data-role="seat-total"]').textContent = formatCurrency(total);

		const warningEl = state.panel.querySelector('[data-role="seat-warning"]');
		warningEl.textContent = warningText;
		warningEl.style.display = warningText ? '' : 'none';

		const input = state.panel.querySelector('[data-role="seat-input"]');
		input.min = String(minSeats);
		input.value = String(state.billableSeats || minSeats);
		input.oninput = () => {
			const floorSeats = minSeats;
			state.billableSeats = Math.max(Number(input.value || 0), floorSeats);
			input.value = String(state.billableSeats);
			const newTotal = Number(state.billableSeats) * Number(selectedPrice || 0);
			state.panel.querySelector('[data-role="seat-total"]').textContent = formatCurrency(newTotal);
			const newWarning = shouldShowWarning(plan, state.billableSeats)
				? plan.next_plan
					? `This plan supports up to ${maxSeats} seats. Please upgrade to ${plan.next_plan} to continue.`
					: `This plan supports up to ${maxSeats} seats. Please upgrade to a higher plan to continue.`
				: '';
			const w = state.panel.querySelector('[data-role="seat-warning"]');
			w.textContent = newWarning;
			w.style.display = newWarning ? '' : 'none';
		};

		if (!state.panel.isConnected) {
			state.planGrid.insertAdjacentElement('afterend', state.panel);
		}
	}

	function resetPanel() {
		if (!state.panel) return;
		state.panel.style.display = 'none';
		state.panel.innerHTML = '';
	}

	function clearPlanGridAlerts(scope = null) {
		const root = scope || state.planGridDialog || getPlanGridDialog();
		if (!root) return;

		const alerts = Array.from(root.querySelectorAll('[role="alert"]'));
		for (const alert of alerts) {
			const text = (alert.textContent || '').trim();
			if (
				text.includes('active users') ||
				text.includes('deactivate users before reducing your seat count') ||
				text.includes('billable seat limit')
			) {
				alert.remove();
			}
		}
	}

	function bindPlanGridDialog() {
		if (state.planGridDialogCloseBound) return;
		state.planGridDialogCloseBound = true;

		const clearOnClose = (dialog) => {
			window.setTimeout(() => clearPlanGridAlerts(dialog), 0);
			window.setTimeout(() => clearPlanGridAlerts(dialog), 250);
		};

		document.addEventListener(
			'click',
			(event) => {
				const button = event.target?.closest?.('button');
				if (!isDialogCloseButton(button)) return;
				const dialog = button.closest('[data-dismissable-layer][role="dialog"], [role="dialog"][data-dismissable-layer], [role="dialog"]');
				clearOnClose(dialog || state.planGridDialog || getPlanGridDialog());
			},
			true,
		);
	}

	function getPlanGridDialog(grid = state.planGrid) {
		if (!grid) return null;
		return (
			grid.closest('[data-dismissable-layer][role="dialog"]') ||
			grid.closest('[role="dialog"][data-dismissable-layer]') ||
			grid.closest('[role="dialog"]') ||
			grid.closest('[data-dismissable-layer]') ||
			null
		);
	}

	function isDialogCloseButton(button) {
		if (!button || button.tagName !== 'BUTTON') return false;
		if (button.dataset?.role === 'seat-billing-ignore-close') return false;
		return Boolean(button.querySelector('svg.lucide-x, svg[class*="lucide-x"], svg path[d="M18 6 6 18"], svg path[d="m6 6 12 12"]'));
	}

	function refreshSelection() {
		if (!state.planGrid) return;
		log('Refreshing selection...');
		decoratePlanCards(state.planGrid);
		const selected = getSelectedPlanFromGrid(state.planGrid);

		if (selected) {
			log('Current selection:', selected.name);
			const initialSeats = getInitialSeatCount(selected);
			if (state.selectedPlan?.name !== selected.name) {
				state.selectedPlan = selected;
				state.billableSeats = clampSeats(selected, initialSeats);
				state.step = isSeatBased(selected) ? 2 : 1;
				log('Plan changed to:', selected.name);
				renderPanel();
			}
			if (state.selectedPlan && isSeatBased(state.selectedPlan) && state.step !== 2) {
				state.step = 2;
				renderPanel();
			}
		} else {
			log('No plan selected');
			if (state.selectedPlan !== null) {
				state.selectedPlan = null;
				state.step = 1;
				resetPanel();
				clearPlanGridAlerts();
				renderPanel();
			}
		}
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

	async function maybeMount() {
		if (!isRelevantRoute()) return;

		try {
			await Promise.all([loadPlans(), loadLocale()]);
		} catch (error) {
			return;
		}

		if (isManagedSiteOverviewRoute() && !state.activeSubscriptionContext) {
			loadCurrentSubscription();
		}

		patchFetch();
		patchXhr();

		const grid = findPlanGrid();
		if (!grid) {
			if (state.planGrid) log('Plan grid lost');
			resetPanel();
			clearPlanGridAlerts();
			state.planGrid = null;
			state.planGridDialog = null;
			state.selectedPlan = null;
			state.step = 1;
			return;
		}

		const modal = getPlanGridDialog(grid);
		if (!isVisibleElement(grid) || (modal && !isVisibleElement(modal))) {
			if (state.planGrid) log('Plan grid hidden');
			resetPanel();
			clearPlanGridAlerts(modal);
			state.planGrid = null;
			state.planGridDialog = null;
			state.selectedPlan = null;
			state.step = 1;
			return;
		}

		if (state.planGrid !== grid) {
			log('Found plan grid');
			state.planGrid = grid;
			state.planGridDialog = modal;
			bindPlanGridDialog();
			bindPlanGrid(grid);
			refreshSelection();
		}
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Network interception
	// ─────────────────────────────────────────────────────────────────────────────
	function updateSeatBillingPayloadObject(payload, seats, effectivePriceInr, effectivePriceUsd) {
		if (!payload || typeof payload !== 'object') return false;

		let mutated = false;
		if (payload.site && typeof payload.site === 'object') {
			payload.site.billable_seats = seats;
			payload.site.price_inr = effectivePriceInr;
			payload.site.price_usd = effectivePriceUsd;
			mutated = true;
		}
		if (payload.doc && payload.doc.doctype === 'Site' && typeof payload.doc === 'object') {
			payload.doc.billable_seats = seats;
			payload.doc.price_inr = effectivePriceInr;
			payload.doc.price_usd = effectivePriceUsd;
			mutated = true;
		}
		if (!payload.args || typeof payload.args !== 'object') {
			payload.args = {};
		}
		payload.args.billable_seats = seats;
		payload.args.price_inr = effectivePriceInr;
		payload.args.price_usd = effectivePriceUsd;
		mutated = true;

		if (payload.plan && !payload.billable_seats) {
			payload.billable_seats = seats;
			payload.price_inr = effectivePriceInr;
			mutated = true;
		}
		if (payload.subscription_plan && !payload.billable_seats) {
			payload.billable_seats = seats;
			payload.price_inr = effectivePriceInr;
			mutated = true;
		}

		return mutated;
	}

	function updateRequestBody(url, body) {
		if (!body) return body;

		const bodyIsString = typeof body === 'string';
		const bodyIsSearchParams = typeof URLSearchParams !== 'undefined' && body instanceof URLSearchParams;
		const bodyIsFormData = typeof FormData !== 'undefined' && body instanceof FormData;
		let parsed = body;

		if (bodyIsString) {
			try {
				parsed = JSON.parse(body);
			} catch (error) {
				parsed = new URLSearchParams(body);
			}
		} else if (!bodyIsSearchParams && !bodyIsFormData && typeof body !== 'object') {
			return body;
		}

		const nestedArgs = parseMaybeJSON(bodyIsSearchParams ? parsed.get('args') : parsed?.args);
		const nestedDocs = parseMaybeJSON(bodyIsSearchParams ? parsed.get('docs') : parsed?.docs);

		const planName =
			parsed?.site?.plan ||
			parsed?.plan ||
			parsed?.doc?.subscription_plan ||
			parsed?.doc?.plan ||
			nestedArgs?.plan ||
			nestedArgs?.subscription_plan ||
			nestedDocs?.subscription_plan ||
			nestedDocs?.plan;
		const plan = findPlanByBillingType(
			parsed?.billing_type ||
			nestedArgs?.billing_type ||
			nestedDocs?.billing_type ||
			(state.selectedPlan && state.selectedPlan.billing_type) ||
			'',
			planName || state.selectedPlan?.name || '',
		);

		if (!isSeatBased(plan)) {
			if (bodyIsSearchParams) {
				parsed.delete('billable_seats');
				parsed.delete('price_usd');
				const args = parseMaybeJSON(parsed.get('args'));
				if (args) {
					delete args.billable_seats;
					delete args.price_usd;
					parsed.set('args', JSON.stringify(args));
				}
				const docs = parseMaybeJSON(parsed.get('docs'));
				if (docs) {
					delete docs.billable_seats;
					delete docs.price_usd;
					parsed.set('docs', JSON.stringify(docs));
				}
				return parsed.toString();
			}

			if (bodyIsFormData) {
				parsed.delete('billable_seats');
				parsed.delete('price_usd');
				const args = parseMaybeJSON(parsed.get('args'));
				if (args) {
					delete args.billable_seats;
					delete args.price_usd;
					parsed.set('args', JSON.stringify(args));
				}
				const docs = parseMaybeJSON(parsed.get('docs'));
				if (docs) {
					delete docs.billable_seats;
					delete docs.price_usd;
					parsed.set('docs', JSON.stringify(docs));
				}
				return parsed;
			}

			if (bodyIsString) {
				try {
					const obj = JSON.parse(body);
					delete obj.billable_seats;
					delete obj.price_usd;
					if (obj.args) {
						delete obj.args.billable_seats;
						delete obj.args.price_usd;
					}
					if (obj.doc) {
						delete obj.doc.billable_seats;
						delete obj.doc.price_usd;
					}
					if (obj.site) {
						delete obj.site.billable_seats;
						delete obj.site.price_usd;
					}
					return JSON.stringify(obj);
				} catch (e) {
					return body;
				}
			}

			const cloned = JSON.parse(JSON.stringify(parsed));
			delete cloned.billable_seats;
			delete cloned.price_usd;
			if (cloned.args) {
				delete cloned.args.billable_seats;
				delete cloned.args.price_usd;
			}
			return cloned;
		}

		const seats = clampSeats(plan, state.billableSeats);
		const effectivePriceInr = Number(plan?.price_inr || 0);
		const effectivePriceUsd = Number(plan?.price_usd || 0);
		const effectiveSelectedPrice = getPlanSeatPrice(plan);

		if (bodyIsSearchParams) {
			let mutated = false;
			if (nestedArgs) {
				nestedArgs.billable_seats = seats;
				nestedArgs.price_inr = effectivePriceInr;
				nestedArgs.price_usd = effectivePriceUsd;
				parsed.set('args', JSON.stringify(nestedArgs));
				mutated = true;
			}
			if (nestedDocs && nestedDocs.doctype === 'Site') {
				nestedDocs.billable_seats = seats;
				nestedDocs.price_inr = effectivePriceInr;
				nestedDocs.price_usd = effectivePriceUsd;
				parsed.set('docs', JSON.stringify(nestedDocs));
				mutated = true;
			}
			if (!mutated) return body;
			return parsed.toString();
		}

		if (bodyIsFormData) {
			let mutated = false;
			if (nestedArgs) {
				nestedArgs.billable_seats = seats;
				nestedArgs.price_inr = effectivePriceInr;
				nestedArgs.price_usd = effectivePriceUsd;
				parsed.set('args', JSON.stringify(nestedArgs));
				mutated = true;
			}
			if (nestedDocs && nestedDocs.doctype === 'Site') {
				nestedDocs.billable_seats = seats;
				nestedDocs.price_inr = effectivePriceInr;
				nestedDocs.price_usd = effectivePriceUsd;
				parsed.set('docs', JSON.stringify(nestedDocs));
				mutated = true;
			}
			return mutated ? parsed : body;
		}

		if (bodyIsString) {
			if (typeof parsed === 'string') {
				return body;
			}

			if (parsed instanceof URLSearchParams) {
				let mutated = false;
				if (nestedArgs) {
					nestedArgs.billable_seats = seats;
					nestedArgs.price_inr = effectivePriceInr;
					nestedArgs.price_usd = effectivePriceUsd;
					parsed.set('args', JSON.stringify(nestedArgs));
					mutated = true;
				}
				if (nestedDocs && nestedDocs.doctype === 'Site') {
					nestedDocs.billable_seats = seats;
					nestedDocs.price_inr = effectivePriceInr;
					nestedDocs.price_usd = effectivePriceUsd;
					parsed.set('docs', JSON.stringify(nestedDocs));
					mutated = true;
				}
				return mutated ? parsed.toString() : body;
			}

			const cloned = JSON.parse(JSON.stringify(parsed));
			if (!updateSeatBillingPayloadObject(cloned, seats, effectivePriceInr, effectivePriceUsd)) return body;
			return JSON.stringify(cloned);
		}

		const cloned = parsed;
		if (!updateSeatBillingPayloadObject(cloned, seats, effectivePriceInr, effectivePriceUsd)) return body;
		return cloned;
	}

	function shouldLogRequest(url) {
		return (
			(url || '').includes('press.api.site.new') ||
			(url || '').includes('press.api.client.insert') ||
			(url || '').includes('press.api.client.run_doc_method') ||
			(url || '').includes('set_plan') ||
			(url || '').includes('change_plan')
		);
	}

	function patchFetch() {
		if (window.__erpSeatBillingFetchPatched) return;
		window.__erpSeatBillingFetchPatched = true;

		const originalFetch = window.fetch.bind(window);
		window.fetch = async function (input, init = {}) {
			try {
				const url = typeof input === 'string' ? input : input?.url || '';
				if (shouldLogRequest(url) && init?.body) {
					init = { ...init, body: updateRequestBody(url, init.body) };
				}
			} catch (error) {
				log('fetch patch error', error);
			}
			return originalFetch(input, init);
		};
	}

	function patchXhr() {
		if (window.__erpSeatBillingXhrPatched) return;
		window.__erpSeatBillingXhrPatched = true;

		const originalOpen = XMLHttpRequest.prototype.open;
		const originalSend = XMLHttpRequest.prototype.send;

		XMLHttpRequest.prototype.open = function (method, url, ...rest) {
			this.__erpSeatBillingUrl = url;
			return originalOpen.call(this, method, url, ...rest);
		};

		XMLHttpRequest.prototype.send = function (body) {
			try {
				if (shouldLogRequest(this.__erpSeatBillingUrl) && body) {
					body = updateRequestBody(this.__erpSeatBillingUrl, body);
				}
			} catch (error) {
				log('xhr patch error', error);
			}
			return originalSend.call(this, body);
		};
	}

	// ─────────────────────────────────────────────────────────────────────────────
	// Bootstrapping
	// ─────────────────────────────────────────────────────────────────────────────
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

	function startObserver() {
		const scan = debounce(() => {
			maybeMount().catch((error) => log('maybeMount failed', error));
		}, 100);

		const observer = new MutationObserver(scan);
		observer.observe(document.documentElement, {
			childList: true,
			subtree: true,
			attributes: true,
		});

		window.addEventListener('popstate', scan);
		window.addEventListener('hashchange', scan);
		scan();
	}

	function start() {
		if (document.readyState === 'loading') {
			document.addEventListener('DOMContentLoaded', startObserver, { once: true });
			return;
		}
		startObserver();
	}

	start();
})();
