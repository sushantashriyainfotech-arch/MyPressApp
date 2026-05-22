(function () {
	function getCurrencyCode() {
		return (
			frappe?.boot?.team?.currency ||
			frappe?.boot?.team_currency ||
			frappe?.boot?.currency ||
			frappe?.boot?.sysdefaults?.currency ||
			frappe?.session?.currency ||
			'USD'
		);
	}

	function formatMoney(value) {
		const amount = Number(value || 0);
		const currency = getCurrencyCode();
		try {
			return new Intl.NumberFormat(undefined, {
				style: 'currency',
				currency,
				currencyDisplay: 'symbol',
			}).format(amount);
		} catch (error) {
			return `${currency} ${amount.toFixed(2)}`;
		}
	}

	function formatSeatLine(frm) {
		const seats = Number(frm.doc.billable_seats || 0);
		const price = Number(frm.doc.price_per_seat || 0);
		const total = Number(frm.doc.total || 0);
		return `${seats} seats × ${formatMoney(price)} = ${formatMoney(total)}`;
	}

	frappe.ui.form.on("Invoice", {
		refresh(frm) {
			if (!frm.doc.billable_seats) return;

			frm.dashboard.set_headline(formatSeatLine(frm));
			frm.add_custom_button(__("View Seat Billing"), () => {
				window.open("/seat-billing", "_blank", "noopener");
			});
		},
		billable_seats(frm) {
			if (frm.doc.billable_seats) frm.dashboard.set_headline(formatSeatLine(frm));
		},
		price_per_seat(frm) {
			if (frm.doc.billable_seats) frm.dashboard.set_headline(formatSeatLine(frm));
		},
	});
})();
