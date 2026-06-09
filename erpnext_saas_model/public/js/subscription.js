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

	function updateSeatTotals(frm) {
		if (frm.doc.plan_type !== "Site Plan") {
			if (Number(frm.doc.total_amount || 0)) {
				frm.set_value("total_amount", 0);
			}
			return;
		}

		const seats = Number(frm.doc.billable_seats || 0);
		const price = Number(frm.doc.price_per_seat || 0);
		const total = Number((seats * price).toFixed(2));

		if (Number(frm.doc.total_amount || 0) !== total) {
			frm.set_value("total_amount", total);
			return;
		}

		frm.dashboard.set_headline(`${seats} seats × ${formatMoney(price)} = ${formatMoney(total)}`);
	}

	frappe.ui.form.on("Subscription", {
		refresh(frm) {
			if (frm.doc.plan_type !== "Site Plan") return;
			updateSeatTotals(frm);
			frm.add_custom_button(__("Seat Summary"), () => {
				frappe.msgprint({
					title: __("Current seat commitment"),
					message: `${Number(frm.doc.billable_seats || 0)} seats × ${formatMoney(frm.doc.price_per_seat)} = ${formatMoney(frm.doc.total_amount)}`,
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
		price_per_seat(frm) {
			updateSeatTotals(frm);
		},
		total_amount(frm) {
			if (frm.doc.plan_type !== "Site Plan") return;
			updateSeatTotals(frm);
		},
	});
})();
