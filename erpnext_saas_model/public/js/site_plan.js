(function () {
	function updateFieldVisibility(frm) {
		const seatBased = frm.doc.billing_type === "Seat Based";
		["price_per_seat", "min_seats", "max_seats", "next_plan"].forEach((fieldname) => {
			frm.toggle_display(fieldname, seatBased);
			frm.toggle_reqd(fieldname, seatBased && fieldname === "price_per_seat");
		});
	}

	frappe.ui.form.on("Site Plan", {
		refresh(frm) {
			updateFieldVisibility(frm);
		},
		billing_type(frm) {
			updateFieldVisibility(frm);
		},
		price_per_seat(frm) {
			if (frm.doc.billing_type !== "Seat Based") return;
			frm.dashboard.set_headline(
				`Seat billing is active at ${frm.doc.price_per_seat || 0} per seat for ${frm.doc.plan_title || frm.doc.name}.`
			);
		},
	});
})();
