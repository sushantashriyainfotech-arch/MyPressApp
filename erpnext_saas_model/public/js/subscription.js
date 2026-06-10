(function () {
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

	function getSelectedPrice(frm) {
		const currency = (frm.doc.currency || getCurrencyCode() || "USD").toUpperCase();
		const inr = Number(frm.doc.price_inr || 0);
		const usd = Number(frm.doc.price_usd || 0);
		const hasInr = frm.doc.price_inr !== null && frm.doc.price_inr !== undefined && frm.doc.price_inr !== "";
		const hasUsd = frm.doc.price_usd !== null && frm.doc.price_usd !== undefined && frm.doc.price_usd !== "";
		return currency === "INR" ? (hasInr ? inr : usd) : (hasUsd ? usd : inr);
	}

	function formatMoney(value, currencyOverride = null) {
		const amount = Number(value || 0);
		const currency = (currencyOverride || getCurrencyCode() || "USD").toUpperCase();
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

	function updateSeatTotals(frm) {
		if (frm.doc.plan_type !== "Site Plan") {
			if (Number(frm.doc.total_amount || 0)) {
				frm.set_value("total_amount", 0);
			}
			return;
		}

		const seats = Number(frm.doc.billable_seats || 0);
		const selectedPrice = Number(getSelectedPrice(frm) || 0);
		const total = Number((seats * selectedPrice).toFixed(2));
		const currency = (frm.doc.currency || getCurrencyCode() || "USD").toUpperCase();

		if (Number(frm.doc.total_amount || 0) !== total) {
			frm.set_value("total_amount", total);
			return;
		}

		frm.dashboard.set_headline(
			`${seats} seats × ${formatMoney(selectedPrice, currency)} = ${formatMoney(total, currency)}`
		);
	}

	frappe.ui.form.on("Subscription", {
		refresh(frm) {
			if (frm.doc.plan_type !== "Site Plan") return;
			updateSeatTotals(frm);
			frm.add_custom_button(__("Seat Summary"), () => {
				const selectedPrice = getSelectedPrice(frm);
				const currency = (frm.doc.currency || getCurrencyCode() || "USD").toUpperCase();
				frappe.msgprint({
					title: __("Current seat commitment"),
					message: `${Number(frm.doc.billable_seats || 0)} seats × ${formatMoney(selectedPrice, currency)} = ${formatMoney(frm.doc.total_amount, currency)}`,
					indicator: "blue",
				});
			});
		},
		plan_type(frm) {
			updateSeatTotals(frm);
		},
		billable_seats(frm) {
			updateSeatTotals(frm);
		},
		price_inr(frm) {
			updateSeatTotals(frm);
		},
		price_usd(frm) {
			updateSeatTotals(frm);
		},
		total_amount(frm) {
			if (frm.doc.plan_type !== "Site Plan") return;
			updateSeatTotals(frm);
		},
	});
})();
