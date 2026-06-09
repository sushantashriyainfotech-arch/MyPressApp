(function () {
	const seatPlanCache = new Map();

	function getCurrencyCode() {
		return (
			frappe?.boot?.team?.currency ||
			frappe?.boot?.team_currency ||
			frappe?.boot?.currency ||
			frappe?.boot?.sysdefaults?.currency ||
			frappe?.session?.currency ||
			"USD"
		);
	}

	function formatMoney(value) {
		const amount = Number(value || 0);
		const currency = getCurrencyCode();
		try {
			return new Intl.NumberFormat(undefined, {
				style: "currency",
				currency,
				currencyDisplay: "symbol",
			}).format(amount);
		} catch (error) {
			return `${currency} ${amount.toFixed(2)}`;
		}
	}

	async function isSeatBasedPlan(plan) {
		if (!plan) return false;
		if (seatPlanCache.has(plan)) {
			return seatPlanCache.get(plan);
		}

		try {
			const response = await frappe.db.get_value("Site Plan", plan, "billing_type");
			const billingType =
				response?.message?.billing_type || response?.billing_type || response?.message || null;
			const isSeatBased = billingType === "Seat Based";
			seatPlanCache.set(plan, isSeatBased);
			return isSeatBased;
		} catch (error) {
			seatPlanCache.set(plan, false);
			return false;
		}
	}

	async function formatSeatLine(frm) {
		const items = Array.isArray(frm.doc.items) ? frm.doc.items : [];
		const seatBasedItems = [];
		const planChecks = await Promise.all(
			items
				.filter((item) => item.plan)
				.map(async (item) => ({
					item,
					isSeatBased: await isSeatBasedPlan(item.plan),
				}))
		);

		planChecks.forEach(({ item, isSeatBased }) => {
			if (isSeatBased) {
				seatBasedItems.push(item);
			}
		});

		const days = seatBasedItems.reduce((total, item) => total + Number(item.quantity || 0), 0);
		const total = seatBasedItems.reduce((sum, item) => sum + Number(item.amount || 0), 0);
		const planLabel =
			seatBasedItems.length === 1 && seatBasedItems[0].plan ? seatBasedItems[0].plan : __("Seat-based billing");
		return `${planLabel} active for ${days} day${days === 1 ? "" : "s"} = ${formatMoney(total)}`;
	}

	async function updateSeatHeadline(frm) {
		if (!frm.doc.billable_seats) return;
		const headline = await formatSeatLine(frm);
		frm.dashboard.set_headline(headline);
	}

	frappe.ui.form.on("Invoice", {
		refresh(frm) {
			if (!frm.doc.billable_seats) return;

			updateSeatHeadline(frm);
			frm.add_custom_button(__("View Seat Billing"), () => {
				window.open("/seat-billing", "_blank", "noopener");
			});
		},
		billable_seats(frm) {
			updateSeatHeadline(frm);
		},
		price_inr(frm) {
			updateSeatHeadline(frm);
		},
		price_usd(frm) {
			updateSeatHeadline(frm);
		},
		items(frm) {
			updateSeatHeadline(frm);
		},
	});
})();
