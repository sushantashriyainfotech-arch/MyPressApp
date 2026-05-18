(function () {
	const state = {
		subscriptions: [],
		plans: [],
		current: null,
		logs: [],
		selectedSubscription: null,
		selectedPlan: null,
		seatCount: 1,
	};

	const els = {};

	function initElements() {
		els.subscriptionSelect = document.getElementById("subscription-select");
		els.planGrid = document.getElementById("plan-grid");
		els.seatCount = document.getElementById("seat-count");
		els.seatPrice = document.getElementById("seat-price");
		els.monthlyTotal = document.getElementById("monthly-total");
		els.currentPlanPill = document.getElementById("current-plan-pill");
		els.summaryTitle = document.getElementById("summary-title");
		els.activeUsers = document.getElementById("active-users");
		els.currentSeats = document.getElementById("current-seats");
		els.lastUpdated = document.getElementById("last-updated");
		els.logList = document.getElementById("log-list");
		els.status = document.getElementById("status");
		els.applyBtn = document.getElementById("apply-btn");
		els.reloadBtn = document.getElementById("reload-btn");
		els.openFormBtn = document.getElementById("open-form-btn");
		els.upsellCard = document.getElementById("upsell-card");
		els.upsellTitle = document.getElementById("upsell-title");
		els.upsellCopy = document.getElementById("upsell-copy");
	}

	function currency(amount) {
		const value = Number(amount || 0);
		return new Intl.NumberFormat("en-IN", {
			style: "currency",
			currency: "INR",
			maximumFractionDigits: 2,
		}).format(value);
	}

	function queryParam(name) {
		return new URLSearchParams(window.location.search).get(name);
	}

	function setStatus(message, type = "") {
		els.status.textContent = message || "";
		els.status.dataset.type = type;
	}

	async function api(method, params = {}) {
		const url = new URL(`/api/method/${method}`, window.location.origin);
		Object.entries(params).forEach(([key, value]) => {
			if (value !== undefined && value !== null && value !== "") {
				url.searchParams.set(key, value);
			}
		});

		const response = await fetch(url.toString(), {
			credentials: "same-origin",
		});
		const payload = await response.json();
		if (!response.ok || payload.exc) {
			const message =
				payload._server_messages ? JSON.parse(payload._server_messages)[0] : payload.message || "Request failed";
			const error = new Error(message);
			error.payload = payload;
			throw error;
		}
		return payload.message;
	}

	function renderSubscriptions() {
		els.subscriptionSelect.innerHTML = state.subscriptions
			.map((sub) => {
				const label = `${sub.site || sub.name} • ${sub.plan || "No plan"}`;
				return `<option value="${sub.name}" ${sub.name === state.selectedSubscription ? "selected" : ""}>${label}</option>`;
			})
			.join("");
	}

	function renderPlans() {
		els.planGrid.innerHTML = state.plans
			.map((plan) => {
				const active = plan.name === state.selectedPlan ? "active" : "";
				const maxText = plan.max_seats ? `Up to ${plan.max_seats} seats` : "No max seat cap";
				return `
					<button type="button" class="plan-card ${active}" data-plan="${plan.name}">
						<p class="plan-title">${plan.plan_title || plan.name}</p>
						<p class="plan-meta">
							<strong>${currency(plan.price_per_seat)}</strong> / seat<br />
							Min ${plan.min_seats || 1} seats<br />
							${maxText}
						</p>
					</button>
				`;
			})
			.join("");

		els.planGrid.querySelectorAll("[data-plan]").forEach((node) => {
			node.addEventListener("click", () => {
				state.selectedPlan = node.dataset.plan;
				const plan = state.plans.find((item) => item.name === state.selectedPlan);
				if (plan) {
					state.seatCount = Math.max(Number(plan.min_seats || 1), Number(state.seatCount || 1));
					els.seatCount.value = state.seatCount;
				}
				renderPlans();
				renderSummary();
			});
		});
	}

	function renderSummary() {
		const plan = state.plans.find((item) => item.name === state.selectedPlan) || state.plans[0];
		if (!plan) {
			els.summaryTitle.textContent = "Seat total";
			els.currentPlanPill.textContent = "No plan selected";
			els.seatPrice.textContent = currency(0);
			els.monthlyTotal.textContent = currency(0);
			return;
		}

		state.selectedPlan = plan.name;
		const seats = Math.max(Number(els.seatCount.value || 1), Number(plan.min_seats || 1));
		state.seatCount = seats;
		const total = seats * Number(plan.price_per_seat || 0);

		els.summaryTitle.textContent = `${plan.plan_title || plan.name} billing`;
		els.currentPlanPill.textContent = plan.name;
		els.seatPrice.textContent = currency(plan.price_per_seat);
		els.monthlyTotal.textContent = currency(total);
		els.seatCount.min = plan.min_seats || 1;
		els.seatCount.value = seats;
		els.activeUsers.textContent = state.current ? state.current.active_user_count || 0 : 0;
		els.currentSeats.textContent = state.current ? state.current.billable_seats || 0 : 0;
		els.lastUpdated.textContent = state.current?.subscription?.seats_last_updated || "-";

		const overLimit = plan.max_seats && seats > Number(plan.max_seats);
		els.upsellCard.classList.toggle("hidden", !overLimit);
		if (overLimit) {
			els.upsellTitle.textContent = plan.next_plan
				? `Move to ${plan.next_plan}`
				: "Contact support to add more users";
			els.upsellCopy.textContent = plan.next_plan
				? "The selected seat count exceeds this plan. Choose the suggested next plan to continue."
				: "This plan has reached its ceiling. Reach support to unlock more seats.";
		}
	}

	function renderLogs() {
		if (!state.logs.length) {
			els.logList.innerHTML = `<div class="log-empty">No seat changes logged yet.</div>`;
			return;
		}

		els.logList.innerHTML = state.logs
			.map((log) => {
				return `
					<article class="log-row">
						<div>
							<strong>${log.old_seats} → ${log.new_seats} seats</strong>
							<p>${log.change_type} • ${log.changed_by || "System"} • Effective from ${log.billing_effective_from || "-"}</p>
						</div>
						<div>
							<strong>${log.access_updated_at || "-"}</strong>
							<p>${log.name}</p>
						</div>
					</article>
				`;
			})
			.join("");
	}

	async function loadDashboard() {
		setStatus("Loading seat billing dashboard...");
		const subscription = queryParam("subscription") || state.selectedSubscription;
		const data = await api("erpnext_saas_model.seat_billing.get_seat_billing_dashboard", {
			subscription,
		});
		state.subscriptions = data.subscriptions || [];
		state.plans = data.plans || [];
		state.current = data.current || null;
		state.logs = data.logs || [];
		state.selectedSubscription = subscription || state.current?.name || state.subscriptions[0]?.name || null;
		state.selectedPlan = state.current?.subscription?.plan || state.plans[0]?.name || null;
		state.seatCount = state.current?.billable_seats || state.plans[0]?.min_seats || 1;

		renderSubscriptions();
		renderPlans();
		renderSummary();
		renderLogs();
		setStatus("Ready.");
	}

	async function applyChange() {
		if (!state.selectedSubscription || !state.selectedPlan) {
			setStatus("Choose a subscription and plan first.", "error");
			return;
		}

		const plan = state.plans.find((item) => item.name === state.selectedPlan);
		const seats = Number(els.seatCount.value || 1);
		if (plan && seats < Number(plan.min_seats || 1)) {
			setStatus(`You need at least ${plan.min_seats || 1} seats on this plan.`, "error");
			return;
		}

		setStatus("Applying seat change...");
		try {
			const result = await api("erpnext_saas_model.seat_billing.activate_seat_billing", {
				subscription: state.selectedSubscription,
				plan: state.selectedPlan,
				new_seats: seats,
			});

			if (result && result.error_code === "SEATS_EXCEED_PLAN_LIMIT") {
				els.upsellCard.classList.remove("hidden");
				els.upsellTitle.textContent = result.suggested_plan
					? `Move to ${result.suggested_plan}`
					: "Contact support to add more users";
				els.upsellCopy.textContent = result.suggested_plan
					? "The selected seat count exceeds the current plan. Switch to the suggested plan to continue."
					: "This plan cannot accommodate more seats. Please contact support.";
				setStatus("Seat limit reached. Review the upsell panel.", "warning");
				return;
			}

			setStatus(result?.message || "Seat change applied.", "success");
			await loadDashboard();
		} catch (error) {
			setStatus(error.message || "Could not update seats right now.", "error");
		}
	}

	function bindEvents() {
		els.subscriptionSelect.addEventListener("change", async (event) => {
			state.selectedSubscription = event.target.value;
			const next = new URL(window.location.href);
			next.searchParams.set("subscription", state.selectedSubscription);
			window.history.replaceState({}, "", next.toString());
			await loadDashboard();
		});

		els.seatCount.addEventListener("input", () => {
			renderSummary();
		});

		els.seatCount.addEventListener("change", () => {
			renderSummary();
		});

		document.querySelectorAll(".stepper-btn").forEach((button) => {
			button.addEventListener("click", () => {
				const nextSeats = Number(els.seatCount.value || 1) + Number(button.dataset.step || 0);
				els.seatCount.value = Math.max(1, nextSeats);
				renderSummary();
			});
		});

		els.applyBtn.addEventListener("click", applyChange);
		els.reloadBtn.addEventListener("click", loadDashboard);
		els.openFormBtn.addEventListener("click", () => {
			if (!state.selectedSubscription) return;
			window.location.href = `/app/subscription/${encodeURIComponent(state.selectedSubscription)}`;
		});
	}

	document.addEventListener("DOMContentLoaded", async () => {
		initElements();
		bindEvents();
		try {
			await loadDashboard();
		} catch (error) {
			setStatus(error.message || "Unable to load the dashboard.", "error");
		}
	});
})();
