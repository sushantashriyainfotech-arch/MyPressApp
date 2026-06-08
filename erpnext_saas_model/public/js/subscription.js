(function () {

	const DEBUG = true; // Set to false in production

	function log(...args) {
		if (DEBUG) console.log('[Seat Billing]', ...args);
	}


	function getCurrencyCode() {
		log('f-b-t currency', frappe?.boot?.team?.currency)
		log('f-b team_currency', frappe?.boot?.team_currency)
		log('f-b currency', frappe?.boot?.currency)
		log('f-b sysdefaults.currency', frappe?.boot?.sysdefaults?.currency)
		log('f-b session.currency', frappe?.session?.currency)
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

	function formatTotal(frm) {
		const seats = Number(frm.doc.billable_seats || 0);
		const price = Number(frm.doc.price_per_seat || 0);
		const total = Number(frm.doc.total_amount || seats * price);
		return `${seats} seats × ${formatMoney(price)} = ${formatMoney(total)}`;
	}

	frappe.ui.form.on("Subscription", {
		refresh(frm) {
			if (frm.doc.plan_type !== "Site Plan") return;

			// Add button to open the external Seat Billing Management dashboard
			// frm.add_custom_button(__("Open Seat Billing"), () => {
			// 	window.open(
			// 		`/seat-billing?subscription=${encodeURIComponent(frm.doc.name)}`,
			// 		"_blank",
			// 		"noopener"
			// 	);
			// });

			// Add a simple summary helper for the currently viewed commitment
			frm.add_custom_button(__("Seat Summary"), () => {
				frappe.msgprint({
					title: __("Current seat commitment"),
					message: formatTotal(frm),
					indicator: "blue",
				});
			});

			// Update dashboard headline and add informational comment
			frm.dashboard.set_headline(formatTotal(frm));
			frm.dashboard.add_comment(
				__(
					"Billing is updated immediately when seats change, and the daily snapshot picks up the new count at 6 PM."
				),
				"blue"
			);
		},
		billable_seats(frm) {
			frm.dashboard.set_headline(formatTotal(frm));
		},
		price_per_seat(frm) {
			frm.dashboard.set_headline(formatTotal(frm));
		},
		total_amount(frm) {
			frm.dashboard.set_headline(formatTotal(frm));
		},
	});
})();
