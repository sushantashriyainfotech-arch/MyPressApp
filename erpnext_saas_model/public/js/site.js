frappe.ui.form.on("Site", {
	refresh(frm) {
		// Display seat commitment in the headline for quick visual reference
		if (frm.doc.billable_seats > 1) {
			frm.dashboard.set_headline(
				__("Site is configured with {0} billable seats", [frm.doc.billable_seats])
			);
		}
	},
	billable_seats(frm) {
		// Update headline in real-time if seat count changes in the form
		if (frm.doc.billable_seats > 1) {
			frm.dashboard.set_headline(
				__("Site is configured with {0} billable seats", [frm.doc.billable_seats])
			);
		} else {
			frm.dashboard.set_headline("");
		}
	}
});
