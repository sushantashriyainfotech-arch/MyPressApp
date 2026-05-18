(function () {
	function formatTotal(frm) {
		const seats = Number(frm.doc.billable_seats || 0);
		const price = Number(frm.doc.price_per_seat || 0);
		const total = Number(frm.doc.total_amount || seats * price);
		return `${seats} seats × ₹${price.toFixed(2)} = ₹${total.toFixed(2)}`;
	}

	frappe.ui.form.on("Subscription", {
		refresh(frm) {
			if (frm.doc.plan_type !== "Site Plan") return;

			frm.add_custom_button(__("Open Seat Billing"), () => {
				window.open(
					`/seat-billing?subscription=${encodeURIComponent(frm.doc.name)}`,
					"_blank",
					"noopener"
				);
			});

			frm.add_custom_button(__("Seat Summary"), () => {
				frappe.msgprint({
					title: __("Current seat commitment"),
					message: formatTotal(frm),
					indicator: "blue",
				});
			});

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
